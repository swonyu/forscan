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

from typing import Optional

from .base import (
    CanFrame,
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
