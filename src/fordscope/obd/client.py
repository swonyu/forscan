"""OBD-II (SAE J1979) client — generic diagnostics over ISO-TP.

Modes: 01 current data, 03/07/0A stored/pending/permanent DTCs, 04 clear, 09
vehicle info (VIN). Positive response = request mode + 0x40; negative response
= [0x7F, mode, NRC].
"""
from __future__ import annotations

from ..isotp.socket import IsoTpSocket
from .pids import (
    PidResult,
    decode_pid,
    decode_dtc,
    decode_dtcs,
    decode_supported_pids,
    decode_monitor_status,
)
from .dtc_database import DtcInfo, describe_dtc

MODE_CURRENT_DATA = 0x01
MODE_FREEZE_FRAME = 0x02
MODE_STORED_DTCS = 0x03
MODE_CLEAR_DTCS = 0x04
MODE_PENDING_DTCS = 0x07
MODE_VEHICLE_INFO = 0x09
MODE_PERMANENT_DTCS = 0x0A
NEGATIVE_RESPONSE_SID = 0x7F
NRC_RESPONSE_PENDING = 0x78  # requestCorrectlyReceived-ResponsePending (keep waiting)
VEHICLE_INFO_VIN = 0x02
VEHICLE_INFO_CALID = 0x04       # calibration ID(s), ASCII, 16-byte items
VEHICLE_INFO_CVN = 0x06         # calibration verification number(s), 4-byte
VEHICLE_INFO_ECU_NAME = 0x0A    # ECU name/acronym(s), ASCII, 20-byte items


class ObdError(Exception):
    """Base class for OBD-II client failures."""


class ObdNegativeResponse(ObdError):
    def __init__(self, mode: int, nrc: int) -> None:
        self.mode = mode
        self.nrc = nrc
        super().__init__(f"OBD mode 0x{mode:02X} negative response, NRC 0x{nrc:02X}")


