"""OBD-II (SAE J1979) — generic diagnostics over ISO-TP."""

from .pids import (
    PidDef,
    PidResult,
    PID_TABLE,
    decode_pid,
    decode_dtc,
    encode_dtc,
    decode_dtcs,
)
from .client import ObdClient, ObdError, ObdNegativeResponse
from .simulated_ecu import SimulatedObdEcu
from .dtc_database import DtcInfo, DTC_DEFINITIONS, describe_dtc

__all__ = [
    "PidDef",
    "PidResult",
    "PID_TABLE",
    "decode_pid",
    "decode_dtc",
    "encode_dtc",
    "decode_dtcs",
    "ObdClient",
    "ObdError",
    "ObdNegativeResponse",
    "SimulatedObdEcu",
    "DtcInfo",
    "DTC_DEFINITIONS",
    "describe_dtc",
]
