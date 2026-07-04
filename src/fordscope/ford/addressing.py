"""Ford / ISO 15765-4 diagnostic addressing.

Two schemes:

* **11-bit** — the legislated OBD pairs (0x7E0->0x7E8 …) and Ford's proprietary
  module convention where the response is the request id + 8 (e.g. 0x726->0x72E).
* **29-bit normal fixed** — 0x18DA{target}{source} request, 0x18DA{source}{target}
  response (so with the tester source 0xF1, response = 0x18DAF1{target}), and the
  0x18DB33F1 functional request.

AUTHORITATIVE HERE: the addressing *math* (a public standard). NOT authoritative:
the specific Ford module address bytes in ``TYPICAL_FORD_MODULES`` — those are
proprietary, vary by model/year, and MUST be confirmed on the actual vehicle
(NEEDS ON-CAR CHECK). The math is proven; the module map is a starting point.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

TESTER_ADDRESS = 0xF1
FUNCTIONAL_TARGET_ADDRESS = 0x33
OBD_FUNCTIONAL_REQUEST_ID = 0x7DF

_EXT_PHYS_PREFIX = 0x18DA0000
_EXT_FUNC_PREFIX = 0x18DB0000
_ELEVEN_BIT_RESPONSE_OFFSET = 0x08
_CAN_11BIT_MAX = 0x7FF


@dataclass(frozen=True)
class AddressPair:
    """A request/response CAN-ID pair for one module."""

    request_id: int
    response_id: int
    is_extended: bool
    name: Optional[str] = None


# --- 11-bit ------------------------------------------------------------
def eleven_bit_module(request_id: int, *, name: Optional[str] = None) -> AddressPair:
    """Ford 11-bit module: response = request + 8."""
    if not 0 <= request_id <= _CAN_11BIT_MAX:
        raise ValueError(f"11-bit request id out of range: 0x{request_id:X}")
    resp = request_id + _ELEVEN_BIT_RESPONSE_OFFSET
    if resp > _CAN_11BIT_MAX:
        raise ValueError(f"response id 0x{resp:X} exceeds 11-bit range")
    return AddressPair(request_id, resp, is_extended=False, name=name)


def legislated_obd_pair(ecu_index: int = 0) -> AddressPair:
    """The legislated OBD-II physical pairs: 0x7E0+n / 0x7E8+n (n = 0..7)."""
    if not 0 <= ecu_index <= 7:
        raise ValueError(f"ECU index must be 0..7, got {ecu_index}")
    return eleven_bit_module(0x7E0 + ecu_index, name=f"OBD ECU #{ecu_index + 1}")


# --- 29-bit normal fixed ----------------------------------------------
def extended_module(
    target_address: int,
    source_address: int = TESTER_ADDRESS,
    *,
    name: Optional[str] = None,
) -> AddressPair:
    """29-bit physical pair: 0x18DA{TA}{SA} request, 0x18DA{SA}{TA} response."""
    for label, addr in (("target", target_address), ("source", source_address)):
        if not 0 <= addr <= 0xFF:
            raise ValueError(f"{label} address must be a byte, got 0x{addr:X}")
    request_id = _EXT_PHYS_PREFIX | (target_address << 8) | source_address
    response_id = _EXT_PHYS_PREFIX | (source_address << 8) | target_address
    return AddressPair(request_id, response_id, is_extended=True, name=name)


def extended_functional_request_id(source_address: int = TESTER_ADDRESS) -> int:
    """29-bit functional (broadcast) request id: 0x18DB33F1 with the default tester."""
    if not 0 <= source_address <= 0xFF:
        raise ValueError(f"source address must be a byte, got 0x{source_address:X}")
    return _EXT_FUNC_PREFIX | (FUNCTIONAL_TARGET_ADDRESS << 8) | source_address


# --- Typical Ford module map (NOT authoritative — confirm on-vehicle) ---
# Community-observed 11-bit request ids. Response follows request + 8. Exact
# addresses differ by model/year and bus (HS-CAN vs MS-CAN); treat as a probe
# starting point, never as guaranteed for a given truck.
TYPICAL_FORD_MODULES = {
    "PCM": 0x7E0,   # Powertrain Control Module (legislated engine address)
    "TCM": 0x7E1,   # Transmission Control Module
    "ABS": 0x760,   # Anti-lock Brake System
    "BCM": 0x726,   # Body Control Module
    "IPC": 0x720,   # Instrument Panel Cluster
    "PSCM": 0x730,  # Power Steering Control Module
    "RCM": 0x737,   # Restraints Control Module
    "APIM": 0x7D0,  # SYNC / infotainment
    "HVAC": 0x733,  # Climate control
    "PAM": 0x736,   # Parking Aid Module
}


def ford_module(name: str) -> AddressPair:
    """Build an 11-bit pair for a named module from the typical map.

    The address is a TYPICAL value — confirm it against the actual vehicle
    before trusting a module you reach this way.
    """
    key = name.upper()
    if key not in TYPICAL_FORD_MODULES:
        raise KeyError(f"no typical address on file for module {name!r}")
    return eleven_bit_module(TYPICAL_FORD_MODULES[key], name=key)
