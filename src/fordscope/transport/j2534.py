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
