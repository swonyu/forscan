"""OBD-II (SAE J1979) decoders — Mode 01 PIDs and DTC codes.

Pure functions, formulas hand-transcribed from SAE J1979 (NOT from any code
under test). Each Mode 01 PID has a fixed data length and a scaling formula;
each DTC is two bytes decoded to the ``P/C/B/U`` + 4-digit form.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


# --- Mode 01 PID decoders (data = the bytes after [0x41, PID]) -----------
def _u16(d: bytes) -> int:
    return (d[0] << 8) | d[1]


def _rpm(d: bytes) -> float:
    return _u16(d) / 4.0


def _temp_minus40(d: bytes) -> int:
    return d[0] - 40


def _percent_255(d: bytes) -> float:
    return d[0] * 100.0 / 255.0


def _fuel_trim(d: bytes) -> float:
    return (d[0] - 128) * 100.0 / 128.0


def _maf(d: bytes) -> float:
    return _u16(d) / 100.0


def _timing_advance(d: bytes) -> float:
    return d[0] / 2.0 - 64.0


def _module_voltage(d: bytes) -> float:
    return _u16(d) / 1000.0


@dataclass(frozen=True)
class PidDef:
    name: str
    num_bytes: int
    decode: Callable[[bytes], float]
    unit: str


@dataclass(frozen=True)
class PidResult:
    pid: int
    name: str
    value: float
    unit: str
    raw: bytes


PID_TABLE = {
    0x04: PidDef("Calculated engine load", 1, _percent_255, "%"),
    0x05: PidDef("Engine coolant temperature", 1, _temp_minus40, "degC"),
    0x06: PidDef("Short term fuel trim, Bank 1", 1, _fuel_trim, "%"),
    0x07: PidDef("Long term fuel trim, Bank 1", 1, _fuel_trim, "%"),
    0x0A: PidDef("Fuel pressure", 1, lambda d: float(d[0] * 3), "kPa"),
    0x0B: PidDef("Intake manifold absolute pressure", 1, lambda d: float(d[0]), "kPa"),
    0x0C: PidDef("Engine RPM", 2, _rpm, "rpm"),
    0x0D: PidDef("Vehicle speed", 1, lambda d: float(d[0]), "km/h"),
    0x0E: PidDef("Timing advance", 1, _timing_advance, "deg"),
    0x0F: PidDef("Intake air temperature", 1, _temp_minus40, "degC"),
    0x10: PidDef("MAF air flow rate", 2, _maf, "g/s"),
    0x11: PidDef("Throttle position", 1, _percent_255, "%"),
    0x2F: PidDef("Fuel tank level input", 1, _percent_255, "%"),
    0x33: PidDef("Absolute barometric pressure", 1, lambda d: float(d[0]), "kPa"),
    0x42: PidDef("Control module voltage", 2, _module_voltage, "V"),
    0x46: PidDef("Ambient air temperature", 1, _temp_minus40, "degC"),
}


def decode_pid(pid: int, data: bytes) -> PidResult:
    """Decode Mode 01 PID data bytes into a value + unit."""
    if pid not in PID_TABLE:
        raise KeyError(f"unknown/unsupported PID 0x{pid:02X}")
    d = PID_TABLE[pid]
    if len(data) < d.num_bytes:
        raise ValueError(
            f"PID 0x{pid:02X} needs {d.num_bytes} data byte(s), got {len(data)}"
        )
    used = bytes(data[: d.num_bytes])
    return PidResult(pid, d.name, d.decode(used), d.unit, used)


# --- DTC codec -----------------------------------------------------------
_DTC_LETTERS = "PCBU"  # first two bits of byte A


def decode_dtc(a: int, b: int) -> str:
    """Two DTC bytes -> e.g. 'P0143'.

    Bits 7-6 of A pick the letter (P/C/B/U); bits 5-4 are the first digit (0-3);
    the low nibble of A and both nibbles of B are the remaining hex digits.
    """
    letter = _DTC_LETTERS[(a >> 6) & 0x03]
    d1 = (a >> 4) & 0x03
    d2 = a & 0x0F
    d3 = (b >> 4) & 0x0F
    d4 = b & 0x0F
    return f"{letter}{d1}{d2:X}{d3:X}{d4:X}"


def encode_dtc(code: str) -> bytes:
    """Inverse of ``decode_dtc``: 'P0143' -> b'\\x01\\x43'."""
    if len(code) != 5 or code[0] not in _DTC_LETTERS:
        raise ValueError(f"malformed DTC code: {code!r}")
    idx = _DTC_LETTERS.index(code[0])
    d1 = int(code[1], 16)
    if d1 > 3:
        raise ValueError(f"DTC first digit must be 0-3, got {code[1]}")
    d2 = int(code[2], 16)
    d3 = int(code[3], 16)
    d4 = int(code[4], 16)
    a = (idx << 6) | (d1 << 4) | d2
    b = (d3 << 4) | d4
    return bytes([a, b])


def decode_supported_pids(base: int, data: bytes) -> list[int]:
    """Decode a Mode 01 supported-PIDs bitmask (PID 0x00/0x20/... response).

    ``data`` is the 4-byte mask; the MSB (bit 31 of byte A) is PID ``base+1`` and
    the LSB (bit 0 of byte D) is PID ``base+0x20`` (which, when set, means the next
    range is available). Returns the supported PID numbers.
    """
    if len(data) < 4:
        raise ValueError(f"supported-PIDs mask needs 4 bytes, got {len(data)}")
    bits = int.from_bytes(data[:4], "big")
    return [base + offset for offset in range(1, 0x21) if bits & (1 << (0x20 - offset))]


def decode_dtcs(payload: bytes) -> list[str]:
    """Decode a Mode 03/07/0A body: [count, (A,B) x count]. Skips 0x0000 pads."""
    if not payload:
        return []
    count = payload[0]
    pairs = payload[1:]
    out: list[str] = []
    for i in range(0, min(len(pairs) - (len(pairs) % 2), count * 2), 2):
        a, b = pairs[i], pairs[i + 1]
        if a == 0 and b == 0:
            continue
        out.append(decode_dtc(a, b))
    return out
