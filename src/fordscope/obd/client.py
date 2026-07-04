"""OBD-II (SAE J1979) client — generic diagnostics over ISO-TP.

Modes: 01 current data, 03/07/0A stored/pending/permanent DTCs, 04 clear, 09
vehicle info (VIN). Positive response = request mode + 0x40; negative response
= [0x7F, mode, NRC].
"""
from __future__ import annotations

from ..isotp.socket import IsoTpSocket
from .pids import PidResult, decode_pid, decode_dtcs, decode_supported_pids
from .dtc_database import DtcInfo, describe_dtc

MODE_CURRENT_DATA = 0x01
MODE_STORED_DTCS = 0x03
MODE_CLEAR_DTCS = 0x04
MODE_PENDING_DTCS = 0x07
MODE_VEHICLE_INFO = 0x09
MODE_PERMANENT_DTCS = 0x0A
NEGATIVE_RESPONSE_SID = 0x7F
VEHICLE_INFO_VIN = 0x02


class ObdError(Exception):
    """Base class for OBD-II client failures."""


class ObdNegativeResponse(ObdError):
    def __init__(self, mode: int, nrc: int) -> None:
        self.mode = mode
        self.nrc = nrc
        super().__init__(f"OBD mode 0x{mode:02X} negative response, NRC 0x{nrc:02X}")


class ObdClient:
    def __init__(self, socket: IsoTpSocket, *, timeout: float = 1.0) -> None:
        self.socket = socket
        self.timeout = timeout

    def _request(self, payload: bytes) -> bytes:
        self.socket.send(payload)
        resp = self.socket.recv(self.timeout)
        if resp is None:
            raise ObdError(f"no response to mode 0x{payload[0]:02X}")
        if len(resp) == 0:
            raise ObdError("empty OBD response")
        if resp[0] == NEGATIVE_RESPONSE_SID:
            if len(resp) < 3:
                raise ObdError("malformed negative response")
            raise ObdNegativeResponse(resp[1], resp[2])
        expected = (payload[0] + 0x40) & 0xFF
        if resp[0] != expected:
            raise ObdError(
                f"expected 0x{expected:02X}, got 0x{resp[0]:02X}"
            )
        return resp

    def current_data(self, pid: int) -> PidResult:
        """Mode 01: read one live-data PID, decoded to value + unit."""
        resp = self._request(bytes([MODE_CURRENT_DATA, pid & 0xFF]))
        if len(resp) < 2 or resp[1] != (pid & 0xFF):
            raise ObdError("PID echo mismatch in Mode 01 response")
        return decode_pid(pid, resp[2:])

    def supported_pids(self, max_ranges: int = 8) -> list:
        """Mode 01: which PIDs the ECU supports. Queries PID 0x00, then 0x20, …
        while the continuation bit is set. Returns the supported PID numbers."""
        supported: list = []
        base = 0x00
        for _ in range(max_ranges):
            try:
                resp = self._request(bytes([MODE_CURRENT_DATA, base]))
            except ObdError:
                break
            if len(resp) < 2 or resp[1] != base:
                raise ObdError("supported-PIDs echo mismatch")
            pids = decode_supported_pids(base, resp[2:6])
            supported.extend(pids)
            continuation = base + 0x20
            if continuation not in pids:
                break
            base = continuation
        return supported

    def read_dtcs(self, mode: int = MODE_STORED_DTCS) -> list[str]:
        """Mode 03 (stored), 07 (pending) or 0A (permanent) trouble codes."""
        if mode not in (MODE_STORED_DTCS, MODE_PENDING_DTCS, MODE_PERMANENT_DTCS):
            raise ValueError(f"mode 0x{mode:02X} is not a DTC-read mode")
        resp = self._request(bytes([mode]))
        return decode_dtcs(resp[1:])

    def read_dtcs_described(self, mode: int = MODE_STORED_DTCS) -> list[DtcInfo]:
        """Like ``read_dtcs`` but each code carries its description/category."""
        return [describe_dtc(code) for code in self.read_dtcs(mode)]

    def clear_dtcs(self) -> None:
        """Mode 04: clear stored DTCs and turn off the MIL."""
        self._request(bytes([MODE_CLEAR_DTCS]))

    def read_vin(self) -> str:
        """Mode 09 PID 02: vehicle identification number."""
        resp = self._request(bytes([MODE_VEHICLE_INFO, VEHICLE_INFO_VIN]))
        # [0x49, 0x02, NODI, <VIN bytes>]
        if len(resp) < 3 or resp[1] != VEHICLE_INFO_VIN:
            raise ObdError("Mode 09 echo mismatch")
        return resp[3:].decode("ascii", errors="replace")
