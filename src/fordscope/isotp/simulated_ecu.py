"""A simulated ISO-TP ECU endpoint — a stateful ``SimulatorTransport`` responder.

It speaks the ECU side of ISO-TP so the whole diagnostic stack can be exercised
without hardware: it reassembles multi-frame requests, hands the reassembled
application payload to a user ``handler``, and segments the handler's response
back out (Single Frame, or First Frame + Consecutive Frames after the client's
Flow Control). This same endpoint is reused to simulate UDS / OBD-II ECUs by
supplying a smarter handler.

Scope note: models the common BS=0 exchange (the ECU grants clear-to-send once
and the client requests all frames at once). Block-size>0 on the *receive* side
of the ECU is not modelled here; the client's send path handles ECU BS>0 and is
tested separately with a scripted responder.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional, Tuple

from ..transport.base import CanFrame
from .frames import (
    IsoTpFrameType,
    FlowStatus,
    encode_single_frame,
    encode_first_frame,
    encode_consecutive_frame,
    encode_flow_control,
    parse_isotp,
    SF_MAX_DATA,
    FF_FIRST_DATA,
    CF_MAX_DATA,
)

Handler = Callable[[bytes], Optional[bytes]]


class SimulatedIsoTpEcu:
    def __init__(
        self,
        handler: Handler,
        *,
        request_id: int,
        response_id: int,
        is_extended: bool = False,
        fc_block_size: int = 0,
        fc_stmin: int = 0,
        pad_byte: int = 0x00,
        pad_to_8: bool = True,
    ) -> None:
        self.handler = handler
        self.request_id = request_id
        self.response_id = response_id
        self.is_extended = is_extended
        self.fc_block_size = fc_block_size
        self.fc_stmin = fc_stmin
        self.pad_byte = pad_byte
        self.pad_to_8 = pad_to_8
        # last fully-reassembled request payload, for test inspection
        self.last_request: Optional[bytes] = None
        # incoming request reassembly state
        self._rx = bytearray()
        self._rx_total = 0
        self._rx_sn = 1
        # outgoing multi-frame response state (awaiting client Flow Control)
        self._tx_rest = b""
        self._tx_sn = 1

    def _frame(self, data: bytes) -> CanFrame:
        return CanFrame(self.response_id, data, is_extended=self.is_extended)

    def __call__(self, frame: CanFrame) -> Tuple[CanFrame, ...]:
        if frame.arbitration_id != self.request_id:
            return ()
        pci = parse_isotp(frame.data)

        if pci.type is IsoTpFrameType.SINGLE:
            return self._respond(pci.data)

        if pci.type is IsoTpFrameType.FIRST:
            self._rx = bytearray(pci.data[: min(FF_FIRST_DATA, pci.length or 0)])
            self._rx_total = pci.length or 0
            self._rx_sn = 1
            fc = encode_flow_control(
                FlowStatus.CONTINUE, self.fc_block_size, self.fc_stmin,
                pad_byte=self.pad_byte, pad_to_8=self.pad_to_8,
            )
            return (self._frame(fc),)

        if pci.type is IsoTpFrameType.CONSECUTIVE:
            if pci.sequence_number != self._rx_sn:
                return ()  # drop out-of-sequence frame
            self._rx.extend(pci.data[: self._rx_total - len(self._rx)])
            self._rx_sn = (self._rx_sn + 1) & 0x0F
            if len(self._rx) >= self._rx_total and self._rx_total:
                request = bytes(self._rx)
                self._rx = bytearray()
                self._rx_total = 0
                return self._respond(request)
            return ()

        # FLOW_CONTROL: client granting us to send our pending response CFs
        if pci.flow_status == FlowStatus.CONTINUE:
            return self._flush_response_cfs()
        return ()

    def _respond(self, request: bytes) -> Tuple[CanFrame, ...]:
        self.last_request = request
        response = self.handler(request)
        if response is None:
            return ()
        if len(response) <= SF_MAX_DATA:
            sf = encode_single_frame(response, pad_byte=self.pad_byte, pad_to_8=self.pad_to_8)
            return (self._frame(sf),)
        ff = encode_first_frame(
            len(response), response[:FF_FIRST_DATA],
            pad_byte=self.pad_byte, pad_to_8=self.pad_to_8,
        )
        self._tx_rest = response[FF_FIRST_DATA:]
        self._tx_sn = 1
        return (self._frame(ff),)

    def _flush_response_cfs(self) -> Tuple[CanFrame, ...]:
        frames = []
        rest, sn, i = self._tx_rest, self._tx_sn, 0
        while i < len(rest):
            chunk = rest[i : i + CF_MAX_DATA]
            cf = encode_consecutive_frame(sn, chunk, pad_byte=self.pad_byte, pad_to_8=self.pad_to_8)
            frames.append(self._frame(cf))
            i += len(chunk)
            sn = (sn + 1) & 0x0F
        self._tx_rest = b""
        return tuple(frames)


def multiplex(*responders: Callable[[CanFrame], Iterable[CanFrame]]):
    """Combine several ECU responders onto one simulated bus.

    Each responder ignores frames not addressed to it (returns nothing), so only
    the module matching a request replies — modelling several ECUs sharing a bus.
    """

    def _combined(frame: CanFrame) -> Tuple[CanFrame, ...]:
        replies: list[CanFrame] = []
        for responder in responders:
            replies.extend(responder(frame))
        return tuple(replies)

    return _combined
