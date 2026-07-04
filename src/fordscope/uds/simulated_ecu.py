"""A simulated UDS ECU — an application handler for ``SimulatedIsoTpEcu``.

Maps a reassembled UDS request payload to a UDS response payload, modelling a
DID store, the current diagnostic session, and the last reset. Plug it in::

    uds = SimulatedUdsEcu({0xF190: b"1FMHK8D89ABA12345"})
    isotp_ecu = SimulatedIsoTpEcu(uds, request_id=0x7E0, response_id=0x7E8)
    bus = SimulatorTransport(isotp_ecu)

Returning None (e.g. a suppressed TesterPresent) makes the ECU send nothing.
"""
from __future__ import annotations

from typing import Dict, Optional

from .services import (
    NEGATIVE_RESPONSE_SID,
    POSITIVE_RESPONSE_OFFSET,
    SUPPRESS_POSITIVE_RESPONSE_BIT,
    DIAGNOSTIC_SESSION_CONTROL,
    ECU_RESET,
    READ_DATA_BY_IDENTIFIER,
    WRITE_DATA_BY_IDENTIFIER,
    INPUT_OUTPUT_CONTROL_BY_IDENTIFIER,
    ROUTINE_CONTROL,
    TESTER_PRESENT,
    SESSION_DEFAULT,
    SESSION_PROGRAMMING,
    SESSION_EXTENDED,
    IO_RETURN_CONTROL_TO_ECU,
    ROUTINE_START,
    ROUTINE_STOP,
    ROUTINE_REQUEST_RESULTS,
    NRC_SERVICE_NOT_SUPPORTED,
    NRC_SUBFUNCTION_NOT_SUPPORTED,
    NRC_INCORRECT_LENGTH_OR_FORMAT,
    NRC_REQUEST_OUT_OF_RANGE,
    NRC_REQUEST_SEQUENCE_ERROR,
)


