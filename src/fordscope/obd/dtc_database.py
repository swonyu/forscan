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
    # --- additional well-established SAE J2012 generic codes ---
    "P0011": "Intake Camshaft Position Timing Over-Advanced or System Performance (Bank 1)",
    "P0016": "Crankshaft/Camshaft Position Correlation (Bank 1, Sensor A)",
    "P0106": "Manifold Absolute Pressure/Barometric Pressure Circuit Range/Performance",
    "P0107": "Manifold Absolute Pressure/Barometric Pressure Circuit Low Input",
    "P0108": "Manifold Absolute Pressure/Barometric Pressure Circuit High Input",
    "P0112": "Intake Air Temperature Circuit Low Input",
    "P0116": "Engine Coolant Temperature Circuit Range/Performance",
    "P0122": "Throttle/Pedal Position Sensor A Circuit Low Input",
    "P0123": "Throttle/Pedal Position Sensor A Circuit High Input",
    "P0125": "Insufficient Coolant Temperature for Closed Loop Fuel Control",
    "P0130": "O2 Sensor Circuit (Bank 1, Sensor 1)",
    "P0132": "O2 Sensor Circuit High Voltage (Bank 1, Sensor 1)",
    "P0134": "O2 Sensor Circuit No Activity Detected (Bank 1, Sensor 1)",
    "P0136": "O2 Sensor Circuit (Bank 1, Sensor 2)",
    "P0141": "O2 Sensor Heater Circuit (Bank 1, Sensor 2)",
    "P0175": "System Too Rich (Bank 2)",
    "P0201": "Injector Circuit/Open - Cylinder 1",
    "P0202": "Injector Circuit/Open - Cylinder 2",
    "P0203": "Injector Circuit/Open - Cylinder 3",
    "P0204": "Injector Circuit/Open - Cylinder 4",
    "P0217": "Engine Coolant Over Temperature Condition",
    "P0305": "Cylinder 5 Misfire Detected",
    "P0306": "Cylinder 6 Misfire Detected",
    "P0316": "Engine Misfire Detected on Startup (First 1000 Revolutions)",
    "P0327": "Knock Sensor 1 Circuit Low Input (Bank 1)",
    "P0336": "Crankshaft Position Sensor A Circuit Range/Performance",
    "P0341": "Camshaft Position Sensor Circuit Range/Performance",
    "P0351": "Ignition Coil A Primary/Secondary Circuit",
    "P0352": "Ignition Coil B Primary/Secondary Circuit",
    "P0402": "Exhaust Gas Recirculation Flow Excessive Detected",
    "P0411": "Secondary Air Injection System Incorrect Flow Detected",
    "P0421": "Warm Up Catalyst Efficiency Below Threshold (Bank 1)",
    "P0441": "Evaporative Emission Control System Incorrect Purge Flow",
    "P0443": "Evaporative Emission Control System Purge Control Valve Circuit",
    "P0449": "Evaporative Emission Control System Vent Valve/Solenoid Circuit",
    "P0456": "Evaporative Emission Control System Leak Detected (Very Small Leak)",
    "P0457": "Evaporative Emission Control System Leak Detected (Fuel Cap Loose/Off)",
    "P0480": "Cooling Fan 1 Control Circuit",
    "P0506": "Idle Air Control System RPM Lower Than Expected",
    "P0507": "Idle Air Control System RPM Higher Than Expected",
    "P0562": "System Voltage Low",
    "P0563": "System Voltage High",
    "P0601": "Internal Control Module Memory Check Sum Error",
    "P0606": "ECM/PCM Processor Fault",
    "P0705": "Transmission Range Sensor Circuit (PRNDL Input)",
    "P0715": "Input/Turbine Speed Sensor Circuit",
    "P0720": "Output Speed Sensor Circuit",
    "P0740": "Torque Converter Clutch Circuit/Open",
    "P0741": "Torque Converter Clutch Circuit Performance or Stuck Off",
    "P0750": "Shift Solenoid A",
    "P0755": "Shift Solenoid B",
    "U0101": "Lost Communication With Transmission Control Module (TCM)",
    "U0140": "Lost Communication With Body Control Module (BCM)",
    "U0155": "Lost Communication With Instrument Panel Cluster (IPC) Control Module",
    # --- series completions (SAE J2012): mechanical siblings of curated entries so
    #     common V6/V8 Fords are recognized, not dropped to the structural fallback ---
    "P0205": "Injector Circuit/Open - Cylinder 5",
    "P0206": "Injector Circuit/Open - Cylinder 6",
    "P0207": "Injector Circuit/Open - Cylinder 7",
    "P0208": "Injector Circuit/Open - Cylinder 8",
    "P0307": "Cylinder 7 Misfire Detected",
    "P0308": "Cylinder 8 Misfire Detected",
    "P0353": "Ignition Coil C Primary/Secondary Circuit",
    "P0354": "Ignition Coil D Primary/Secondary Circuit",
    "P0355": "Ignition Coil E Primary/Secondary Circuit",
    "P0356": "Ignition Coil F Primary/Secondary Circuit",
    "P0357": "Ignition Coil G Primary/Secondary Circuit",
    "P0358": "Ignition Coil H Primary/Secondary Circuit",
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
    # SAE J2012: digit-2 is 0-3 (from 2 bits); digits 3-5 are hex nibbles. A code
    # outside that shape isn't a valid DTC — reject it rather than let it masquerade
    # as a well-formed (if uncurated) code.
    if code[1] not in "0123" or any(c not in "0123456789ABCDEF" for c in code[2:5].upper()):
        raise ValueError(f"malformed DTC code: {code!r}")
    system = _SYSTEMS[code[0]]
    manufacturer_specific = code[1] in ("1", "3")
    # The _P_SUBSYSTEMS third-digit taxonomy is SAE J2012's *generic P0-family*
    # grouping — it is NOT valid for manufacturer codes (P1/P3, where the OEM defines
    # the whole code) nor for generic P2xxx (a different third-digit taxonomy). Assert
    # a subsystem ONLY for P0xxx, else leave it None rather than fabricate a category.
    subsystem = _P_SUBSYSTEMS.get(code[2]) if (code[0] == "P" and code[1] == "0") else None
    return DtcInfo(
        code=code,
        system=system,
        manufacturer_specific=manufacturer_specific,
        subsystem=subsystem,
        definition=DTC_DEFINITIONS.get(code),
    )
