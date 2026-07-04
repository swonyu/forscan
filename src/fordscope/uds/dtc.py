"""UDS (ISO 14229) DTC records — 3-byte DTC + 1-byte status.

Unlike OBD-II Mode 03 (2-byte DTCs), UDS ReadDTCInformation reports each fault as
a 3-byte DTC (the first two bytes are the familiar P/C/B/U + 4-digit code, the
third is a failure-type byte) followed by a status byte whose bits describe the
fault's state (confirmed, pending, etc., per ISO 14229-1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ..obd.pids import decode_dtc, encode_dtc

# DTC status byte bits (ISO 14229-1 Table).
STATUS_TEST_FAILED = 0x01
STATUS_TEST_FAILED_THIS_CYCLE = 0x02
STATUS_PENDING = 0x04
STATUS_CONFIRMED = 0x08
STATUS_TEST_NOT_COMPLETED_SINCE_CLEAR = 0x10
STATUS_TEST_FAILED_SINCE_CLEAR = 0x20
STATUS_TEST_NOT_COMPLETED_THIS_CYCLE = 0x40
STATUS_WARNING_INDICATOR = 0x80


@dataclass(frozen=True)
class UdsDtc:
    code: str          # e.g. "P0143"
    failure_type: int  # 3rd DTC byte (failure-type / sub-type)
    status: int        # status byte

    @property
    def display(self) -> str:
        return f"{self.code}-{self.failure_type:02X}"

    @property
    def confirmed(self) -> bool:
        return bool(self.status & STATUS_CONFIRMED)

    @property
    def pending(self) -> bool:
        return bool(self.status & STATUS_PENDING)


def decode_dtc_records(records: bytes) -> List[UdsDtc]:
    """Decode a run of 4-byte DTCAndStatus records (3-byte DTC + status)."""
    usable = len(records) - (len(records) % 4)
    out: List[UdsDtc] = []
    for i in range(0, usable, 4):
        a, b, failure_type, status = records[i], records[i + 1], records[i + 2], records[i + 3]
        out.append(UdsDtc(decode_dtc(a, b), failure_type, status))
    return out


def encode_dtc_record(code: str, failure_type: int = 0x00, status: int = STATUS_CONFIRMED) -> bytes:
    """Build a 4-byte DTCAndStatus record from a code + failure type + status."""
    return encode_dtc(code) + bytes([failure_type & 0xFF, status & 0xFF])
