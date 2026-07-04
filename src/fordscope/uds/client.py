"""UDS (ISO 14229) client — request/response over an ISO-TP socket.

Handles the three response shapes: positive (``SID + 0x40``), negative
(``0x7F SID NRC`` → ``NegativeResponseError``), and the special
responsePending (NRC 0x78), where the ECU acknowledges but keeps working and
the client must keep waiting for the real reply.
"""
from __future__ import annotations

from typing import Optional

from ..isotp.socket import IsoTpSocket
from .services import (
    POSITIVE_RESPONSE_OFFSET,
    NEGATIVE_RESPONSE_SID,
    SUPPRESS_POSITIVE_RESPONSE_BIT,
    NRC_RESPONSE_PENDING,
    DIAGNOSTIC_SESSION_CONTROL,
    ECU_RESET,
    READ_DATA_BY_IDENTIFIER,
    WRITE_DATA_BY_IDENTIFIER,
    INPUT_OUTPUT_CONTROL_BY_IDENTIFIER,
    ROUTINE_CONTROL,
    READ_DTC_INFORMATION,
    REPORT_DTC_BY_STATUS_MASK,
    TESTER_PRESENT,
    ROUTINE_START,
    ROUTINE_STOP,
    ROUTINE_REQUEST_RESULTS,
    nrc_name,
)
from .dtc import UdsDtc, decode_dtc_records


class UdsError(Exception):
    """Base class for UDS-layer failures."""


class NegativeResponseError(UdsError):
    """The ECU returned a negative response (0x7F SID NRC)."""

    def __init__(self, request_sid: int, nrc: int) -> None:
        self.request_sid = request_sid
        self.nrc = nrc
        self.nrc_name = nrc_name(nrc)
        super().__init__(
            f"UDS service 0x{request_sid:02X} negative response: "
            f"0x{nrc:02X} {self.nrc_name}"
        )


class UnexpectedResponseError(UdsError):
    """A response that is neither a well-formed positive nor negative reply."""


