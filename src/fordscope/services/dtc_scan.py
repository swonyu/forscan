"""Whole-car DTC scan — read trouble codes from every module and describe them.

Walks the module list, reads each module's DTCs via UDS ReadDTCInformation (0x19),
and pairs each code with its human description from the OBD DTC database. A module
that answers (positive or negative) is present; silence means absent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

from ..transport.base import Transport
from ..isotp.socket import IsoTpError
from ..uds.client import NegativeResponseError, UdsError
from ..uds.dtc import UdsDtc
from ..ford.addressing import AddressPair
from ..obd.dtc_database import describe_dtc
from .module_scan import connect_module


@dataclass
class ModuleDtcReport:
    name: str
    request_id: int
    present: bool
    dtcs: List[UdsDtc] = field(default_factory=list)


def scan_module_dtcs(client, pair: AddressPair) -> ModuleDtcReport:
    name = pair.name or f"0x{pair.request_id:X}"
    try:
        dtcs = client.read_dtc_information()
        return ModuleDtcReport(name, pair.request_id, True, dtcs)
    except NegativeResponseError:
        # module answered but doesn't support 0x19 / has none -> present, no dtcs
        return ModuleDtcReport(name, pair.request_id, True, [])
    except IsoTpError:
        # answered then faulted mid-transfer -> present, no dtcs (don't abort the walk)
        return ModuleDtcReport(name, pair.request_id, True, [])
    except UdsError:
        # silence -> not on this vehicle
        return ModuleDtcReport(name, pair.request_id, False, [])


def scan_vehicle_dtcs(
    transport: Transport,
    modules: Sequence[AddressPair],
    *,
    timeout: float = 0.5,
) -> List[ModuleDtcReport]:
    reports: List[ModuleDtcReport] = []
    for pair in modules:
        client = connect_module(transport, pair, timeout=timeout)
        reports.append(scan_module_dtcs(client, pair))
    return reports


def total_dtc_count(reports: Sequence[ModuleDtcReport]) -> int:
    return sum(len(r.dtcs) for r in reports)


def format_dtc_report(reports: Sequence[ModuleDtcReport]) -> str:
    lines: List[str] = []
    for r in reports:
        if not r.present:
            lines.append(f"[--] {r.name} (0x{r.request_id:X}) - not present")
            continue
        if not r.dtcs:
            lines.append(f"[OK] {r.name} (0x{r.request_id:X}) - no codes")
            continue
        lines.append(f"[!!] {r.name} (0x{r.request_id:X}) - {len(r.dtcs)} code(s)")
        for dtc in r.dtcs:
            desc = describe_dtc(dtc.code).summary
            flags = []
            if dtc.confirmed:
                flags.append("confirmed")
            if dtc.pending:
                flags.append("pending")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            lines.append(f"       {desc}{flag_str}")
    return "\n".join(lines)
