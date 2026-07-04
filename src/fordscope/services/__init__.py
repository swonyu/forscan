"""Application services built on the diagnostic layers (scans, reports, coding)."""

from .module_scan import (
    ModuleInfo,
    IDENTIFICATION_DIDS,
    connect_module,
    scan_module,
    scan_vehicle,
    format_scan_report,
)
from .dtc_scan import (
    ModuleDtcReport,
    scan_module_dtcs,
    scan_vehicle_dtcs,
    total_dtc_count,
    format_dtc_report,
)

__all__ = [
    "ModuleInfo",
    "IDENTIFICATION_DIDS",
    "connect_module",
    "scan_module",
    "scan_vehicle",
    "format_scan_report",
    "ModuleDtcReport",
    "scan_module_dtcs",
    "scan_vehicle_dtcs",
    "total_dtc_count",
    "format_dtc_report",
]
