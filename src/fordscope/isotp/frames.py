"""ISO-TP (ISO 15765-2) frame codec — the four PCI frame types.

Pure, stateless encode/parse of the CAN payloads that carry a segmented
diagnostic message. The stateful segmentation/reassembly + flow-control state
machine is built on top of these primitives in ``transport_layer`` (next step).

Byte formats — classic 8-byte CAN, "normal" addressing — hand-derived from
ISO 15765-2 (NOT from any code under test):

    Single Frame (SF):   [0x0L]        + L data bytes         L = 1..7
    First Frame  (FF):   [0x1H, 0xLL]  + 6 data bytes         total len = 0xHLL (12-bit)
    Consecutive  (CF):   [0x2S]        + up to 7 data bytes   S = 4-bit sequence number
    Flow Control (FC):   [0x3F, BS, ST]                       F = flow status

The high nibble of byte 0 is the PCI (frame type). SF length 0 and FF length 0
are CAN-FD / 32-bit-length escapes and are explicitly unsupported here (classic
CAN only, ISO-TP messages up to 4095 bytes).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

CAN_FRAME_LEN = 8
SF_MAX_DATA = 7          # SF carries at most 7 data bytes (8 - 1 PCI byte)
FF_FIRST_DATA = 6        # FF always carries exactly 6 data bytes (8 - 2 PCI bytes)
CF_MAX_DATA = 7          # CF carries at most 7 data bytes (8 - 1 PCI byte)
ISOTP_MAX_CLASSIC_LEN = 0xFFF  # 4095, the 12-bit FF length ceiling
DEFAULT_PAD_BYTE = 0x00


class IsoTpFrameType(IntEnum):
    SINGLE = 0x0
    FIRST = 0x1
    CONSECUTIVE = 0x2
    FLOW_CONTROL = 0x3


class FlowStatus(IntEnum):
    CONTINUE = 0x0   # clear-to-send
    WAIT = 0x1
    OVERFLOW = 0x2   # abort


@dataclass(frozen=True)
class IsoTpPci:
    """A parsed ISO-TP frame. Fields not relevant to the type stay None."""

    type: IsoTpFrameType
    data: bytes = b""                 # SF/CF/FF carried data bytes
    length: "int | None" = None       # SF data length, or FF total message length
    sequence_number: "int | None" = None   # CF 4-bit sequence number
    flow_status: "int | None" = None  # FC flow status (compare to FlowStatus.*)
    block_size: "int | None" = None   # FC block size
    stmin: "int | None" = None        # FC separation-time-minimum byte


def _pad(payload: bytes, pad_byte: int, pad_to_8: bool) -> bytes:
    if pad_to_8 and len(payload) < CAN_FRAME_LEN:
        return payload + bytes([pad_byte]) * (CAN_FRAME_LEN - len(payload))
    return payload


def encode_single_frame(
    data: bytes, *, pad_byte: int = DEFAULT_PAD_BYTE, pad_to_8: bool = True
) -> bytes:
    """A whole message that fits in one frame (1..7 bytes)."""
    if not 1 <= len(data) <= SF_MAX_DATA:
        raise ValueError(f"SF data must be 1..{SF_MAX_DATA} bytes, got {len(data)}")
    payload = bytes([len(data)]) + bytes(data)  # PCI nibble 0x0 | length
    return _pad(payload, pad_byte, pad_to_8)


def encode_first_frame(
    total_length: int,
    first_data: bytes,
    *,
    pad_byte: int = DEFAULT_PAD_BYTE,
    pad_to_8: bool = True,
) -> bytes:
    """The opening frame of a multi-frame message (total length 8..4095)."""
    if not (SF_MAX_DATA + 1) <= total_length <= ISOTP_MAX_CLASSIC_LEN:
        raise ValueError(
            f"FF total length must be {SF_MAX_DATA + 1}..{ISOTP_MAX_CLASSIC_LEN}, "
            f"got {total_length}"
        )
    if len(first_data) != FF_FIRST_DATA:
        raise ValueError(f"FF carries exactly {FF_FIRST_DATA} data bytes, got {len(first_data)}")
    b0 = (IsoTpFrameType.FIRST << 4) | ((total_length >> 8) & 0x0F)
    b1 = total_length & 0xFF
    payload = bytes([b0, b1]) + bytes(first_data)
    return _pad(payload, pad_byte, pad_to_8)


def encode_consecutive_frame(
    sequence_number: int,
    data: bytes,
    *,
    pad_byte: int = DEFAULT_PAD_BYTE,
    pad_to_8: bool = True,
) -> bytes:
    """A follow-on data frame; sequence_number wraps 0..15."""
    if not 0 <= sequence_number <= 0x0F:
        raise ValueError(f"CF sequence number must be 0..15, got {sequence_number}")
    if not 1 <= len(data) <= CF_MAX_DATA:
        raise ValueError(f"CF data must be 1..{CF_MAX_DATA} bytes, got {len(data)}")
    b0 = (IsoTpFrameType.CONSECUTIVE << 4) | (sequence_number & 0x0F)
    payload = bytes([b0]) + bytes(data)
    return _pad(payload, pad_byte, pad_to_8)


def encode_flow_control(
    flow_status: int = FlowStatus.CONTINUE,
    block_size: int = 0,
    stmin: int = 0,
    *,
    pad_byte: int = DEFAULT_PAD_BYTE,
    pad_to_8: bool = True,
) -> bytes:
    """Receiver -> sender flow control (CTS / Wait / Overflow)."""
    if not 0 <= int(flow_status) <= 0x0F:
        raise ValueError(f"flow status must be 0..15, got {flow_status}")
    if not 0 <= block_size <= 0xFF:
        raise ValueError(f"block size must be a byte, got {block_size}")
    if not 0 <= stmin <= 0xFF:
        raise ValueError(f"stmin must be a byte, got {stmin}")
    b0 = (IsoTpFrameType.FLOW_CONTROL << 4) | (int(flow_status) & 0x0F)
    payload = bytes([b0, block_size & 0xFF, stmin & 0xFF])
    return _pad(payload, pad_byte, pad_to_8)


def pci_type(payload: bytes) -> IsoTpFrameType:
    """The frame type from byte 0's high nibble. Raises on empty / unknown."""
    if not payload:
        raise ValueError("empty CAN payload has no PCI")
    nibble = payload[0] >> 4
    try:
        return IsoTpFrameType(nibble)
    except ValueError:
        raise ValueError(f"unknown ISO-TP PCI nibble 0x{nibble:X}") from None


