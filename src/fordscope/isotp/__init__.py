"""ISO-TP (ISO 15765-2) — segmentation of diagnostic messages over CAN.

Layered as: a stateless frame **codec** (this iteration) and, on top of it, a
stateful segmentation/reassembly + flow-control layer (next iteration).
"""

from .frames import (
    IsoTpFrameType,
    FlowStatus,
    IsoTpPci,
    encode_single_frame,
    encode_first_frame,
    encode_consecutive_frame,
    encode_flow_control,
    parse_isotp,
    pci_type,
    SF_MAX_DATA,
    FF_FIRST_DATA,
    CF_MAX_DATA,
    ISOTP_MAX_CLASSIC_LEN,
)
from .socket import (
    IsoTpSocket,
    IsoTpError,
    IsoTpTimeout,
    IsoTpOverflow,
    IsoTpSequenceError,
    stmin_to_seconds,
)
from .simulated_ecu import SimulatedIsoTpEcu

__all__ = [
    "IsoTpFrameType",
    "FlowStatus",
    "IsoTpPci",
    "encode_single_frame",
    "encode_first_frame",
    "encode_consecutive_frame",
    "encode_flow_control",
    "parse_isotp",
    "pci_type",
    "SF_MAX_DATA",
    "FF_FIRST_DATA",
    "CF_MAX_DATA",
    "ISOTP_MAX_CLASSIC_LEN",
    "IsoTpSocket",
    "IsoTpError",
    "IsoTpTimeout",
    "IsoTpOverflow",
    "IsoTpSequenceError",
    "stmin_to_seconds",
    "SimulatedIsoTpEcu",
]
