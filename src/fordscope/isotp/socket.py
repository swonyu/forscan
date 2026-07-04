"""ISO-TP transport layer: send/receive an arbitrary-length message over CAN.

``IsoTpSocket`` wraps a ``Transport`` and a (tx_id, rx_id) address pair and
implements the segmentation + flow-control state machine on top of the frame
codec:

  send(payload):
    <= 7 bytes  -> one Single Frame
    >  7 bytes  -> First Frame, await Flow Control, stream Consecutive Frames,
                   honouring the receiver's block size and STmin

  recv():
    Single Frame -> return it
    First Frame  -> send Flow Control (CTS), collect Consecutive Frames in
                    sequence, reassemble to the declared length

STmin *timing* is honoured via an injectable ``sleep`` (a no-op by default, so
the logic is deterministic under test); the exact on-wire separation is only
meaningful against real hardware and is labelled as such.
"""
from __future__ import annotations

from typing import Callable, Optional

from ..transport.base import CanFrame, Transport
from .frames import (
    IsoTpFrameType,
    FlowStatus,
    IsoTpPci,
    encode_single_frame,
    encode_first_frame,
    encode_consecutive_frame,
    encode_flow_control,
    parse_isotp,
    SF_MAX_DATA,
    FF_FIRST_DATA,
    CF_MAX_DATA,
    ISOTP_MAX_CLASSIC_LEN,
)


class IsoTpError(Exception):
    """Base class for ISO-TP transport-layer failures."""


class IsoTpTimeout(IsoTpError):
    """A required frame did not arrive in time."""


class IsoTpOverflow(IsoTpError):
    """The receiver reported a buffer overflow (flow status = 2)."""


class IsoTpSequenceError(IsoTpError):
    """A consecutive frame arrived out of sequence."""


def stmin_to_seconds(stmin: int) -> float:
    """Convert an ISO-TP STmin byte to a delay in seconds.

    0x00..0x7F  -> that many milliseconds.
    0xF1..0xF9  -> 100..900 microseconds.
    Reserved    -> treated as the 127 ms maximum (ISO 15765-2 §6.5.5.5).
    """
    if 0x00 <= stmin <= 0x7F:
        return stmin / 1000.0
    if 0xF1 <= stmin <= 0xF9:
        return (stmin - 0xF0) / 10000.0
    return 0x7F / 1000.0