class SimulatedUdsEcu:
    def __init__(
        self,
        dids: "Optional[Dict[int, bytes]]" = None,
        *,
        io_dids: "Optional[set]" = None,
        routines: "Optional[Dict[int, bytes]]" = None,
    ) -> None:
        self.dids: Dict[int, bytes] = {int(k): bytes(v) for k, v in (dids or {}).items()}
        self.session: int = SESSION_DEFAULT
        self.last_reset: Optional[int] = None
        # bidirectional-control state
        self.io_dids = set(io_dids or ())
        self.io_state: Dict[int, bytes] = {}
        self.routines: Dict[int, bytes] = {int(k): bytes(v) for k, v in (routines or {}).items()}
        self.routines_started: set = set()

    def __call__(self, request: bytes) -> Optional[bytes]:
        if not request:
            return None
        sid = request[0]
        handler = {
            DIAGNOSTIC_SESSION_CONTROL: self._session,
            ECU_RESET: self._ecu_reset,
            READ_DATA_BY_IDENTIFIER: self._read_did,
            WRITE_DATA_BY_IDENTIFIER: self._write_did,
            INPUT_OUTPUT_CONTROL_BY_IDENTIFIER: self._io_control,
            ROUTINE_CONTROL: self._routine_control,
            TESTER_PRESENT: self._tester_present,
        }.get(sid)
        if handler is None:
            return self._nrc(sid, NRC_SERVICE_NOT_SUPPORTED)
        return handler(request)

    @staticmethod
    def _nrc(sid: int, code: int) -> bytes:
        return bytes([NEGATIVE_RESPONSE_SID, sid, code])

    @staticmethod
    def _positive(sid: int) -> int:
        return (sid + POSITIVE_RESPONSE_OFFSET) & 0xFF

    def _session(self, request: bytes) -> Optional[bytes]:
        if len(request) != 2:
            return self._nrc(DIAGNOSTIC_SESSION_CONTROL, NRC_INCORRECT_LENGTH_OR_FORMAT)
        sub = request[1] & 0x7F
        if sub not in (SESSION_DEFAULT, SESSION_PROGRAMMING, SESSION_EXTENDED):
            return self._nrc(DIAGNOSTIC_SESSION_CONTROL, NRC_SUBFUNCTION_NOT_SUPPORTED)
        self.session = sub
        # positive response + P2/P2* server timing (50 ms / 5000 ms).
        return bytes([self._positive(DIAGNOSTIC_SESSION_CONTROL), sub, 0x00, 0x32, 0x01, 0xF4])

    def _ecu_reset(self, request: bytes) -> Optional[bytes]:
        if len(request) != 2:
            return self._nrc(ECU_RESET, NRC_INCORRECT_LENGTH_OR_FORMAT)
        self.last_reset = request[1]
        return bytes([self._positive(ECU_RESET), request[1]])

    def _read_did(self, request: bytes) -> Optional[bytes]:
        if len(request) != 3:
            return self._nrc(READ_DATA_BY_IDENTIFIER, NRC_INCORRECT_LENGTH_OR_FORMAT)
        did = (request[1] << 8) | request[2]
        if did not in self.dids:
            return self._nrc(READ_DATA_BY_IDENTIFIER, NRC_REQUEST_OUT_OF_RANGE)
        return bytes([self._positive(READ_DATA_BY_IDENTIFIER), request[1], request[2]]) + self.dids[did]

    def _write_did(self, request: bytes) -> Optional[bytes]:
        if len(request) < 4:
            return self._nrc(WRITE_DATA_BY_IDENTIFIER, NRC_INCORRECT_LENGTH_OR_FORMAT)
        did = (request[1] << 8) | request[2]
        self.dids[did] = bytes(request[3:])
        return bytes([self._positive(WRITE_DATA_BY_IDENTIFIER), request[1], request[2]])

    def _tester_present(self, request: bytes) -> Optional[bytes]:
        if len(request) != 2:
            return self._nrc(TESTER_PRESENT, NRC_INCORRECT_LENGTH_OR_FORMAT)
        if request[1] & SUPPRESS_POSITIVE_RESPONSE_BIT:
            return None  # suppressed — ECU stays silent
        return bytes([self._positive(TESTER_PRESENT), request[1] & 0x7F])

    def _io_control(self, request: bytes) -> Optional[bytes]:
        # [0x2F, hi, lo, option, *state]
        if len(request) < 4:
            return self._nrc(INPUT_OUTPUT_CONTROL_BY_IDENTIFIER, NRC_INCORRECT_LENGTH_OR_FORMAT)
        did = (request[1] << 8) | request[2]
        option = request[3]
        state = bytes(request[4:])
        if did not in self.io_dids:
            return self._nrc(INPUT_OUTPUT_CONTROL_BY_IDENTIFIER, NRC_REQUEST_OUT_OF_RANGE)
        if option == IO_RETURN_CONTROL_TO_ECU:
            self.io_state.pop(did, None)
        else:
            self.io_state[did] = state
        # echo did + option + the commanded state as the control status record
        return bytes([self._positive(INPUT_OUTPUT_CONTROL_BY_IDENTIFIER), request[1], request[2], option]) + state

    def _routine_control(self, request: bytes) -> Optional[bytes]:
        # [0x31, type, rid_hi, rid_lo, *option]
        if len(request) < 4:
            return self._nrc(ROUTINE_CONTROL, NRC_INCORRECT_LENGTH_OR_FORMAT)
        rtype = request[1]
        rid = (request[2] << 8) | request[3]
        if rid not in self.routines:
            return self._nrc(ROUTINE_CONTROL, NRC_REQUEST_OUT_OF_RANGE)
        head = bytes([self._positive(ROUTINE_CONTROL), rtype, request[2], request[3]])
        if rtype == ROUTINE_START:
            self.routines_started.add(rid)
            return head
        if rtype == ROUTINE_STOP:
            self.routines_started.discard(rid)
            return head
        if rtype == ROUTINE_REQUEST_RESULTS:
            if rid not in self.routines_started:
                return self._nrc(ROUTINE_CONTROL, NRC_REQUEST_SEQUENCE_ERROR)
            return head + self.routines[rid]
        return self._nrc(ROUTINE_CONTROL, NRC_SUBFUNCTION_NOT_SUPPORTED)
