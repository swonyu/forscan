"""J2534 (PassThru) raw-CAN wire codec — foundation for the Openport/J2534-on-Mac backend.

SAE J2534 ("PassThru") is the standardised programming interface most pro-grade
pass-thru devices speak (Openport 2.0, Ford VCM/VCMII, Mongoose, etc.). Unlike
slcan's ASCII lines or the ELM327's AT commands, J2534 is a *binary* API: frames
cross as ``PASSTHRU_MSG`` records whose ``Data`` field, for the raw-CAN protocol,
is the 4-byte big-endian arbitration ID followed by the payload, and whose
``TxFlags``/``RxStatus`` carry a ``CAN_29BIT_ID`` bit that marks an extended ID.

WHAT IS TESTED HERE: the wire codec — CanFrame <-> the J2534 raw-CAN ``Data`` +
status representation — all pure and hand-derived from SAE J2534-1. WHAT IS NOT:
the real ``PassThru*`` C entry points (a vendor ``.dylib`` reached over ctypes),
which are **[NEEDS ON-CAR CHECK]**. Keeping the codec pure means the eventual
``J2534Transport`` can marshal messages against an injected PassThru library with
no hardware attached, exactly as ``SlcanTransport``/``Elm327Transport`` do today.

Scope note: this backend targets the RAW-CAN protocol (ProtocolID = CAN), letting
FordScope's own ISO-TP layer segment/reassemble — the same division of labour as
the slcan backend. The device's on-board ISO15765 protocol is deliberately unused.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Optional

from .base import (
    CanFrame,
    Transport,
    TransportError,
    TransportNotOpen,
    CAN_MAX_CLASSIC_DLC,
    CAN_MAX_11BIT_ID,
    CAN_MAX_29BIT_ID,
)

# --- SAE J2534-1 constants (spec values, not derived from any adapter) ---------
# ProtocolID for the raw-CAN channel (Table: Protocol IDs). We use raw CAN, not
# ISO15765 (6), so our own ISO-TP layer owns segmentation.
PROTOCOL_CAN = 5
# TxFlags / RxStatus bit set when the arbitration ID is a 29-bit (extended) ID.
CAN_29BIT_ID = 0x00000100
# RxStatus bit 0 (TX_MSG_TYPE): this PASSTHRU_MSG is a LOOPBACK echo of a frame
# we transmitted (J2534 devices echo their own transmits by default), NOT a frame
# received off the bus — a receiver must drop these or it "hears" its own sends.
TX_MSG_TYPE = 0x00000001
# PassThruStartMsgFilter filter type. A raw-CAN channel receives NOTHING until at
# least one filter is armed; a PASS_FILTER with an all-zero mask + all-zero pattern
# is the pass-all filter that admits every arbitration ID.
PASS_FILTER = 1

# J2534 prepends the CAN arbitration ID to the payload as 4 big-endian bytes.
_CAN_ID_LEN = 4

# Ford CAN buses: HS-CAN = 500 kbit, MS-CAN = 125 kbit. PassThruConnect takes the
# baud in bit/s, so these presets guard the caller the way slcan's Sx codes do.
_BAUDRATES = {
    250: 250_000,
    500: 500_000,
    125: 125_000,
    1000: 1_000_000,
}


def can_baudrate(kbps: int) -> int:
    """kbit preset -> J2534 ``BaudRate`` (bit/s) for ``PassThruConnect``."""
    if kbps not in _BAUDRATES:
        raise ValueError(
            f"unsupported J2534 CAN baud {kbps} kbit; choices: {sorted(_BAUDRATES)}"
        )
    return _BAUDRATES[kbps]


def encode_can_message(frame: CanFrame) -> "tuple[int, bytes]":
    """CanFrame -> ``(TxFlags, Data)`` for a J2534 raw-CAN ``PASSTHRU_MSG``.

    ``Data`` is the 4-byte big-endian arbitration ID followed by the payload;
    ``TxFlags`` carries ``CAN_29BIT_ID`` iff the frame is a 29-bit extended ID.
    The two are returned separately because the ID width lives in the flags word,
    not in the ID bytes (a small ID can be either standard or extended).
    """
    data = frame.arbitration_id.to_bytes(_CAN_ID_LEN, "big") + frame.data
    tx_flags = CAN_29BIT_ID if frame.is_extended else 0
    return tx_flags, data


def parse_can_message(data, rx_status: int = 0) -> Optional[CanFrame]:
    """``(Data, RxStatus)`` from a J2534 raw-CAN ``PASSTHRU_MSG`` -> CanFrame.

    Extended-ness is taken from the ``CAN_29BIT_ID`` ``RxStatus`` bit (per spec),
    NOT from the ID magnitude, so a small 29-bit ID round-trips correctly.
    Returns None for a runt (fewer than the 4 ID bytes), an over-length payload
    (> 8, classic CAN), or an ID outside the 11-/29-bit range — so a receiver can
    skip a malformed record without crashing, mirroring the slcan parser.
    """
    if isinstance(data, (bytes, bytearray)):
        data = bytes(data)
    if len(data) < _CAN_ID_LEN:
        return None
    arb = int.from_bytes(data[:_CAN_ID_LEN], "big")
    payload = data[_CAN_ID_LEN:]
    if len(payload) > CAN_MAX_CLASSIC_DLC:
        return None
    extended = bool(rx_status & CAN_29BIT_ID)
    if arb > (CAN_MAX_29BIT_ID if extended else CAN_MAX_11BIT_ID):
        return None
    return CanFrame(arb, payload, is_extended=extended)


# --- Message record + transport over an injected PassThru library --------------
@dataclass
class PassThruMsg:
    """The raw-CAN-relevant fields of a J2534 ``PASSTHRU_MSG`` record.

    ``data`` is the J2534 CAN ``Data`` layout the codec above produces/consumes
    (4-byte big-endian arbitration ID + payload); ``tx_flags`` carries
    ``CAN_29BIT_ID`` on transmit, and ``rx_status`` carries ``CAN_29BIT_ID`` /
    ``TX_MSG_TYPE`` on receive. The real ctypes binding packs this into the C
    struct (with ``DataSize`` = ``len(data)``); this dataclass is that struct's
    Python face for the injected-library path.
    """

    protocol_id: int
    data: bytes
    tx_flags: int = 0
    rx_status: int = 0
    timestamp: int = 0


# --- The J2534-1 PASSTHRU_MSG C ABI (the binary face of the real .dylib) --------
# SAE J2534-1 defines PASSTHRU_MSG as six unsigned-long fields then a byte array:
#     unsigned long ProtocolID, RxStatus, TxFlags, Timestamp, DataSize, ExtraDataIndex;
#     unsigned char Data[4128];
# J2534 is a Windows-origin API where `unsigned long` is 32-bit, so the leading
# fields are ``c_uint32`` — NOT ``c_ulong``, which is 64-bit under LP64 on macOS/
# Linux and would silently double every field width (sizeof 4176) and mis-align the
# struct. Spec sizeof = 6*4 + 4128 = 4152. The eventual real backend hands arrays of
# these to ``PassThruReadMsgs``/``PassThruWriteMsgs``; LOADING and CALLING that
# vendor ``.dylib`` over ctypes is **[NEEDS ON-CAR CHECK]** — only the layout +
# marshalling below are proven here, with no hardware attached.
PASSTHRU_MSG_DATA_LEN = 4128


class CPassThruMsg(ctypes.Structure):
    """ctypes image of the J2534-1 ``PASSTHRU_MSG`` C struct (see notes above)."""

    _fields_ = [
        ("ProtocolID", ctypes.c_uint32),
        ("RxStatus", ctypes.c_uint32),
        ("TxFlags", ctypes.c_uint32),
        ("Timestamp", ctypes.c_uint32),
        ("DataSize", ctypes.c_uint32),
        ("ExtraDataIndex", ctypes.c_uint32),
        ("Data", ctypes.c_ubyte * PASSTHRU_MSG_DATA_LEN),
    ]


def pack_msg(msg: PassThruMsg) -> CPassThruMsg:
    """``PassThruMsg`` dataclass -> the C ``PASSTHRU_MSG`` the ``.dylib`` expects.

    Copies ``data`` into ``Data`` and sets ``DataSize`` to its length (the count of
    valid leading bytes); the rest of the fixed 4128-byte ``Data`` array stays zero.
    Raises ``ValueError`` if ``data`` overflows the array rather than truncating or
    overrunning it.
    """
    if len(msg.data) > PASSTHRU_MSG_DATA_LEN:
        raise ValueError(
            f"PASSTHRU_MSG Data holds at most {PASSTHRU_MSG_DATA_LEN} bytes, "
            f"got {len(msg.data)}"
        )
    c = CPassThruMsg()
    c.ProtocolID = msg.protocol_id
    c.TxFlags = msg.tx_flags
    c.RxStatus = msg.rx_status
    c.Timestamp = msg.timestamp
    c.DataSize = len(msg.data)
    for i, b in enumerate(msg.data):
        c.Data[i] = b
    return c


def unpack_msg(c: CPassThruMsg) -> PassThruMsg:
    """The C ``PASSTHRU_MSG`` -> a ``PassThruMsg`` dataclass.

    Only the first ``DataSize`` bytes of ``Data`` are valid payload (per spec); the
    rest of the fixed array is ignored, so a struct buffer reused across reads never
    leaks stale trailing bytes into the decoded frame.
    """
    data = bytes(c.Data[: c.DataSize])
    return PassThruMsg(
        protocol_id=c.ProtocolID,
        data=data,
        tx_flags=c.TxFlags,
        rx_status=c.RxStatus,
        timestamp=c.Timestamp,
    )


# --- The J2534-1 PassThru* C entry-point prototypes (the callable face of the .dylib)
# SAE J2534-1 v04.04 defines a fixed set of C entry points, every one returning the
# `long` status code and taking device/channel handles + PASSTHRU_MSG pointers:
#
#     long PassThruOpen(void *pName, unsigned long *pDeviceID);
#     long PassThruConnect(unsigned long DeviceID, unsigned long ProtocolID,
#                          unsigned long Flags, unsigned long BaudRate,
#                          unsigned long *pChannelID);
#     long PassThruReadMsgs(unsigned long ChannelID, PASSTHRU_MSG *pMsg,
#                           unsigned long *pNumMsgs, unsigned long Timeout);
#     ... (14 entry points total)
#
# ctypes needs each function's restype/argtypes to marshal Python args to the C ABI.
# As with CPassThruMsg above, J2534's `unsigned long` is the 32-bit Windows-origin
# type -> c_uint32 (NOT c_ulong, which is 64-bit under LP64 on macOS/Linux and would
# mis-marshal every handle); the status `long` -> c_int32; PASSTHRU_MSG* ->
# POINTER(CPassThruMsg). Hand-derived from SAE J2534-1. LOADING a real vendor .dylib
# and CALLING these entry points needs the adapter + vendor driver and is
# **[NEEDS ON-CAR CHECK]** — only bind_prototypes over an injected library (and
# load_library's missing-library error path) is proven here with no hardware.
_J2534_LONG = ctypes.c_int32                        # J2534 status return (`long`)
_J2534_ULONG = ctypes.c_uint32                      # J2534 `unsigned long` (32-bit)
_J2534_ULONG_P = ctypes.POINTER(ctypes.c_uint32)    # `unsigned long *` (out param)
_J2534_MSG_P = ctypes.POINTER(CPassThruMsg)         # `PASSTHRU_MSG *`
_J2534_VOID_P = ctypes.c_void_p                     # `void *`
_J2534_CHAR_P = ctypes.c_char_p                     # `char *`

PASSTHRU_PROTOTYPES = {
    "PassThruOpen": (_J2534_LONG, (_J2534_VOID_P, _J2534_ULONG_P)),
    "PassThruClose": (_J2534_LONG, (_J2534_ULONG,)),
    "PassThruConnect": (
        _J2534_LONG,
        (_J2534_ULONG, _J2534_ULONG, _J2534_ULONG, _J2534_ULONG, _J2534_ULONG_P),
    ),
    "PassThruDisconnect": (_J2534_LONG, (_J2534_ULONG,)),
    "PassThruReadMsgs": (
        _J2534_LONG,
        (_J2534_ULONG, _J2534_MSG_P, _J2534_ULONG_P, _J2534_ULONG),
    ),
    "PassThruWriteMsgs": (
        _J2534_LONG,
        (_J2534_ULONG, _J2534_MSG_P, _J2534_ULONG_P, _J2534_ULONG),
    ),
    "PassThruStartPeriodicMsg": (
        _J2534_LONG,
        (_J2534_ULONG, _J2534_MSG_P, _J2534_ULONG_P, _J2534_ULONG),
    ),
    "PassThruStopPeriodicMsg": (_J2534_LONG, (_J2534_ULONG, _J2534_ULONG)),
    "PassThruStartMsgFilter": (
        _J2534_LONG,
        (_J2534_ULONG, _J2534_ULONG, _J2534_MSG_P, _J2534_MSG_P, _J2534_MSG_P,
         _J2534_ULONG_P),
    ),
    "PassThruStopMsgFilter": (_J2534_LONG, (_J2534_ULONG, _J2534_ULONG)),
    "PassThruSetProgrammingVoltage": (
        _J2534_LONG,
        (_J2534_ULONG, _J2534_ULONG, _J2534_ULONG),
    ),
    "PassThruReadVersion": (
        _J2534_LONG,
        (_J2534_ULONG, _J2534_CHAR_P, _J2534_CHAR_P, _J2534_CHAR_P),
    ),
    "PassThruGetLastError": (_J2534_LONG, (_J2534_CHAR_P,)),
    "PassThruIoctl": (
        _J2534_LONG,
        (_J2534_ULONG, _J2534_ULONG, _J2534_VOID_P, _J2534_VOID_P),
    ),
}


def bind_prototypes(lib):
    """Apply the SAE J2534-1 ctypes prototypes to a loaded PassThru library.

    ``lib`` is a ``ctypes.CDLL`` (or any object exposing the ``PassThru*`` entry
    points as attributes with settable ``restype``/``argtypes`` — e.g. an injected
    fake). Sets each function's ``restype``/``argtypes`` from ``PASSTHRU_PROTOTYPES``
    so ctypes marshals Python args to the C ABI, and returns ``lib`` so callers can
    chain. Purely declarative — no entry point is CALLED here, so it runs with no
    hardware. Actually LOADING a vendor ``.dylib`` and INVOKING these functions is
    **[NEEDS ON-CAR CHECK]**.
    """
    for name, (restype, argtypes) in PASSTHRU_PROTOTYPES.items():
        func = getattr(lib, name)
        func.restype = restype
        func.argtypes = list(argtypes)
    return lib


def load_library(path: str):
    """Load a J2534 vendor library from ``path`` and bind the ``PassThru*`` prototypes.

    Thin wrapper over ``bind_prototypes(ctypes.CDLL(path))``. Loading a REAL Openport/
    Ford ``.dylib`` and calling into it needs the adapter + vendor driver and is
    **[NEEDS ON-CAR CHECK]**; the suite exercises only ``bind_prototypes`` over an
    injected fake plus this function's missing-library error path (``OSError``).
    """
    return bind_prototypes(ctypes.CDLL(path))


# --- SAE J2534-1 return codes (spec values, hand-derived from the standard's
# return-value table, NOT read back from any adapter) --------------------------
# Every PassThru* entry point returns a `long` status; 0 == success. ReadMsgs uses
# ERR_BUFFER_EMPTY (0x10) as the ordinary "no message arrived within Timeout"
# signal, so the adapter maps THAT one status to an empty batch, not an error.
STATUS_NOERROR = 0x00
ERR_BUFFER_EMPTY = 0x10


class J2534Error(TransportError):
    """A ``PassThru*`` entry point returned a non-zero J2534 status code.

    Carries the failing ``function`` name and the raw ``status`` so callers can map
    it (e.g. via ``PassThruGetLastError``). ReadMsgs' ``ERR_BUFFER_EMPTY`` is NOT
    raised — the adapter treats it as an empty receive per the spec.
    """

    def __init__(self, function: str, status: int) -> None:
        self.function = function
        self.status = status
        super().__init__(f"{function} returned J2534 status 0x{status:02X}")


class PassThruAdapter:
    """Wrap a bound J2534 library and present the ``J2534Transport`` ``pt`` duck-type.

    ``lib`` is a ``ctypes.CDLL`` with the ``PassThru*`` prototypes applied by
    :func:`bind_prototypes` (or any object exposing those entry points as callables,
    e.g. an injected fake). Each method marshals Python <-> the J2534 C ABI:

    * out handles (device / channel / filter id, message count) travel as
      ``ctypes.pointer(c_uint32())`` and are read back from ``.value``;
    * ``PASSTHRU_MSG`` records cross as ``CPassThruMsg`` arrays via
      :func:`pack_msg` / :func:`unpack_msg`;
    * a non-zero status raises :class:`J2534Error`, EXCEPT ReadMsgs'
      ``ERR_BUFFER_EMPTY`` which maps to an empty list (the spec's timeout signal).

    This is the thin seam between the callable ``.dylib`` face (proven here over an
    injected fake, no hardware) and the transport, i.e. the ``pt`` object
    :class:`J2534Transport` drives. LOADING a real vendor ``.dylib`` and CALLING
    these entry points on a live bus is **[NEEDS ON-CAR CHECK]**.
    """

    def __init__(self, lib, *, read_batch: int = 8) -> None:
        self._lib = lib
        self._read_batch = read_batch

    @staticmethod
    def _check(function: str, status: int) -> None:
        if status != STATUS_NOERROR:
            raise J2534Error(function, status)

    def open(self):
        device_id = ctypes.c_uint32()
        self._check("PassThruOpen", self._lib.PassThruOpen(None, ctypes.pointer(device_id)))
        return device_id.value

    def connect(self, device_id, protocol_id, flags, baudrate):
        channel_id = ctypes.c_uint32()
        self._check(
            "PassThruConnect",
            self._lib.PassThruConnect(
                device_id, protocol_id, flags, baudrate, ctypes.pointer(channel_id)
            ),
        )
        return channel_id.value

    def start_msg_filter(self, channel_id, filter_type, mask, pattern):
        filter_id = ctypes.c_uint32()
        c_mask = pack_msg(mask)
        c_pattern = pack_msg(pattern)
        self._check(
            "PassThruStartMsgFilter",
            self._lib.PassThruStartMsgFilter(
                channel_id,
                filter_type,
                ctypes.pointer(c_mask),
                ctypes.pointer(c_pattern),
                None,  # pFlowControlMsg: NULL for a PASS/BLOCK filter (raw CAN)
                ctypes.pointer(filter_id),
            ),
        )
        return filter_id.value

    def write_msgs(self, channel_id, msgs, timeout):
        count = len(msgs)
        arr = (CPassThruMsg * count)(*[pack_msg(m) for m in msgs])
        num = ctypes.c_uint32(count)
        self._check(
            "PassThruWriteMsgs",
            self._lib.PassThruWriteMsgs(channel_id, arr, ctypes.pointer(num), timeout),
        )

    def read_msgs(self, channel_id, timeout):
        arr = (CPassThruMsg * self._read_batch)()
        num = ctypes.c_uint32(self._read_batch)
        status = self._lib.PassThruReadMsgs(
            channel_id, arr, ctypes.pointer(num), timeout
        )
        if status == ERR_BUFFER_EMPTY:
            return []  # spec's ordinary "nothing within Timeout" — not a failure
        self._check("PassThruReadMsgs", status)
        return [unpack_msg(arr[i]) for i in range(num.value)]

    def disconnect(self, channel_id):
        self._check("PassThruDisconnect", self._lib.PassThruDisconnect(channel_id))

    def close(self, device_id):
        self._check("PassThruClose", self._lib.PassThruClose(device_id))


# Fixed PassThruWriteMsgs timeout (ms): transmit is near-instant on a live bus, so
# this only bounds a stuck adapter. Receive timeouts come from recv()'s argument.
_WRITE_TIMEOUT_MS = 100


class J2534Transport(Transport):
    """Raw-CAN transport over an injected J2534 (PassThru) library.

    The injected ``pt`` object is a duck-typed PassThru library exposing::

        open() -> device_id
        connect(device_id, protocol_id, flags, baudrate) -> channel_id
        start_msg_filter(channel_id, filter_type, mask, pattern) -> filter_id
        write_msgs(channel_id, msgs, timeout_ms) -> None
        read_msgs(channel_id, timeout_ms) -> list[PassThruMsg]
        disconnect(channel_id) -> None
        close(device_id) -> None

    The REAL library is a vendor ``.dylib`` reached over ctypes, and THAT binding
    is **[NEEDS ON-CAR CHECK]**. Here any object with these methods drives the
    transport, so the ``CanFrame`` <-> ``PASSTHRU_MSG`` marshalling and the channel
    lifecycle are proven with no hardware attached — exactly as ``SlcanTransport``
    / ``Elm327Transport`` are proven over an injected serial port.

    Scope: RAW CAN (``PROTOCOL_CAN``); FordScope's own ISO-TP layer owns
    segmentation, so the device's on-board ISO15765 protocol is deliberately unused.
    """

    def __init__(self, pt, *, baudrate_kbps: int = 500, connect_flags: int = 0) -> None:
        self._pt = pt
        self.baudrate_kbps = baudrate_kbps
        self.connect_flags = connect_flags
        self._device_id = None
        self._channel_id = None
        self._open = False
        self._rx: "list[PassThruMsg]" = []

    def open(self) -> None:
        self._device_id = self._pt.open()
        self._channel_id = self._pt.connect(
            self._device_id,
            PROTOCOL_CAN,
            self.connect_flags,
            can_baudrate(self.baudrate_kbps),
        )
        # A J2534 raw-CAN channel hears NOTHING until a filter is armed; the
        # pass-all filter (zero mask, zero pattern) admits every arbitration ID.
        zero = b"\x00\x00\x00\x00"
        self._pt.start_msg_filter(
            self._channel_id,
            PASS_FILTER,
            PassThruMsg(PROTOCOL_CAN, zero),
            PassThruMsg(PROTOCOL_CAN, zero),
        )
        self._open = True

    def close(self) -> None:
        try:
            if self._channel_id is not None:
                self._pt.disconnect(self._channel_id)
        except Exception:
            pass  # adapter may be gone — still release the device below
        self._channel_id = None
        try:
            if self._device_id is not None:
                self._pt.close(self._device_id)
        except Exception:
            pass
        self._device_id = None
        self._open = False
        self._rx.clear()

    @property
    def is_open(self) -> bool:
        return self._open

    def send(self, frame: CanFrame) -> None:
        if not self._open:
            raise TransportNotOpen("send() before open()")
        tx_flags, data = encode_can_message(frame)
        msg = PassThruMsg(PROTOCOL_CAN, data, tx_flags=tx_flags)
        self._pt.write_msgs(self._channel_id, [msg], _WRITE_TIMEOUT_MS)

    def recv(self, timeout: float = 1.0) -> Optional[CanFrame]:
        if not self._open:
            raise TransportNotOpen("recv() before open()")
        timeout_ms = int(timeout * 1000)
        while True:
            if not self._rx:
                msgs = self._pt.read_msgs(self._channel_id, timeout_ms)
                if not msgs:
                    return None  # nothing arrived within the timeout
                self._rx.extend(msgs)
            msg = self._rx.pop(0)
            if msg.rx_status & TX_MSG_TYPE:
                continue  # our own transmit loopback echo, not a received frame
            frame = parse_can_message(msg.data, msg.rx_status)
            if frame is not None:
                return frame
            # malformed/non-data record — skip it, keep draining (mirrors slcan)
