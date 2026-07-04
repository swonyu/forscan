"""Drive-cycle coach — actionable guidance to complete NOT-READY I/M monitors.

Research-grounded (docs/RESEARCH_2026-07-04, 3-vote verified): ONLY the EVAP monitor's
Ford-specific drive conditions survived verification; the Ford-specific catalyst and
HEGO/O2 drive-cycle claims were REFUTED. So EVAP carries a Ford-verified condition and
every other monitor carries clearly-labeled GENERIC OBD-II guidance (never asserted as
Ford-specific). This is guidance, not a pass guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DriveCycleTip:
    monitor: str
    guidance: str
    ford_verified: bool  # True = Ford-specific 3-vote-verified; False = generic guidance


# monitor name (from decode_monitor_status) -> (guidance, ford_verified)
_GUIDANCE = {
    "Evaporative system": (
        "Drive at a steady 45–65 mph for 10 CONTINUOUS minutes with the fuel tank "
        "between 1/2 and 3/4 full, avoiding hills and sharp turns.", True),
    "Catalyst": (
        "Warm the engine to full operating temperature, then hold a steady 40–55 mph "
        "cruise for several minutes.", False),
    "Heated catalyst": (
        "Warm the engine fully, then hold a steady 40–55 mph cruise for several minutes.", False),
    "Oxygen sensor": (
        "After a cold start and warm-up, alternate steady cruise with gentle "
        "deceleration (throttle closed) to exercise the sensor.", False),
    "Oxygen sensor heater": (
        "A cold start followed by a few minutes of running warms and tests the "
        "sensor heater.", False),
    "EGR system": (
        "Steady-speed cruising with periods of gentle acceleration and deceleration.", False),
    "Secondary air system": (
        "A cold start (the air pump typically runs briefly at startup) followed by warm-up.", False),
    "Misfire": (
        "A continuous monitor — normal varied driving completes it; no special cycle.", False),
    "Fuel system": (
        "A continuous monitor — normal varied driving completes it; no special cycle.", False),
    "Components": (
        "A continuous monitor — normal varied driving completes it; no special cycle.", False),
}
_DEFAULT = (
    "Complete a full OBD-II drive cycle: cold start, idle, steady cruise, "
    "acceleration, and deceleration; several trips may be needed.", False)


def drive_cycle_tips(not_ready_monitors) -> "list[DriveCycleTip]":
    """One tip per not-ready monitor. EVAP is Ford-verified; the rest are clearly-
    labeled generic OBD-II guidance (the Ford-specific cycles for those were refuted)."""
    tips = []
    for m in not_ready_monitors:
        guidance, verified = _GUIDANCE.get(m, _DEFAULT)
        tips.append(DriveCycleTip(monitor=m, guidance=guidance, ford_verified=verified))
    return tips