class IsoTpSocket:
    def __init__(
        self,
        transport: Transport,
        tx_id: int,
        rx_id: int,
        *,
        is_extended: bool = False,
        pad_byte: int = 0x00,
        pad_to_8: bool = True,
        rx_block_size: int = 0,
        rx_stmin: int = 0,
        recv_timeout: float = 1.0,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.transport = transport
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.is_extended = is_extended
        self.pad_byte = pad_byte
        self.pad_to_8 = pad_to_8
        self.rx_block_size = rx_block_size  # our FC block size when receiving (0 = all)
        self.rx_stmin = rx_stmin
        self.recv_timeout = recv_timeout
        self._sleep: Callable[[float], None] = sleep or (lambda _s: None)

    # --- framing helpers -------------------------------------------------
    def _emit(self, payload: bytes) -> None:
        self.transport.send(
            CanFrame(self.tx_id, payload, is_extended=self.is_extended)
        )

    def _sf(self, data: bytes) -> bytes:
        return encode_single_frame(data, pad_byte=self.pad_byte, pad_to_8=self.pad_to_8)

    def _ff(self, total: int, first: bytes) -> bytes:
        return encode_first_frame(total, first, pad_byte=self.pad_byte, pad_to_8=self.pad_to_8)

    def _cf(self, sn: int, data: bytes) -> bytes:
        return encode_consecutive_frame(sn, data, pad_byte=self.pad_byte, pad_to_8=self.pad_to_8)

    def _fc(self, status: int, bs: int, st: int) -> bytes:
        return encode_flow_control(status, bs, st, pad_byte=self.pad_byte, pad_to_8=self.pad_to_8)

    def _recv_matching(self, timeout: float) -> Optional[CanFrame]:
        """Next frame addressed to us, skipping traffic for other IDs."""
        frame = self.transport.recv(timeout)
        while frame is not None and frame.arbitration_id != self.rx_id:
            frame = self.transport.recv(timeout)
        return frame

    # --- send ------------------------------------------------------------
    def send(self, payload: bytes) -> None:
        if len(payload) == 0:
            raise ValueError("cannot send an empty ISO-TP payload")
        if len(payload) > ISOTP_MAX_CLASSIC_LEN:
            raise IsoTpError(
                f"payload {len(payload)} bytes exceeds classic ISO-TP max "
                f"{ISOTP_MAX_CLASSIC_LEN}"
            )
        if len(payload) <= SF_MAX_DATA:
            self._emit(self._sf(payload))
            return
        self._emit(self._ff(len(payload), payload[:FF_FIRST_DATA]))
        fc = self._await_cts()
        self._stream_cfs(payload[FF_FIRST_DATA:], fc)

    def _await_cts(self) -> IsoTpPci:
        for _ in range(16):  # bounded WAIT handling
            frame = self._recv_matching(self.recv_timeout)
            if frame is None:
                raise IsoTpTimeout("no flow-control frame received")
            pci = parse_isotp(frame.data)
            if pci.type is not IsoTpFrameType.FLOW_CONTROL:
                raise IsoTpError(f"expected flow control, got {pci.type.name}")
            if pci.flow_status == FlowStatus.OVERFLOW:
                raise IsoTpOverflow("receiver reported overflow")
            if pci.flow_status == FlowStatus.CONTINUE:
                return pci
            if pci.flow_status != FlowStatus.WAIT:
                # ISO 15765-2 §6.5.5.3: a reserved FlowStatus (0x3-0xF) is an N_PCI
                # error (N_INVALID_FS) — abort, don't reinterpret it as WAIT.
                raise IsoTpError(
                    f"invalid flow-control FlowStatus 0x{int(pci.flow_status):X} (reserved)"
                )
            # WAIT (0x1): loop and read the next FC
        raise IsoTpTimeout("too many flow-control WAIT frames")

    def _stream_cfs(self, rest: bytes, fc: IsoTpPci) -> None:
        block_size = fc.block_size or 0
        stmin = fc.stmin or 0
        sn = 1
        in_block = 0
        first_after_cts = True
        i = 0
        while i < len(rest):
            chunk = rest[i : i + CF_MAX_DATA]
            if not first_after_cts:
                self._sleep(stmin_to_seconds(stmin))
            self._emit(self._cf(sn, chunk))
            first_after_cts = False
            i += len(chunk)
            sn = (sn + 1) & 0x0F
            in_block += 1
            if block_size != 0 and in_block == block_size and i < len(rest):
                fc = self._await_cts()
                block_size = fc.block_size or 0
                stmin = fc.stmin or 0
                in_block = 0
                first_after_cts = True

    # --- recv ------------------------------------------------------------
    def recv(self, timeout: Optional[float] = None) -> Optional[bytes]:
        timeout = self.recv_timeout if timeout is None else timeout
        frame = self._recv_matching(timeout)
        if frame is None:
            return None
        pci = parse_isotp(frame.data)
        if pci.type is IsoTpFrameType.SINGLE:
            return pci.data
        if pci.type is IsoTpFrameType.FIRST:
            return self._reassemble(pci)
        raise IsoTpError(f"unexpected {pci.type.name} at start of message")

    def _reassemble(self, ff: IsoTpPci) -> bytes:
        total = ff.length or 0
        buf = bytearray(ff.data[: min(FF_FIRST_DATA, total)])
        self._emit(self._fc(FlowStatus.CONTINUE, self.rx_block_size, self.rx_stmin))
        expected_sn = 1
        in_block = 0
        while len(buf) < total:
            frame = self._recv_matching(self.recv_timeout)
            if frame is None:
                raise IsoTpTimeout("timed out waiting for a consecutive frame")
            pci = parse_isotp(frame.data)
            if pci.type is not IsoTpFrameType.CONSECUTIVE:
                raise IsoTpError(f"expected consecutive frame, got {pci.type.name}")
            if pci.sequence_number != expected_sn:
                raise IsoTpSequenceError(
                    f"expected SN {expected_sn}, got {pci.sequence_number}"
                )
            buf.extend(pci.data[: total - len(buf)])
            expected_sn = (expected_sn + 1) & 0x0F
            in_block += 1
            if self.rx_block_size != 0 and in_block == self.rx_block_size and len(buf) < total:
                self._emit(self._fc(FlowStatus.CONTINUE, self.rx_block_size, self.rx_stmin))
                in_block = 0
        return bytes(buf)
