"""Whole-car module scan — connect to each module and read its identification.

For every module address, opens a UDS session over ISO-TP and reads the standard
identification DIDs (part number, software/hardware version, VIN…). A module that
answers anything (positive OR negative) is 'present'; total silence means it is
not on this vehicle.

On-car reality: which modules exist, and their exact addresses, vary by model/year
(the ``ford.addressing`` map is TYPICAL, not authoritative). This walk is how a
real tool discovers what is actually there.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..transport.base import Transport
from ..isotp.socket import IsoTpSocket
from ..uds.client import UdsClient, NegativeResponseError, UdsError
from ..ford.addressing import AddressPair

# Standard ISO 14229 identification DIDs (order = report order).
IDENTIFICATION_DIDS: Sequence[Tuple[int, str]] = (
    (0xF190, "VIN"),
    (0xF187, "Spare part number"),
    (0xF188, "ECU software number"),
    (0xF18C, "ECU serial number"),
    (0xF191, "ECU hardware number"),
    (0xF194, "ECU software version"),
)


@dataclass
class ModuleInfo:
    name: str
    request_id: int
    response_id: int
    present: bool
    identifiers: Dict[str, bytes] = field(default_factory=dict)

    def text(self, label: str) -> Optional[str]:
        value = self.identifiers.get(label)
        return None if value is None else value.decode("ascii", errors="replace")


def connect_module(transport: Transport, pair: AddressPair, *, timeout: float = 1.0) -> UdsClient:
    """Build a UDS client bound to one module's address pair."""
    sock = IsoTpSocket(
        transport,
        tx_id=pair.request_id,
        rx_id=pair.response_id,
        is_extended=pair.is_extended,
        recv_timeout=timeout,
    )
    return UdsClient(sock, p2_timeout=timeout)


def scan_module(
    client: UdsClient,
    pair: AddressPair,
    dids: Sequence[Tuple[int, str]] = IDENTIFICATION_DIDS,
) -> ModuleInfo:
    identifiers: Dict[str, bytes] = {}
    responded = False
    for did, label in dids:
        try:
            identifiers[label] = client.read_data_by_identifier(did)
            responded = True
        except NegativeResponseError:
            responded = True  # it answered, just not with this DID
        except UdsError:
            pass  # silence — no evidence the module is here (yet)
    name = pair.name or f"0x{pair.request_id:X}"
    return ModuleInfo(name, pair.request_id, pair.response_id, responded, identifiers)


def scan_vehicle(
    transport: Transport,
    modules: Sequence[AddressPair],
    dids: Sequence[Tuple[int, str]] = IDENTIFICATION_DIDS,
    *,
    timeout: float = 0.5,
) -> List[ModuleInfo]:
    results: List[ModuleInfo] = []
    for pair in modules:
        client = connect_module(transport, pair, timeout=timeout)
        results.append(scan_module(client, pair, dids))
    return results


def format_scan_report(infos: Sequence[ModuleInfo]) -> str:
    lines: List[str] = []
    for m in infos:
        if not m.present:
            lines.append(f"[--] {m.name} (0x{m.request_id:X}) - not present")
            continue
        lines.append(f"[OK] {m.name} (0x{m.request_id:X})")
        for label, value in m.identifiers.items():
            lines.append(f"       {label}: {value.decode('ascii', errors='replace')}")
    return "\n".join(lines)