class UdsClient:
    def __init__(
        self,
        socket: IsoTpSocket,
        *,
        p2_timeout: float = 1.0,
        max_response_pending: int = 5,
    ) -> None:
        self.socket = socket
        self.p2_timeout = p2_timeout
        self.max_response_pending = max_response_pending

    def request(self, payload: bytes, *, expect_response: bool = True) -> Optional[bytes]:
        """Send a raw UDS request; return the full positive-response payload.

        Raises ``NegativeResponseError`` on a final negative response, transparently
        looping through responsePending (0x78). Returns None if expect_response is False.
        """
        if not payload:
            raise ValueError("empty UDS request")
        sid = payload[0]
        self.socket.send(payload)
        if not expect_response:
            return None

        pending = 0
        while True:
            resp = self.socket.recv(self.p2_timeout)
            if resp is None:
                raise UdsError(f"no response to service 0x{sid:02X}")
            if len(resp) == 0:
                raise UnexpectedResponseError("empty UDS response payload")

            if resp[0] == NEGATIVE_RESPONSE_SID:
                if len(resp) < 3:
                    raise UnexpectedResponseError("malformed negative response")
                echoed_sid, nrc = resp[1], resp[2]
                if nrc == NRC_RESPONSE_PENDING:
                    pending += 1
                    if pending > self.max_response_pending:
                        raise UdsError(
                            f"service 0x{sid:02X}: too many responsePending (0x78)"
                        )
                    continue
                raise NegativeResponseError(echoed_sid, nrc)

            if resp[0] != (sid + POSITIVE_RESPONSE_OFFSET) & 0xFF:
                raise UnexpectedResponseError(
                    f"expected positive 0x{(sid + POSITIVE_RESPONSE_OFFSET) & 0xFF:02X}, "
                    f"got 0x{resp[0]:02X}"
                )
            return resp

    # --- convenience wrappers -------------------------------------------
    def read_data_by_identifier(self, did: int) -> bytes:
        if not 0 <= did <= 0xFFFF:
            raise ValueError(f"DID must be a 16-bit value, got {did}")
        hi, lo = (did >> 8) & 0xFF, did & 0xFF
        resp = self.request(bytes([READ_DATA_BY_IDENTIFIER, hi, lo]))
        assert resp is not None
        if len(resp) < 3 or resp[1] != hi or resp[2] != lo:
            raise UnexpectedResponseError("DID echo mismatch in ReadDataByIdentifier response")
        return resp[3:]

    def write_data_by_identifier(self, did: int, data: bytes) -> None:
        if not 0 <= did <= 0xFFFF:
            raise ValueError(f"DID must be a 16-bit value, got {did}")
        hi, lo = (did >> 8) & 0xFF, did & 0xFF
        resp = self.request(bytes([WRITE_DATA_BY_IDENTIFIER, hi, lo]) + bytes(data))
        assert resp is not None
        if len(resp) < 3 or resp[1] != hi or resp[2] != lo:
            raise UnexpectedResponseError("DID echo mismatch in WriteDataByIdentifier response")

    def diagnostic_session_control(self, session: int) -> bytes:
        resp = self.request(bytes([DIAGNOSTIC_SESSION_CONTROL, session & 0xFF]))
        assert resp is not None
        return resp

    def ecu_reset(self, reset_type: int) -> bytes:
        resp = self.request(bytes([ECU_RESET, reset_type & 0xFF]))
        assert resp is not None
        return resp

    def tester_present(self, suppress_response: bool = True) -> None:
        sub = SUPPRESS_POSITIVE_RESPONSE_BIT if suppress_response else 0x00
        self.request(bytes([TESTER_PRESENT, sub]), expect_response=not suppress_response)

    # --- bidirectional controls -----------------------------------------
    # SAFETY: these command real actuators (relays, valves, motors, self-tests)
    # on a real vehicle. Simulator-tested only here; on-car use demands safe
    # conditions (correct session, engine state) and is NEEDS ON-CAR CHECK.
    def io_control(self, did: int, control_option: int, control_state: bytes = b"") -> bytes:
        """InputOutputControlByIdentifier (0x2F). Returns the control-status bytes."""
        if not 0 <= did <= 0xFFFF:
            raise ValueError(f"DID must be a 16-bit value, got {did}")
        hi, lo = (did >> 8) & 0xFF, did & 0xFF
        resp = self.request(
            bytes([INPUT_OUTPUT_CONTROL_BY_IDENTIFIER, hi, lo, control_option & 0xFF])
            + bytes(control_state)
        )
        assert resp is not None
        if len(resp) < 4 or resp[1] != hi or resp[2] != lo:
            raise UnexpectedResponseError("IOControl echo mismatch")
        return resp[4:]

    def routine_control(self, routine_type: int, routine_id: int, data: bytes = b"") -> bytes:
        """RoutineControl (0x31). Returns the routine status/results record."""
        if not 0 <= routine_id <= 0xFFFF:
            raise ValueError(f"routine id must be a 16-bit value, got {routine_id}")
        hi, lo = (routine_id >> 8) & 0xFF, routine_id & 0xFF
        resp = self.request(
            bytes([ROUTINE_CONTROL, routine_type & 0xFF, hi, lo]) + bytes(data)
        )
        assert resp is not None
        if len(resp) < 4 or resp[1] != (routine_type & 0xFF) or resp[2] != hi or resp[3] != lo:
            raise UnexpectedResponseError("RoutineControl echo mismatch")
        return resp[4:]

    def start_routine(self, routine_id: int, data: bytes = b"") -> bytes:
        return self.routine_control(ROUTINE_START, routine_id, data)

    def stop_routine(self, routine_id: int, data: bytes = b"") -> bytes:
        return self.routine_control(ROUTINE_STOP, routine_id, data)

    def request_routine_results(self, routine_id: int) -> bytes:
        return self.routine_control(ROUTINE_REQUEST_RESULTS, routine_id)

    def read_dtc_information(self, status_mask: int = 0xFF) -> "list[UdsDtc]":
        """ReadDTCInformation (0x19 / reportDTCByStatusMask). Returns decoded DTCs."""
        resp = self.request(
            bytes([READ_DTC_INFORMATION, REPORT_DTC_BY_STATUS_MASK, status_mask & 0xFF])
        )
        assert resp is not None
        # [0x59, 0x02, DTCStatusAvailabilityMask, <4-byte records>...]
        if len(resp) < 3 or resp[1] != REPORT_DTC_BY_STATUS_MASK:
            raise UnexpectedResponseError("ReadDTCInformation echo mismatch")
        return decode_dtc_records(resp[3:])
