"""Transport layer: CAN-frame abstraction and pluggable backends."""

from .base import (
    CanFrame,
    Transport,
    TransportError,
    TransportNotOpen,
    CAN_MAX_11BIT_ID,
    CAN_MAX_29BIT_ID,
    CAN_MAX_CLASSIC_DLC,
)
from .simulator import (
    SimulatorTransport,
    null_responder,
    echo_responder,
    canned_obd_responder,
)

__all__ = [
    "CanFrame",
    "Transport",
    "TransportError",
    "TransportNotOpen",
    "CAN_MAX_11BIT_ID",
    "CAN_MAX_29BIT_ID",
    "CAN_MAX_CLASSIC_DLC",
    "SimulatorTransport",
    "null_responder",
    "echo_responder",
    "canned_obd_responder",
]
