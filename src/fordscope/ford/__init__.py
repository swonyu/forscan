"""Ford-specific enhanced diagnostics — addressing, modules, As-Built (later)."""

from .addressing import (
    AddressPair,
    TESTER_ADDRESS,
    FUNCTIONAL_TARGET_ADDRESS,
    OBD_FUNCTIONAL_REQUEST_ID,
    TYPICAL_FORD_MODULES,
    eleven_bit_module,
    legislated_obd_pair,
    extended_module,
    extended_functional_request_id,
    ford_module,
)

__all__ = [
    "AddressPair",
    "TESTER_ADDRESS",
    "FUNCTIONAL_TARGET_ADDRESS",
    "OBD_FUNCTIONAL_REQUEST_ID",
    "TYPICAL_FORD_MODULES",
    "eleven_bit_module",
    "legislated_obd_pair",
    "extended_module",
    "extended_functional_request_id",
    "ford_module",
]
