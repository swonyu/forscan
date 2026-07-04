"""DTC-definition database: trouble code -> human description.

Two-tier, by design of honesty:
1. A curated table of common, well-established generic (SAE J2012) codes.
2. A structural fallback that decodes the code's own system + subsystem and
   explicitly marks that no specific definition is on file — rather than
   inventing a meaning for a code we don't actually have.

Manufacturer-specific codes (2nd char 1 or 3) are flagged as such; their exact
meaning is OEM-defined and not asserted here unless curated.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

_SYSTEMS = {"P": "Powertrain", "C": "Chassis", "B": "Body", "U": "Network"}

# Subsystem from the 3rd character of a P-code (e.g. P0[1]43 -> "1").
_P_SUBSYSTEMS = {
    "0": "Fuel and air metering / emissions",
    "1": "Fuel and air metering",
    "2": "Fuel and air metering (injector circuit)",
    "3": "Ignition system or misfire",
    "4": "Auxiliary emission controls",
    "5": "Vehicle speed and idle control",
    "6": "Computer output circuits",
    "7": "Transmission",
    "8": "Transmission",
    "9": "Transmission",
}

# Curated generic definitions (SAE J2012). Only codes with well-established
# standard meanings are included; extend deliberately, never invent.
DTC_DEFINITIONS = {
    "P0100": "Mass or Volume Air Flow Circuit Malfunction",
    "P0101": "Mass or Volume Air Flow Circuit Range/Performance",
    "P0102": "Mass or Volume Air Flow Circuit Low Input",
    "P0113": "Intake Air Temperature Circuit High Input",
    "P0117": "Engine Coolant Temperature Circuit Low Input",
    "P0118": "Engine Coolant Temperature Circuit High Input",
    "P0120": "Throttle/Pedal Position Sensor A Circuit Malfunction",
    "P0128": "Coolant Thermostat (Temperature Below Thermostat Regulating Temperature)",
    "P0131": "O2 Sensor Circuit Low Voltage (Bank 1, Sensor 1)",
    "P0133": "O2 Sensor Circuit Slow Response (Bank 1, Sensor 1)",
    "P0135": "O2 Sensor Heater Circuit Malfunction (Bank 1, Sensor 1)",
    "P0143": "O2 Sensor Circuit Low Voltage (Bank 1, Sensor 3)",
    "P0171": "System Too Lean (Bank 1)",
    "P0172": "System Too Rich (Bank 1)",
    "P0174": "System Too Lean (Bank 2)",
    "P0300": "Random/Multiple Cylinder Misfire Detected",
    "P0301": "Cylinder 1 Misfire Detected",
    "P0302": "Cylinder 2 Misfire Detected",
    "P0303": "Cylinder 3 Misfire Detected",
    "P0304": "Cylinder 4 Misfire Detected",
    "P0325": "Knock Sensor 1 Circuit Malfunction (Bank 1)",
    "P0335": "Crankshaft Position Sensor A Circuit Malfunction",
    "P0340": "Camshaft Position Sensor Circuit Malfunction",
    "P0401": "Exhaust Gas Recirculation Flow Insufficient Detected",
    "P0420": "Catalyst System Efficiency Below Threshold (Bank 1)",
    "P0430": "Catalyst System Efficiency Below Threshold (Bank 2)",
    "P0440": "Evaporative Emission Control System Malfunction",
    "P0442": "Evaporative Emission Control System Leak Detected (Small Leak)",
    "P0446": "Evaporative Emission Control System Vent Control Circuit Malfunction",
    "P0455": "Evaporative Emission Control System Leak Detected (Gross Leak)",
    "P0500": "Vehicle Speed Sensor Malfunction",
    "P0505": "Idle Control System Malfunction",
    "P0700": "Transmission Control System (MIL Request)",
    "U0100": "Lost Communication With ECM/PCM A",
    "U0121": "Lost Communication With Anti-Lock Brake System (ABS) Control Module",
    "C0035": "Left Front Wheel Speed Sensor Circuit",
}


@dataclass(frozen=True)
class DtcInfo:
    code: str
    system: str
    manufacturer_specific: bool
    subsystem: Optional[str]
    definition: Optional[str]

    @property
    def summary(self) -> str:
        if self.definition:
            return f"{self.code}: {self.definition}"
        bits = [self.system]
        if self.manufacturer_specific:
            bits.append("manufacturer-specific")
        if self.subsystem:
            bits.append(self.subsystem)
        return f"{self.code}: {', '.join(bits)} (no specific definition on file)"


def describe_dtc(code: str) -> DtcInfo:
    """Look up a DTC; fall back to structural category when not curated."""
    if len(code) != 5 or code[0] not in _SYSTEMS:
        raise ValueError(f"malformed DTC code: {code!r}")
    system = _SYSTEMS[code[0]]
    manufacturer_specific = code[1] in ("1", "3")
    subsystem = _P_SUBSYSTEMS.get(code[2]) if code[0] == "P" else None
    return DtcInfo(
        code=code,
        system=system,
        manufacturer_specific=manufacturer_specific,
        subsystem=subsystem,
        definition=DTC_DEFINITIONS.get(code),
    )