def parse_isotp(payload: bytes) -> IsoTpPci:
    """Parse one CAN payload into a typed ISO-TP frame.

    CF/FF ``data`` may include trailing CAN padding; the reassembly layer trims
    to the message's declared total length — that context does not exist here.
    """
    ftype = pci_type(payload)

    if ftype is IsoTpFrameType.SINGLE:
        length = payload[0] & 0x0F
        if length == 0:
            raise ValueError("SF length 0 (CAN-FD escape) unsupported")
        if length > SF_MAX_DATA:
            raise ValueError(f"SF length {length} exceeds {SF_MAX_DATA}")
        data = payload[1 : 1 + length]
        if len(data) < length:
            raise ValueError("SF truncated: fewer data bytes than declared length")
        return IsoTpPci(IsoTpFrameType.SINGLE, data=bytes(data), length=length)

    if ftype is IsoTpFrameType.FIRST:
        if len(payload) < 2:
            raise ValueError("FF truncated: missing length byte")
        total = ((payload[0] & 0x0F) << 8) | payload[1]
        if total == 0:
            raise ValueError("FF length 0 (32-bit length escape) unsupported")
        if total < SF_MAX_DATA + 1:
            raise ValueError(
                f"FF total length {total} below multi-frame minimum {SF_MAX_DATA + 1} "
                f"(lengths 1..{SF_MAX_DATA} must use a Single Frame)"
            )
        first = payload[2 : 2 + FF_FIRST_DATA]
        return IsoTpPci(IsoTpFrameType.FIRST, data=bytes(first), length=total)

    if ftype is IsoTpFrameType.CONSECUTIVE:
        sn = payload[0] & 0x0F
        return IsoTpPci(
            IsoTpFrameType.CONSECUTIVE, data=bytes(payload[1:]), sequence_number=sn
        )

    # FLOW_CONTROL
    fs = payload[0] & 0x0F
    bs = payload[1] if len(payload) > 1 else 0
    st = payload[2] if len(payload) > 2 else 0
    return IsoTpPci(
        IsoTpFrameType.FLOW_CONTROL, flow_status=fs, block_size=bs, stmin=st
    )
