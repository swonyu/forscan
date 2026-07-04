"""SAE J1979 Mode 06 — on-board monitoring test results.

Research-grounded (docs/RESEARCH_2026-07-04, 3-vote verified): on 2008+ CAN vehicles
(so the 2016 Fusion) the MID (Monitor ID) numbering is SAE-standardized cross-
manufacturer, so we can name the monitor CATEGORY from the MID. But the TID (Test ID)
meaning and the limit *semantics* (physical units, what "close enough" means) are
OEM-calibrated and NOT standardized. So this decoder shows the MID category + the raw
test value + the ECU's OWN returned min/max limits + a pass/fail computed from those,
and flags the TID as manufacturer-specific. It never fabricates a TID name or a verdict
beyond the limits the ECU itself sent.
"""
from __future__ import annotations

from dataclasses import dataclass

# Standardized MID -> monitor category (SAE J1979 / ISO 15031-5, CAN era). The numbering
# is the same across manufacturers; the bank/sensor/cylinder suffixes follow the offset.
MID_CATEGORIES = {
    0x01: "O2 Sensor Monitor B1S1", 0x02: "O2 Sensor Monitor B1S2",
    0x03: "O2 Sensor Monitor B1S3", 0x04: "O2 Sensor Monitor B1S4",
    0x05: "O2 Sensor Monitor B2S1", 0x06: "O2 Sensor Monitor B2S2",
    0x07: "O2 Sensor Monitor B2S3", 0x08: "O2 Sensor Monitor B2S4",
    0x21: "Catalyst Monitor Bank 1", 0x22: "Catalyst Monitor Bank 2",
    0x31: "EGR Monitor Bank 1", 0x32: "EGR Monitor Bank 2",
    0x33: "EGR Stepper Motor Monitor",
    0x3A: "EVAP Monitor", 0x3B: "EVAP Monitor", 0x3C: "EVAP Monitor (Purge Flow)",
    0x71: "Secondary Air Injection Monitor",
    0xA1: "Misfire Monitor (General)",
}
# Per-cylinder misfire monitors: 0xA2..0xB0 -> Cylinder 1..15.
for _i in range(1, 16):
    MID_CATEGORIES.setdefault(0xA1 + _i, f"Misfire Monitor Cylinder {_i}")
del _i


def describe_mid(mid: int) -> str:
    return MID_CATEGORIES.get(mid, f"manufacturer-specific monitor (MID 0x{mid:02X})")


@dataclass(frozen=True)
class MonitorTest:
    mid: int
    tid: int      # Test ID — manufacturer-specific; not named
    uasid: int    # unit-and-scaling ID (physical unit of value/limits)
    value: int    # raw test value
    min_limit: int  # ECU-returned min
    max_limit: int  # ECU-returned max

    @property
    def category(self) -> str:
        return describe_mid(self.mid)

    @property
    def standardized_mid(self) -> bool:
        return self.mid in MID_CATEGORIES

    @property
    def passed(self) -> bool:
        # Pass/fail is computable from the ECU's OWN returned limits in raw units,
        # without knowing the OEM unit/scaling — value within [min, max].
        return self.min_limit <= self.value <= self.max_limit


_RECORD_LEN = 9  # MID, TID, UASID, value(2), min(2), max(2)


def decode_monitor_tests(data: bytes) -> "list[MonitorTest]":
    """Decode the payload AFTER the 0x46 SID into test records. Only whole 9-byte
    records are decoded; a truncated trailing chunk is dropped, never fabricated."""
    tests = []
    for i in range(0, len(data) - (len(data) % _RECORD_LEN), _RECORD_LEN):
        r = data[i:i + _RECORD_LEN]
        tests.append(MonitorTest(
            mid=r[0], tid=r[1], uasid=r[2],
            value=(r[3] << 8) | r[4],
            min_limit=(r[5] << 8) | r[6],
            max_limit=(r[7] << 8) | r[8],
        ))
    return tests
