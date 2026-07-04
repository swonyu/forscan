"""Web-app controller — the testable bridge between the UI and the engine.

No HTTP or GUI here: it lists serial ports, connects a backend, and runs the
diagnostic commands, returning plain data. Reuses the CLI's ``open_backend`` so
the simulator / elm327 (vLinker FS) / slcan paths and the honesty banner are
identical to the terminal tool.

Thread-safety: one controller (hence one shared transport) serves every
``ThreadingHTTPServer`` worker thread, and the dashboard polls /api/live every
second while the user can click other actions — so two threads would otherwise
interleave request/response frames on the one serial line. Every public method
is serialized on a single **reentrant** lock (reentrant because composite methods
like ``health_report`` call the others, and ``connect`` calls ``disconnect``).
"""
from __future__ import annotations

import functools
import threading
from typing import List, Optional

from ..cli import open_backend, list_serial_ports
from ..isotp import IsoTpSocket
from ..obd import ObdClient, ObdError, ObdNegativeResponse, PID_TABLE

# Range-marker PIDs (0x00/0x20/…) plus status PIDs (0x01 monitor status, 0x02
# freeze-DTC pointer) — none are live-gauge scalars, so keep them out of the picker.
_META_PIDS = {0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0}
_NON_SCALAR_PIDS = _META_PIDS | {0x01, 0x02}
# Common standardized Mode 06 Monitor IDs to sweep (O2, catalyst, EGR, EVAP, misfire).
_COMMON_MODE06_MIDS = (0x01, 0x02, 0x05, 0x06, 0x21, 0x22, 0x31, 0x32, 0x33, 0x3A, 0x3B, 0x3C, 0xA1)
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


