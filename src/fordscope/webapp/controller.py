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
from ..isotp import IsoTpSocket, IsoTpError
from ..obd import ObdClient, ObdError, ObdNegativeResponse, PID_TABLE
from ..obd.drive_cycle import drive_cycle_tips
from ..ford.fusion_2016_asbuilt import FUSION_2016_ASBUILT, features_at_block_line, verify_full_line
from ..ford.asbuilt_catalog_view import filter_features

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
    def asbuilt_features(self, module=None, search=None) -> List[dict]:
        """The community As-Built catalog (``fusion_2016_asbuilt.FUSION_2016_ASBUILT``),
        optionally filtered by module (name like "BCM"/"IPC", or a numeric/hex address)
        and/or a case-insensitive substring search over name+key.

        REFERENCE/DISPLAY ONLY: this is static catalog data, not a live vehicle read — it
        deliberately does NOT require a connection (no ``_require()``) and never touches
        ``self.transport``. Every returned row carries its own ``module_confidence`` and
        ``verified`` (always False for this catalog) so a caller can never present this as
        verified without the flag being right there in the data.
        """
        rows = []
        for f in filter_features(FUSION_2016_ASBUILT, module=module, search=search):
            rows.append({
                "key": f.key,
                "name": f.name,
                "module": f.module,
                "module_addr": f.module_addr,
                "module_confidence": f.module_confidence,
                "block_line": f.block_line,
                "bits": f.bits,
                "kind": f.kind,
                "options": list(f.options),
                "my": f.my,
                "verified": f.verified,
                "note": f.note,
            })
        return rows

    @_synchronized
    def asbuilt_lookup(self, block_line: str, line: Optional[str] = None) -> dict:
        """Reverse-lookup + checksum for a single As-Built block-line label, e.g.
        "726-17-01" as read off a FORScan screen -- the web-UI equivalent of the CLI's
        ``asbuilt-lookup`` command (reuses the exact same helpers: ``features_at_block_line``
        + ``verify_full_line``).

        REFERENCE/CHECKSUM-MATH ONLY: like ``asbuilt_features``, this deliberately does
        NOT require a connection (no ``_require()``) and never touches ``self.transport``
        or any live UDS DID -- it is pure catalog lookup + offline additive-checksum
        arithmetic over user-supplied hex text.

        Returns a dict:
          - ``features``: the catalog feature(s) at ``block_line`` (same row shape as
            ``asbuilt_features``, i.e. name/module/module_confidence/bits/kind/options/etc.),
            plus, PER FEATURE, a ``matched_option`` key:
              * for a ``full_line``-kind feature (only meaningful when ``line`` is given):
                the option's ``meaning`` on an EXACT (not substring) case-insensitive hex
                match against ``line``'s data+checksum bytes, or ``None`` if no option
                matches -- NEVER a fabricated/partial guess.
              * for a ``nibble``/``byte``-kind feature, or when ``line`` is not given:
                always ``None`` -- the catalog only records the CHANGED field, not the
                surrounding unchanged bytes, so decoding a specific option from a partial
                value would be invented, not derived (mirrors the CLI's honest refusal).
            An unknown/empty ``block_line`` degrades to ``features: []``, never raises.
          - ``checksum``: ``None`` if ``line`` was not given; otherwise
            ``{"valid": bool, "expected": int, "actual": int}`` from ``verify_full_line``.
            HONESTY: a ``valid=True`` checksum means only that the trailing byte is
            self-consistent with label+data -- it does NOT mean the value is correct for
            the vehicle (NEEDS ON-CAR CHECK; callers must keep surfacing that caveat).

        Raises ``ValueError`` if ``line`` is given but is not parseable hex (malformed
        hex is a genuine input error, distinct from an unknown block_line, which is a
        clean empty result) -- the HTTP layer maps this to a 400, never a 500.
        """
        features = features_at_block_line(block_line, FUSION_2016_ASBUILT)
        checksum = None
        given_data_hex = None
        if line is not None:
            result = verify_full_line(block_line, line)  # raises ValueError on bad hex
            checksum = {
                "valid": result.valid,
                "expected": result.expected_checksum,
                "actual": result.actual_checksum,
            }
            # Normalize the given line to bare uppercase hex for an EXACT comparison
            # against each full_line option's value -- never a substring/`in` check.
            given_data_hex = line.replace(" ", "").upper()

        rows = []
        for f in features:
            matched_option = None
            if given_data_hex is not None and f.kind == "full_line":
                matched_option = next(
                    (meaning for value, meaning in f.options if value.upper() == given_data_hex),
                    None,
                )
            rows.append({
                "key": f.key,
                "name": f.name,
                "module": f.module,
                "module_addr": f.module_addr,
                "module_confidence": f.module_confidence,
                "block_line": f.block_line,
                "bits": f.bits,
                "kind": f.kind,
                "options": list(f.options),
                "my": f.my,
                "verified": f.verified,
                "note": f.note,
                "matched_option": matched_option,
            })
        return {"features": rows, "checksum": checksum}

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
            except (ObdError, IsoTpError, KeyError, ValueError):
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
        except (ObdError, IsoTpError, KeyError, ValueError):
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
            except (ObdError, IsoTpError, KeyError, ValueError):
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
            except (ObdError, IsoTpError, KeyError, ValueError):
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
            except (ObdError, IsoTpError, KeyError, ValueError):
                return []

        return {
            "calids": _safe(obd.read_calibration_ids),
            "cvns": _safe(obd.read_cvns),
            "ecu_names": _safe(obd.read_ecu_names),
        }

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
                lines.append("  To complete them (generic OBD-II guidance unless [Ford-verified]):")
                for tip in drive_cycle_tips(rd["not_ready"]):
                    tag = " [Ford-verified]" if tip.ford_verified else ""
                    lines.append(f"    • {tip.monitor}{tag}: {tip.guidance}")
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
            monitors = self.monitor_tests()
            if monitors:
                lines.append("")
                lines.append("Emission monitor self-tests (Mode 06):")
                for m in monitors:
                    verdict = "PASS" if all(t["passed"] for t in m["tests"]) else "FAIL"
                    lines.append(f"  {m['category']}: {verdict}")
        except Exception:
            pass  # Mode 06 not supported / read failed — omit the section

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
    def drive_cycle_coach(self) -> list:
        """Actionable guidance to complete the NOT-READY readiness monitors. EVAP is
        Ford-verified; the rest are clearly-labeled GENERIC OBD-II guidance (the
        Ford-specific cycles for those were refuted in verification) — guidance, not
        a pass guarantee."""
        self._require()
        ms = self._obd().monitor_status()
        return [
            {"monitor": t.monitor, "guidance": t.guidance, "ford_verified": t.ford_verified}
            for t in drive_cycle_tips(ms.not_ready)
        ]

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
            except (ObdError, IsoTpError, KeyError, ValueError):
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