class ObdClient:
    def __init__(
        self,
        socket: IsoTpSocket,
        *,
        timeout: float = 1.0,
        response_pending_timeout: float = 5.0,
        max_response_pending: int = 5,
    ) -> None:
        self.socket = socket
        self.timeout = timeout
        # A slow ECU (common on Mode 09 VIN/CALID, or DTC reads on slow modules) may
        # reply NRC 0x78 = "still working, keep waiting"; grant a longer window then.
        self.response_pending_timeout = response_pending_timeout
        self.max_response_pending = max_response_pending

    def _request(self, payload: bytes) -> bytes:
        self.socket.send(payload)
        pending = 0
        timeout = self.timeout
        while True:
            resp = self.socket.recv(timeout)
            if resp is None:
                raise ObdError(f"no response to mode 0x{payload[0]:02X}")
            if len(resp) == 0:
                raise ObdError("empty OBD response")
            if resp[0] == NEGATIVE_RESPONSE_SID:
                if len(resp) < 3:
                    raise ObdError("malformed negative response")
                if resp[1] != payload[0]:
                    # The negative response must echo the request mode; a mismatch is a
                    # crossed-wire reply — reject it, don't misattribute it to this request.
                    raise ObdError(
                        f"negative response mode 0x{resp[1]:02X} does not echo "
                        f"request mode 0x{payload[0]:02X}"
                    )
                if resp[2] == NRC_RESPONSE_PENDING:
                    # 0x78 is NOT terminal — the ECU is still working. Keep polling
                    # (with the longer window), exactly as the UDS client does.
                    pending += 1
                    if pending > self.max_response_pending:
                        raise ObdError(
                            f"mode 0x{payload[0]:02X}: too many responsePending (0x78)"
                        )
                    timeout = self.response_pending_timeout
                    continue
                raise ObdNegativeResponse(resp[1], resp[2])
            expected = (payload[0] + 0x40) & 0xFF
            if resp[0] != expected:
                raise ObdError(f"expected 0x{expected:02X}, got 0x{resp[0]:02X}")
            return resp

    def current_data(self, pid: int) -> PidResult:
        """Mode 01: read one live-data PID, decoded to value + unit."""
        resp = self._request(bytes([MODE_CURRENT_DATA, pid & 0xFF]))
        if len(resp) < 2 or resp[1] != (pid & 0xFF):
            raise ObdError("PID echo mismatch in Mode 01 response")
        return decode_pid(pid, resp[2:])

    def monitor_status(self):
        """Mode 01 PID 0x01: I/M readiness — MIL, DTC count, monitor completeness."""
        resp = self._request(bytes([MODE_CURRENT_DATA, 0x01]))
        if len(resp) < 6 or resp[1] != 0x01:
            raise ObdError("monitor-status echo mismatch")
        return decode_monitor_status(resp[2:6])

    def freeze_frame(self, pid: int, frame: int = 0) -> PidResult:
        """Mode 02: read one PID's frozen value from a freeze frame."""
        resp = self._request(bytes([MODE_FREEZE_FRAME, pid & 0xFF, frame & 0xFF]))
        # [0x42, pid, frame, ...data] — validate BOTH the PID and the frame echo, so
        # a crossed-wire response for a different record isn't accepted as this one.
        if len(resp) < 3 or resp[1] != (pid & 0xFF) or resp[2] != (frame & 0xFF):
            raise ObdError("freeze-frame echo mismatch")
        return decode_pid(pid, resp[3:])

    def freeze_frame_dtc(self, frame: int = 0):
        """Mode 02 PID 0x02: the DTC that triggered the freeze frame, or None."""
        resp = self._request(bytes([MODE_FREEZE_FRAME, 0x02, frame & 0xFF]))
        # [0x42, 0x02, frame, A, B]
        if len(resp) < 5:
            return None
        a, b = resp[3], resp[4]
        if a == 0 and b == 0:
            return None
        return decode_dtc(a, b)

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
        # Decode STRICT (not errors="replace") so a corrupted non-ASCII byte raises
        # instead of baking a U+FFFD into a same-length string that passes the guard.
        try:
            vin = resp[3:].decode("ascii").rstrip("\x00").strip()
        except UnicodeDecodeError:
            raise ObdError("VIN response contains non-ASCII bytes")
        # A VIN is exactly 17 alphanumeric chars; a truncated OR content-corrupted
        # read must NOT be surfaced as a complete VIN — signal the error instead.
        if len(vin) != 17 or not vin.isalnum():
            raise ObdError(f"VIN response malformed: {vin!r} (expected 17 alphanumeric chars)")
        return vin

    def _read_vehicle_info(self, info_type: int) -> bytes:
        """Mode 09 <info_type>: return the data payload after the NODI byte."""
        resp = self._request(bytes([MODE_VEHICLE_INFO, info_type]))
        # [0x49, info_type, NODI, <NODI fixed-width items>]
        if len(resp) < 3 or resp[1] != info_type:
            raise ObdError(f"Mode 09 InfoType 0x{info_type:02X} echo mismatch")
        return resp[3:]

    @staticmethod
    def _text_items(data: bytes, item_len: int) -> "list[str]":
        """Split a Mode 09 payload into fixed-width ASCII items, trimming the
        null padding each carries; drop empty items."""
        items = []
        # Only whole fixed-width items — a truncated trailing chunk is dropped, not
        # decoded into a fabricated extra item (consistent with read_cvns' guard).
        for i in range(0, len(data) - (len(data) % item_len), item_len):
            # STRICT decode: an item with a corrupt non-ASCII byte is DROPPED, not
            # surfaced with a U+FFFD baked into a fabricated calibration/ECU id.
            try:
                text = data[i:i + item_len].split(b"\x00", 1)[0].decode("ascii").strip()
            except UnicodeDecodeError:
                continue
            if text:
                items.append(text)
        return items

    def read_calibration_ids(self) -> "list[str]":
        """Mode 09 InfoType 0x04: the calibration ID(s) — the software level of each
        calibration, exactly what FORScan/dealers read to confirm module firmware.
        [NEEDS ON-CAR CHECK] — the decode is spec-verified; the read needs a car."""
        return self._text_items(self._read_vehicle_info(VEHICLE_INFO_CALID), 16)

    def read_ecu_names(self) -> "list[str]":
        """Mode 09 InfoType 0x0A: the ECU name/acronym(s), ASCII. [NEEDS ON-CAR CHECK]"""
        return self._text_items(self._read_vehicle_info(VEHICLE_INFO_ECU_NAME), 20)

    def read_cvns(self) -> "list[str]":
        """Mode 09 InfoType 0x06: the calibration verification number(s) — a 4-byte
        checksum per calibration, surfaced as hex. [NEEDS ON-CAR CHECK]"""
        data = self._read_vehicle_info(VEHICLE_INFO_CVN)
        return [data[i:i + 4].hex().upper() for i in range(0, len(data) - (len(data) % 4), 4)]
