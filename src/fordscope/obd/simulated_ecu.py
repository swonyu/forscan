"""A simulated OBD-II ECU — an application handler for ``SimulatedIsoTpEcu``.

Seed it with PID data bytes, DTC lists (as decoded strings), and a VIN::

    ecu = SimulatedObdEcu(
        pids={0x0C: bytes([0x0F, 0xA0])},   # RPM 1000
        dtcs=["P0143", "P0196"],
        vin="1FMHK8D89ABA12345",
    )
    isotp_ecu = SimulatedIsoTpEcu(ecu, request_id=0x7DF, response_id=0x7E8)
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .pids import encode_dtc


class SimulatedObdEcu:
    def __init__(
        self,
        *,
        pids: "Optional[Dict[int, bytes]]" = None,
        dtcs: "Optional[List[str]]" = None,
        pending: "Optional[List[str]]" = None,
        permanent: "Optional[List[str]]" = None,
        vin: "Optional[str]" = None,
        calibration_ids: "Optional[List[str]]" = None,
        cvns: "Optional[List[bytes]]" = None,
        ecu_names: "Optional[List[str]]" = None,
        freeze_frame: "Optional[Dict[int, bytes]]" = None,
        freeze_dtc: "Optional[str]" = None,
    ) -> None:
        self.pids: Dict[int, bytes] = {int(k): bytes(v) for k, v in (pids or {}).items()}
        self.dtcs: List[str] = list(dtcs or [])
        self.pending: List[str] = list(pending or [])
        self.permanent: List[str] = list(permanent or [])
        self.vin = vin
        self.calibration_ids: List[str] = list(calibration_ids or [])
        self.cvns: List[bytes] = [bytes(c) for c in (cvns or [])]
        self.ecu_names: List[str] = list(ecu_names or [])
        self.freeze_frame: Dict[int, bytes] = {int(k): bytes(v) for k, v in (freeze_frame or {}).items()}
        self.freeze_dtc = freeze_dtc
        self.cleared = False

    def __call__(self, request: bytes) -> Optional[bytes]:
        if not request:
            return None
        mode = request[0]
        if mode == 0x01:
            return self._mode01(request)
        if mode == 0x02:
            return self._mode02(request)
        if mode == 0x03:
            return self._dtc_block(0x43, self.dtcs)
        if mode == 0x04:
            self.dtcs = []
            self.pending = []
            self.cleared = True
            return bytes([0x44])
        if mode == 0x07:
            return self._dtc_block(0x47, self.pending)
        if mode == 0x0A:
            return self._dtc_block(0x4A, self.permanent)
        if mode == 0x09:
            return self._mode09(request)
        return bytes([0x7F, mode, 0x11])  # serviceNotSupported

    _SUPPORT_QUERY_PIDS = (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0)

    def _mode01(self, request: bytes) -> bytes:
        if len(request) < 2:
            return bytes([0x7F, 0x01, 0x13])
        pid = request[1]
        if pid in self._SUPPORT_QUERY_PIDS:
            return bytes([0x41, pid]) + self._supported_mask(pid)
        if pid not in self.pids:
            return bytes([0x7F, 0x01, 0x31])  # requestOutOfRange
        return bytes([0x41, pid]) + self.pids[pid]

    def _mode02(self, request: bytes) -> bytes:
        # [0x02, pid, frame] -> [0x42, pid, frame, ...data]
        if len(request) < 2:
            return bytes([0x7F, 0x02, 0x13])
        pid = request[1]
        frame = request[2] if len(request) > 2 else 0
        if pid == 0x02:  # the DTC that caused the freeze frame
            dtc_bytes = encode_dtc(self.freeze_dtc) if self.freeze_dtc else bytes([0x00, 0x00])
            return bytes([0x42, 0x02, frame]) + dtc_bytes
        if pid in self.freeze_frame:
            return bytes([0x42, pid, frame]) + self.freeze_frame[pid]
        return bytes([0x7F, 0x02, 0x31])

    def _supported_mask(self, base: int) -> bytes:
        bits = 0
        for offset in range(1, 0x21):
            p = base + offset
            if offset == 0x20:
                # continuation PID: supported if any PID exists in the next range
                supported = any((base + 0x21) <= q <= (base + 0x40) for q in self.pids)
            else:
                supported = p in self.pids
            if supported:
                bits |= 1 << (0x20 - offset)
        return bits.to_bytes(4, "big")

    @staticmethod
    def _dtc_block(sid: int, codes: List[str]) -> bytes:
        body = bytes([len(codes)])
        for code in codes:
            body += encode_dtc(code)
        return bytes([sid]) + body

    def _mode09(self, request: bytes) -> bytes:
        if len(request) < 2:
            return bytes([0x7F, 0x09, 0x13])
        pid = request[1]
        if pid == 0x02 and self.vin is not None:
            return bytes([0x49, 0x02, 0x01]) + self.vin.encode("ascii")
        if pid == 0x04 and self.calibration_ids:  # calibration ID(s), 16-byte items
            return self._info_items(0x04, [s.encode("ascii").ljust(16, b"\x00")[:16] for s in self.calibration_ids])
        if pid == 0x06 and self.cvns:  # calibration verification number(s), 4-byte
            return self._info_items(0x06, [bytes(c).ljust(4, b"\x00")[:4] for c in self.cvns])
        if pid == 0x0A and self.ecu_names:  # ECU name(s), 20-byte items
            return self._info_items(0x0A, [s.encode("ascii").ljust(20, b"\x00")[:20] for s in self.ecu_names])
        return bytes([0x7F, 0x09, 0x31])

    @staticmethod
    def _info_items(info_type: int, items: List[bytes]) -> bytes:
        # Mode 09 positive response: [0x49, InfoType, NODI, <NODI fixed-width items>].
        body = bytes([0x49, info_type, len(items)])
        for item in items:
            body += item
        return body
