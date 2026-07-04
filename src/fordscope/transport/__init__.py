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
from .slcan import (
    SlcanTransport,
    encode_frame,
    parse_frame,
    bitrate_command,
)
from .elm327 import (
    Elm327Transport,
    header_command,
    payload_line,
    parse_response_line,
    protocol_command,
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
    "SlcanTransport",
    "encode_frame",
    "parse_frame",
    "bitrate_command",
    "Elm327Transport",
    "header_command",
    "payload_line",
    "parse_response_line",
    "protocol_command",
]
