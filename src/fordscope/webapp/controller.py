"""Web-app controller — the testable bridge between the UI and the engine.

No HTTP or GUI here: it lists serial ports, connects a backend, and runs the
diagnostic commands, returning plain data. Reuses the CLI's ``open_backend`` so
the simulator / elm327 (vLinker FS) / slcan paths and the honesty banner are
identical to the terminal tool.
"""
from __future__ import annotations

from typing import List, Optional

from ..cli import open_backend, list_serial_ports
from ..isotp import IsoTpSocket
from ..obd import ObdClient, ObdError, PID_TABLE

# Range-marker PIDs (0x00/0x20/…) plus status PIDs (0x01 monitor status, 0x02
# freeze-DTC pointer) — none are live-gauge scalars, so keep them out of the picker.
_META_PIDS = {0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0}
_NON_SCALAR_PIDS = _META_PIDS | {0x01, 0x02}
from ..services import (
    scan_vehicle,
    format_scan_report,
    scan_vehicle_dtcs,
    format_dtc_report,
    DataLogger,
    rows_to_csv,
)

DEMO_PORT = "Demo (simulator)"


def list_ports() -> List[str]:
    """Selectable ports: the demo simulator plus real /dev/cu.* serial devices."""
    return [DEMO_PORT] + list_serial_ports()


class NotConnectedError(RuntimeError):
    pass


class FordScopeController:
    def __init__(self, *, port_factory=None) -> None:
        self.port_factory = port_factory  # inject a fake serial for tests
        self.transport = None
        self.modules = None
        self.banner: Optional[str] = None

    @property
    def connected(self) -> bool:
        return self.transport is not None

    def connect(self, port: str, *, profile: Optional[str] = None) -> str:
        """Connect the demo simulator or a real serial adapter. Returns the banner."""
        self.disconnect()
        if port == DEMO_PORT:
            self.transport, self.modules, self.banner = open_backend(
                "simulator", None, profile=profile
            )
        else:
            self.transport, self.modules, self.banner = open_backend(
                "elm327", port, port_factory=self.port_factory, profile=profile
            )
        return self.banner

    def disconnect(self) -> None:
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
        self.transport = None
        self.modules = None
        self.banner = None

    def _require(self) -> None:
        if not self.connected:
            raise NotConnectedError("connect to an adapter first")

    def _obd(self) -> ObdClient:
        return ObdClient(IsoTpSocket(self.transport, tx_id=0x7E0, rx_id=0x7E8))

    def scan(self) -> str:
        self._require()
        return format_scan_report(scan_vehicle(self.transport, self.modules))

    def dtc(self) -> str:
        self._require()
        return format_dtc_report(scan_vehicle_dtcs(self.transport, self.modules))

    def read_pid(self, pid: int) -> dict:
        self._require()
        r = self._obd().current_data(pid)
        return {"pid": pid, "name": r.name, "value": r.value, "unit": r.unit}

    def live(self, pids) -> list:
        """One live-data sample across several PIDs. Unsupported/undecodable PIDs
        return value=None (blank) rather than failing the whole sample."""
        self._require()
        obd = self._obd()
        rows = []
        for pid in pids:
            try:
                r = obd.current_data(pid)
                rows.append({"pid": pid, "name": r.name, "value": r.value, "unit": r.unit})
            except (ObdError, KeyError, ValueError):
                rows.append({"pid": pid, "name": f"PID {pid:02X}", "value": None, "unit": ""})
        return rows

    def vin(self) -> str:
        self._require()
        return self._obd().read_vin()

    def supported_pids(self) -> list:
        """Which data PIDs the ECU reports, each named if FordScope can decode it.
        The meta range-marker PIDs (0x00/0x20/…) are omitted."""
        self._require()
        rows = []
        for pid in self._obd().supported_pids():
            if pid in _NON_SCALAR_PIDS:
                continue
            d = PID_TABLE.get(pid)
            rows.append({
                "pid": pid,
                "hex": f"{pid:02X}",
                "name": d.name if d else f"PID {pid:02X}",
                "decodable": d is not None,
            })
        return rows

    def health_report(self) -> str:
        """A shareable text snapshot: VIN, readiness, whole-car DTCs, freeze frame.
        Each section is independent — one failing section is noted, not fatal."""
        self._require()
        lines = ["FordScope vehicle health report", self.banner or "", ""]

        try:
            lines.append("VIN: " + self.vin())
        except Exception:
            lines.append("VIN: (unavailable)")

        try:
            rd = self.readiness()
            verdict = "READY (likely PASS)" if (rd["ready"] and not rd["mil_on"]) else "NOT READY"
            lines.append(
                f"Inspection readiness: {verdict}  "
                f"(MIL {'ON' if rd['mil_on'] else 'off'}, {rd['dtc_count']} DTC)"
            )
            if rd["not_ready"]:
                lines.append("  Monitors not complete: " + ", ".join(rd["not_ready"]))
        except Exception:
            lines.append("Inspection readiness: (unavailable)")

        lines += ["", "Trouble codes:"]
        try:
            lines.append(self.dtc())
        except Exception:
            lines.append("  (unavailable)")

        lines.append("")
        try:
            fr = self.freeze_frame()
            if fr["dtc"] or fr["rows"]:
                lines.append(f"Freeze frame (triggered by {fr['dtc'] or 'n/a'}):")
                lines += [f"  {r['name']}: {r['value']} {r['unit']}" for r in fr["rows"]]
            else:
                lines.append("Freeze frame: none stored")
        except Exception:
            lines.append("Freeze frame: (unavailable)")

        return "\n".join(lines)

    def readiness(self) -> dict:
        """I/M readiness: MIL, DTC count, inspection-readiness + which monitors aren't complete."""
        self._require()
        ms = self._obd().monitor_status()
        return {
            "mil_on": ms.mil_on,
            "dtc_count": ms.dtc_count,
            "ready": ms.ready,
            "not_ready": ms.not_ready,
        }

    def freeze_frame(self, pids=None) -> dict:
        """The freeze frame: the DTC that triggered it + frozen PID values."""
        self._require()
        obd = self._obd()
        dtc = obd.freeze_frame_dtc()
        rows = []
        for pid in (pids or [0x04, 0x05, 0x0C, 0x0D, 0x11]):
            try:
                r = obd.freeze_frame(pid)
                rows.append({"pid": pid, "name": r.name, "value": r.value, "unit": r.unit})
            except (ObdError, KeyError, ValueError):
                pass  # this PID isn't in the freeze frame -> omit
        return {"dtc": dtc, "rows": rows}

    def log_csv(self, pids, samples: int = 10) -> str:
        """Capture ``samples`` fast readings of ``pids`` and return CSV text.
        (A burst capture; the CLI `log --interval` does timed drive logs.)"""
        self._require()
        rows = DataLogger(self._obd(), pids).run(samples, interval=0.0)
        return rows_to_csv(rows, pids)

    def clear_dtcs(self) -> None:
        """Clear stored trouble codes (OBD Mode 04) — a real mutating action; the
        UI gates it behind a confirm dialog."""
        self._require()
        self._obd().clear_dtcs()
