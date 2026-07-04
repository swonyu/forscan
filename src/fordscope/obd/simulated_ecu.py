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
    ) -> None:
        self.pids: Dict[int, bytes] = {int(k): bytes(v) for k, v in (pids or {}).items()}
        self.dtcs: List[str] = list(dtcs or [])
        self.pending: List[str] = list(pending or [])
        self.permanent: List[str] = list(permanent or [])
        self.vin = vin
        self.cleared = False

    def __call__(self, request: bytes) -> Optional[bytes]:
        if not request:
            return None
        mode = request[0]
        if mode == 0x01:
            return self._mode01(request)
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

    def _mode01(self, request: bytes) -> bytes:
        if len(request) < 2:
            return bytes([0x7F, 0x01, 0x13])
        pid = request[1]
        if pid not in self.pids:
            return bytes([0x7F, 0x01, 0x31])  # requestOutOfRange
        return bytes([0x41, pid]) + self.pids[pid]

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
        return bytes([0x7F, 0x09, 0x31])