def _synchronized(method):
    """Serialize a controller method on its reentrant lock (one shared transport)."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class FordScopeController:
    def __init__(self, *, port_factory=None) -> None:
        self.port_factory = port_factory  # inject a fake serial for tests
        self.transport = None
        self.modules = None
        self.banner: Optional[str] = None
        self._lock = threading.RLock()
        self._live_stats: dict = {}  # pid -> running min/max/sum/count over the session

    @property
    def connected(self) -> bool:
        return self.transport is not None

    @_synchronized
    def connect(self, port: str, *, profile: Optional[str] = None) -> str:
        """Connect the demo simulator or a real serial adapter. Returns the banner."""
        self.disconnect()
        if not port or not port.strip():
            raise ValueError("select a port first")
        if port == DEMO_PORT:
            self.transport, self.modules, self.banner = open_backend(
                "simulator", None, profile=profile
            )
        else:
            self.transport, self.modules, self.banner = open_backend(
                "elm327", port, port_factory=self.port_factory, profile=profile
            )
        return self.banner

    @_synchronized
    def disconnect(self) -> None:
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
        self.transport = None
        self.modules = None
        self.banner = None
        self._live_stats = {}  # a fresh connection starts a fresh session

    def _require(self) -> None:
        if not self.connected:
            raise NotConnectedError("connect to an adapter first")

    def _obd(self) -> ObdClient:
        return ObdClient(IsoTpSocket(self.transport, tx_id=0x7E0, rx_id=0x7E8))

    @_synchronized
    def snapshot(self, read):
        """Run a read callable and capture the banner atomically under the ONE lock,
        returning ``(result, banner)``. Endpoints pair data with the banner; without
        this a concurrent connect/disconnect could swap the banner between the two
        reads and silently drop the LIVE/UNVALIDATED warning shown beside live data."""
        return read(), self.banner

    @_synchronized
    def scan(self) -> str:
        self._require()
        return format_scan_report(scan_vehicle(self.transport, self.modules))

    @_synchronized
    def dtc(self) -> str:
        self._require()
        return format_dtc_report(scan_vehicle_dtcs(self.transport, self.modules))

    @_synchronized
    def dtc_states(self) -> dict:
        """Generic OBD DTCs split by state — confirmed (Mode 03), pending (07),
        permanent (0A) — each with a plain-language meaning. This is the
        emissions/inspection view (distinct from the UDS per-module `dtc()` scan);
        the pending-vs-permanent split is what tells an owner whether a code will
        self-clear or won't clear until the fault is actually fixed."""
        self._require()
        obd = self._obd()

        def _read(mode: int) -> dict:
            # available=False on a genuine comms failure so an empty bucket is never
            # rendered as an affirmative "all-clear" — a failed read is NOT verified
            # absence. A negative response (ECU answered: mode/codes absent) IS a real
            # empty result, so it stays available=True.
            try:
                codes = [{"code": d.code, "definition": d.summary}
                         for d in obd.read_dtcs_described(mode)]
                return {"codes": codes, "available": True}
            except ObdNegativeResponse:
                return {"codes": [], "available": True}
            except (ObdError, KeyError, ValueError):
                return {"codes": [], "available": False}

        return {
            "confirmed": {
                "meaning": "Confirmed over multiple drive cycles — the MIL (check-engine light) is on for these.",
                **_read(0x03),
            },
            "pending": {
                "meaning": "Detected this drive cycle but not yet confirmed — may clear on their own if the fault doesn't recur.",
                **_read(0x07),
            },
            "permanent": {
                "meaning": "Confirmed faults the ECU won't let you clear manually — they clear only after the ECU itself re-verifies the repair over several drive cycles.",
                **_read(0x0A),
            },
        }

    @_synchronized
    def read_pid(self, pid: int) -> dict:
        self._require()
        try:
            r = self._obd().current_data(pid)
            return {"pid": pid, "name": r.name, "value": r.value, "unit": r.unit}
        except (ObdError, KeyError, ValueError):
            # PID valid-hex but not supported/decodable by this ECU — blank it,
            # exactly like live()/log() do, rather than surfacing a server error.
            return {
                "pid": pid,
                "name": f"PID {pid:02X}",
                "value": None,
                "unit": "",
                "supported": False,
                "note": "not supported by this ECU",
            }

    @_synchronized
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
                self._accumulate(pid, r)
            except (ObdError, KeyError, ValueError):
                rows.append({"pid": pid, "name": f"PID {pid:02X}", "value": None, "unit": ""})
        return rows

    def _accumulate(self, pid: int, r) -> None:
        """Fold one live reading into the session's running stats (numeric only;
        bool is excluded even though it's an int subclass)."""
        value = r.value
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return
        s = self._live_stats.get(pid)
        if s is None:
            self._live_stats[pid] = {
                "name": r.name, "unit": r.unit,
                "min": value, "max": value, "sum": float(value), "count": 1,
            }
        else:
            s["min"] = min(s["min"], value)
            s["max"] = max(s["max"], value)
            s["sum"] += value
            s["count"] += 1

    @_synchronized
    def live_stats(self) -> list:
        """Per-PID min / max / avg accumulated over this session's live polling —
        catches intermittent faults a single snapshot misses. Empty until live()
        has run; reset on (re)connect."""
        self._require()
        return [
            {
                "pid": pid, "name": s["name"], "unit": s["unit"],
                "min": s["min"], "max": s["max"],
                "avg": s["sum"] / s["count"], "count": s["count"],
            }
            for pid, s in self._live_stats.items()
        ]

    @_synchronized
    def vin(self) -> str:
        self._require()
        return self._obd().read_vin()

    @_synchronized
    def monitor_tests(self, mids=None) -> list:
        """Mode 06 on-board monitoring test results across the common standardized
        monitors. Each entry: named MID category + raw value/min/max + pass/fail
        (from the ECU's own limits); TID stays raw. Unsupported MIDs are skipped."""
        self._require()
        obd = self._obd()
        out = []
        for mid in (mids or _COMMON_MODE06_MIDS):
            try:
                tests = obd.monitor_tests(mid)
            except (ObdError, KeyError, ValueError):
                continue  # ECU doesn't support this monitor
            if not tests:
                continue
            out.append({
                "mid": mid,
                "mid_hex": f"{mid:02X}",
                "category": tests[0].category,
                "standardized": tests[0].standardized_mid,
                "tests": [
                    {"tid_hex": f"{t.tid:02X}", "value": t.value,
                     "min": t.min_limit, "max": t.max_limit, "passed": t.passed}
                    for t in tests
                ],
            })
        return out

    @_synchronized
    def calibration(self) -> dict:
        """Mode 09 calibration ID(s) + verification number(s) — a module's software
        level (what FORScan/dealers read). Empty lists if the ECU doesn't report
        them, rather than raising. [NEEDS ON-CAR CHECK]"""
        self._require()
        obd = self._obd()

        def _safe(fn):
            try:
                return fn()
            except (ObdError, KeyError, ValueError):
                return []

        return {"calids": _safe(obd.read_calibration_ids), "cvns": _safe(obd.read_cvns)}

    @_synchronized
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

    @_synchronized
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
            cal = self.calibration()
            if cal["calids"] or cal["cvns"]:
                line = "Calibration: " + ", ".join(cal["calids"])
                if cal["cvns"]:
                    line += f"  (CVN {', '.join(cal['cvns'])})"
                lines.append(line)
        except Exception:
            pass  # many ECUs don't report Mode 09 calibration — omit silently

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

        try:
            stats = self.live_stats()
            if stats:
                lines.append("")
                lines.append("Live session (min/max/avg over the polled sample):")
                lines += [
                    f"  {s['name']}: {s['min']}–{s['max']}, avg {s['avg']:.1f} {s['unit']} (n={s['count']})"
                    for s in stats
                ]
        except Exception:
            pass  # no live session captured — omit the section

        return "\n".join(lines)

    @_synchronized
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

    @_synchronized
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

    @_synchronized
    def log_csv(self, pids, samples: int = 10) -> str:
        """Capture ``samples`` fast readings of ``pids`` and return CSV text.
        (A burst capture; the CLI `log --interval` does timed drive logs.)"""
        self._require()
        samples = max(1, int(samples))  # a burst log needs at least one sample
        rows = DataLogger(self._obd(), pids).run(samples, interval=0.0)
        return rows_to_csv(rows, pids)

    @_synchronized
    def clear_dtcs(self) -> None:
        """Clear stored trouble codes (OBD Mode 04) — a real mutating action; the
        UI gates it behind a confirm dialog."""
        self._require()
        self._obd().clear_dtcs()
