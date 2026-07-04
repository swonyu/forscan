"""Web-app tests — controller logic + the HTTP API over a real in-process server.

No browser and no real serial: the demo (simulator) path exercises the full stack;
the live serial path is NEEDS ON-CAR CHECK.
"""
import http.client
import json
import threading
import time
import unittest
from types import SimpleNamespace

from fordscope.webapp.controller import FordScopeController, NotConnectedError, DEMO_PORT, list_ports
from fordscope.webapp.server import create_server
from fordscope.cli import DEMO_VIN


class ControllerTests(unittest.TestCase):
    def test_list_ports_includes_demo_first(self):
        ports = list_ports()
        self.assertEqual(ports[0], DEMO_PORT)

    def test_connect_demo_scan_read_vin(self):
        c = FordScopeController()
        banner = c.connect(DEMO_PORT)
        self.assertIn("SIMULATED", banner)
        self.assertTrue(c.connected)
        self.assertIn("PCM", c.scan())
        self.assertEqual(c.read_pid(0x0C)["value"], 1000.0)
        self.assertTrue(c.vin())

    def test_command_before_connect_raises(self):
        with self.assertRaises(NotConnectedError):
            FordScopeController().scan()

    def test_connect_with_fusion_profile_scans_fusion_modules(self):
        c = FordScopeController()
        c.connect(DEMO_PORT, profile="fusion2016")
        report = c.scan()
        self.assertIn("RCM", report)          # RCM 0x737 is in the Fusion profile...
        self.assertIn("not present", report)  # ...and absent from the demo bus

    def test_live_reads_multiple_pids(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        rows = c.live([0x0C, 0x05])
        self.assertEqual(rows[0]["value"], 1000.0)  # RPM
        self.assertEqual(rows[1]["value"], 50)      # coolant

    def test_live_blank_for_unsupported_pid(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        rows = c.live([0x0C, 0x99])  # 0x99 unsupported
        self.assertEqual(rows[0]["value"], 1000.0)
        self.assertIsNone(rows[1]["value"])

    def test_disconnect_clears_state(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        c.disconnect()
        self.assertFalse(c.connected)
        with self.assertRaises(NotConnectedError):
            c.scan()

    def test_supported_pids_lists_named_data_pids(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        rows = c.supported_pids()
        names = {r["name"] for r in rows}
        self.assertIn("Engine RPM", names)
        self.assertIn("Engine coolant temperature", names)
        self.assertTrue(all(r["decodable"] for r in rows))
        self.assertNotIn(0x00, {r["pid"] for r in rows})  # meta PIDs filtered out

    def test_clear_dtcs_requires_connection(self):
        with self.assertRaises(NotConnectedError):
            FordScopeController().clear_dtcs()

    def test_clear_dtcs_when_connected_does_not_raise(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        c.clear_dtcs()  # no exception

    def test_health_report(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        report = c.health_report()
        self.assertIn(DEMO_VIN, report)
        self.assertIn("NOT READY", report)
        self.assertIn("P0143", report)
        self.assertIn("Freeze frame", report)

    def test_health_report_coaches_not_ready_monitors(self):
        # The demo has a not-ready monitor; the shareable report should not just list
        # it but tell the owner how to complete it (drive-cycle coach integrated).
        c = FordScopeController()
        c.connect(DEMO_PORT)
        report = c.health_report()
        self.assertIn("To complete them", report)
        self.assertIn("•", report)  # a guidance bullet per not-ready monitor

    def test_calibration(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        cal = c.calibration()
        self.assertIn("DEMO-PCM-CAL-01", cal["calids"])
        self.assertEqual(cal["cvns"], ["1A2B3C4D"])

    def test_health_report_includes_calibration(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        report = c.health_report()
        self.assertIn("Calibration", report)
        self.assertIn("DEMO-PCM-CAL-01", report)

    def test_live_stats_tracks_min_max_avg(self):
        # Deterministic aggregation math over a varying sequence.
        c = FordScopeController()
        c.connect(DEMO_PORT)
        for v in (10, 30, 20):
            c._accumulate(0x0C, SimpleNamespace(name="Engine RPM", value=v, unit="rpm"))
        s = {row["pid"]: row for row in c.live_stats()}[0x0C]
        self.assertEqual((s["min"], s["max"], s["avg"], s["count"]), (10, 30, 20.0, 3))

    def test_live_updates_session_stats(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        c.live([0x0C, 0x05])
        c.live([0x0C, 0x05])
        s = {row["pid"]: row for row in c.live_stats()}
        self.assertEqual(s[0x0C]["count"], 2)
        self.assertEqual(s[0x0C]["avg"], 1000.0)  # demo RPM fixed at 1000

    def test_reconnect_resets_session_stats(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        c.live([0x0C])
        c.connect(DEMO_PORT)  # a fresh connection starts a fresh session
        self.assertEqual(c.live_stats(), [])

    def test_health_report_includes_live_stats_after_session(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        c.live([0x0C])
        c.live([0x0C])
        self.assertIn("Live session", c.health_report())

    def test_dtc_states_splits_by_state(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        st = c.dtc_states()
        self.assertIn("P0143", [d["code"] for d in st["confirmed"]["codes"]])
        self.assertIn("P0113", [d["code"] for d in st["pending"]["codes"]])
        self.assertIn("P0420", [d["code"] for d in st["permanent"]["codes"]])
        self.assertIn("won't", st["permanent"]["meaning"].lower())  # plain-language meaning
        self.assertTrue(st["confirmed"]["available"])  # a real read is available=True

    def test_dtc_states_marks_bucket_unavailable_on_comms_failure(self):
        # A genuine comms failure (timeout/dropout) must NOT be rendered as an
        # affirmative empty "all-clear" — the bucket is flagged unavailable.
        from unittest import mock
        from fordscope.obd import ObdError
        c = FordScopeController()
        c.connect(DEMO_PORT)
        with mock.patch("fordscope.obd.ObdClient.read_dtcs_described",
                        side_effect=ObdError("no response to mode 0x03")):
            st = c.dtc_states()
        self.assertFalse(st["confirmed"]["available"])
        self.assertEqual(st["confirmed"]["codes"], [])

    def test_dtc_states_before_connect_raises(self):
        with self.assertRaises(NotConnectedError):
            FordScopeController().dtc_states()

    def test_monitor_tests_lists_seeded_monitors_with_passfail(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        mt = c.monitor_tests()
        cats = {m["category"] for m in mt}
        self.assertIn("Catalyst Monitor Bank 1", cats)
        cat = next(m for m in mt if m["mid"] == 0x21)
        self.assertTrue(cat["tests"][0]["passed"])          # demo catalyst passes
        egr = next(m for m in mt if m["mid"] == 0x31)
        self.assertFalse(egr["tests"][0]["passed"])          # demo EGR fails (out of limits)

    def test_drive_cycle_coach_covers_not_ready_monitors(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        coach = c.drive_cycle_coach()
        self.assertIn("Oxygen sensor", {t["monitor"] for t in coach})  # demo O2 not ready
        self.assertTrue(all("ford_verified" in t and "guidance" in t for t in coach))

    def test_readiness(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        rd = c.readiness()
        self.assertTrue(rd["mil_on"])
        self.assertEqual(rd["dtc_count"], 1)
        self.assertFalse(rd["ready"])
        self.assertIn("Oxygen sensor", rd["not_ready"])

    def test_freeze_frame(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        fr = c.freeze_frame()
        self.assertEqual(fr["dtc"], "P0143")
        vals = {r["name"]: r["value"] for r in fr["rows"]}
        self.assertEqual(vals["Engine RPM"], 1000.0)
        self.assertEqual(vals["Engine coolant temperature"], 45)  # frozen [85] - 40

    def test_log_csv(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        csv = c.log_csv([0x0C, 0x05], samples=3)
        lines = csv.strip().splitlines()
        self.assertIn("Engine RPM (rpm)", lines[0])
        self.assertEqual(len(lines), 4)  # header + 3 sample rows
        self.assertIn("1000.0", lines[1])

    def test_read_unsupported_pid_returns_blank_not_error(self):
        # A valid-hex PID the ECU doesn't support must come back blank (like live),
        # not raise — the user typing an unsupported PID shouldn't get a server error.
        c = FordScopeController()
        c.connect(DEMO_PORT)
        r = c.read_pid(0x99)  # unsupported by the demo ECU
        self.assertIsNone(r["value"])
        self.assertFalse(r.get("supported", True))

    def test_connect_empty_port_gives_clear_error(self):
        # An empty/missing port must fail with a clear "select a port" message,
        # not leak the live-backend pyserial dependency error.
        c = FordScopeController()
        with self.assertRaises(ValueError) as ctx:
            c.connect("")
        self.assertIn("select a port", str(ctx.exception).lower())

    def test_log_csv_negative_samples_clamped_to_one(self):
        # A negative sample count must not silently produce a header-only (empty) log.
        c = FordScopeController()
        c.connect(DEMO_PORT)
        csv = c.log_csv([0x0C], samples=-5)
        lines = csv.strip().splitlines()
        self.assertEqual(len(lines), 2)  # header + exactly one data row


class ServerTests(unittest.TestCase):
    def setUp(self):
        # Fresh server (and fresh controller) per test — no cross-test state.
        self.server = create_server(port=0)
        self.port = self.server.server_address[1]
        # Small poll interval so shutdown() returns fast (keeps the suite quick).
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True
        )
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()  # release the socket (no ResourceWarning)

    # http.client, not urllib — urllib does a slow macOS proxy lookup per call.
    def _req(self, method, path, obj=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            body = json.dumps(obj).encode() if obj is not None else None
            headers = {"Content-Type": "application/json"} if body is not None else {}
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, raw
        finally:
            conn.close()

    def _json(self, method, path, obj=None):
        status, raw = self._req(method, path, obj)
        return status, (json.loads(raw) if raw else {})

    def test_index_page_served(self):
        status, raw = self._req("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("FordScope", raw.decode())

    def test_index_page_has_live_sparkline_feature(self):
        # R4: the served page wires the per-PID live sparkline (history + inline SVG
        # polyline). The sparkline math itself is verified by running (node); this
        # locks that the feature is present in the shipped page.
        _s, raw = self._req("GET", "/")
        html = raw.decode()
        self.assertIn("function sparkline(", html)
        self.assertIn("<polyline", html)
        self.assertIn("liveHistory", html)

    def test_ports_endpoint(self):
        _s, j = self._json("GET", "/api/ports")
        self.assertIn(DEMO_PORT, j["ports"])

    def test_connect_with_profile_via_endpoint(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT, "profile": "fusion2016"})
        _s, j = self._json("GET", "/api/scan")
        self.assertIn("RCM", j["text"])
        self.assertIn("not present", j["text"])

    def test_connect_scan_read_vin_flow(self):
        _s, j = self._json("POST", "/api/connect", {"port": DEMO_PORT})
        self.assertIn("SIMULATED", j["banner"])
        _s, j = self._json("GET", "/api/scan")
        self.assertIn("PCM", j["text"])
        _s, j = self._json("GET", "/api/read?pid=0C")
        self.assertEqual(j["value"], 1000.0)
        _s, j = self._json("GET", "/api/vin")
        self.assertTrue(j["vin"])

    def test_scan_before_connect_returns_409(self):
        status, _raw = self._req("GET", "/api/scan")
        self.assertEqual(status, 409)

    def test_live_endpoint(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        _s, j = self._json("GET", "/api/live?pids=0C,05")
        vals = {r["name"]: r["value"] for r in j["rows"]}
        self.assertEqual(vals["Engine RPM"], 1000.0)
        self.assertEqual(vals["Engine coolant temperature"], 50)

    def test_clear_dtc_endpoint(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        _s, j = self._json("POST", "/api/clear-dtc")
        self.assertTrue(j["ok"])

    def test_clear_dtc_before_connect_returns_409(self):
        status, _raw = self._req("POST", "/api/clear-dtc")
        self.assertEqual(status, 409)

    def test_supported_endpoint(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        _s, j = self._json("GET", "/api/supported")
        self.assertIn("0C", {p["hex"] for p in j["pids"]})  # RPM

    def test_supported_before_connect_returns_409(self):
        status, _raw = self._req("GET", "/api/supported")
        self.assertEqual(status, 409)

    def test_log_endpoint_returns_csv(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        status, raw = self._req("GET", "/api/log?pids=0C,05&samples=2")
        self.assertEqual(status, 200)
        self.assertIn(b"Engine RPM (rpm)", raw)
        self.assertIn(b"1000.0", raw)

    def test_log_before_connect_returns_409(self):
        status, _raw = self._req("GET", "/api/log?pids=0C&samples=2")
        self.assertEqual(status, 409)

    def test_freeze_endpoint(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        _s, j = self._json("GET", "/api/freeze")
        self.assertEqual(j["dtc"], "P0143")
        self.assertTrue(any(r["name"] == "Engine RPM" for r in j["rows"]))

    def test_freeze_before_connect_returns_409(self):
        status, _raw = self._req("GET", "/api/freeze")
        self.assertEqual(status, 409)

    def test_readiness_endpoint(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        _s, j = self._json("GET", "/api/readiness")
        self.assertTrue(j["mil_on"])
        self.assertFalse(j["ready"])
        self.assertIn("Oxygen sensor", j["not_ready"])

    def test_readiness_before_connect_returns_409(self):
        status, _raw = self._req("GET", "/api/readiness")
        self.assertEqual(status, 409)

    def test_calibration_endpoint(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        _s, j = self._json("GET", "/api/calibration")
        self.assertIn("DEMO-PCM-CAL-01", j["calids"])
        self.assertEqual(j["cvns"], ["1A2B3C4D"])

    def test_calibration_before_connect_returns_409(self):
        status, _raw = self._req("GET", "/api/calibration")
        self.assertEqual(status, 409)

    def test_live_stats_endpoint(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        self._json("GET", "/api/live?pids=0C,05")
        _s, j = self._json("GET", "/api/live-stats")
        self.assertIn(0x0C, {s["pid"] for s in j["stats"]})

    def test_live_stats_before_connect_returns_409(self):
        status, _raw = self._req("GET", "/api/live-stats")
        self.assertEqual(status, 409)

    def test_dtc_states_endpoint(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        _s, j = self._json("GET", "/api/dtc-states")
        self.assertIn("P0143", [d["code"] for d in j["confirmed"]["codes"]])
        self.assertIn("P0420", [d["code"] for d in j["permanent"]["codes"]])

    def test_dtc_states_before_connect_returns_409(self):
        status, _raw = self._req("GET", "/api/dtc-states")
        self.assertEqual(status, 409)

    def test_monitor_tests_endpoint(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        _s, j = self._json("GET", "/api/monitor-tests")
        self.assertIn("Catalyst Monitor Bank 1", {m["category"] for m in j["monitors"]})

    def test_monitor_tests_before_connect_returns_409(self):
        status, _raw = self._req("GET", "/api/monitor-tests")
        self.assertEqual(status, 409)

    def test_drive_cycle_endpoint(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        _s, j = self._json("GET", "/api/drive-cycle")
        self.assertTrue(any("guidance" in t for t in j["tips"]))

    def test_drive_cycle_before_connect_returns_409(self):
        status, _raw = self._req("GET", "/api/drive-cycle")
        self.assertEqual(status, 409)

    def test_report_endpoint(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        _s, j = self._json("GET", "/api/report")
        self.assertIn("VIN:", j["report"])
        self.assertIn("P0143", j["report"])

    def test_report_before_connect_returns_409(self):
        status, _raw = self._req("GET", "/api/report")
        self.assertEqual(status, 409)

    def test_bad_hex_pid_is_client_error_400(self):
        # A malformed hex query param is a client error, not a 500.
        status, _raw = self._req("GET", "/api/read?pid=zz")
        self.assertEqual(status, 400)

    def test_read_unsupported_pid_returns_200_blank(self):
        # Unsupported (but valid-hex) PID is a clean blank, not a 500.
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        status, j = self._json("GET", "/api/read?pid=99")
        self.assertEqual(status, 200)
        self.assertIsNone(j["value"])

    def test_connect_no_body_returns_clear_400(self):
        # POST /api/connect with no body must give a clear "select a port" 400,
        # not a misleading pyserial-dependency error.
        status, j = self._json("POST", "/api/connect")
        self.assertEqual(status, 400)
        self.assertIn("select a port", j["error"].lower())

    def test_log_negative_samples_clamped(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        status, raw = self._req("GET", "/api/log?pids=0C&samples=-5")
        self.assertEqual(status, 200)
        lines = raw.decode().strip().splitlines()
        self.assertEqual(len(lines), 2)  # header + one row, not header-only

    def test_report_download(self):
        self._json("POST", "/api/connect", {"port": DEMO_PORT})
        status, raw = self._req("GET", "/api/report.txt")
        self.assertEqual(status, 200)
        self.assertIn(b"VIN:", raw)
        self.assertIn(b"P0143", raw)

    def test_report_download_before_connect_409(self):
        status, _raw = self._req("GET", "/api/report.txt")
        self.assertEqual(status, 409)


class ConcurrencyTests(unittest.TestCase):
    """One `FordScopeController` (hence one shared transport) serves every
    `ThreadingHTTPServer` worker thread. The built-in dashboard polls /api/live
    every second while the user can click scan/read — so two threads WILL touch
    the one serial line at once. Access must be serialized, or their request/
    response frames interleave and corrupt each other on real hardware."""

    def _gated_controller(self):
        """A controller whose OBD op parks a thread mid-flight on an event, so a
        test can observe whether a second thread enters the critical section."""

        class _GatedController(FordScopeController):
            def __init__(self):
                super().__init__()
                self.transport = object()  # look connected without real hardware
                self.reached = threading.Event()
                self.release = threading.Event()
                self.active = 0
                self.max_active = 0
                self._counter = threading.Lock()

            def _obd(self):
                outer = self

                class _Obd:
                    def current_data(self, pid):
                        with outer._counter:
                            outer.active += 1
                            outer.max_active = max(outer.max_active, outer.active)
                        outer.reached.set()
                        outer.release.wait(timeout=2.0)
                        with outer._counter:
                            outer.active -= 1
                        return SimpleNamespace(name="x", value=1, unit="")

                return _Obd()

        return _GatedController()

    def test_transport_access_is_serialized(self):
        c = self._gated_controller()
        t1 = threading.Thread(target=lambda: c.read_pid(0x0C), daemon=True)
        t1.start()
        self.assertTrue(c.reached.wait(1.0))  # t1 is parked inside the critical section
        t2 = threading.Thread(target=lambda: c.read_pid(0x0D), daemon=True)
        t2.start()
        time.sleep(0.3)  # generous window for t2 to (try to) enter
        observed_max = c.max_active  # sampled while t1 is still parked
        c.release.set()
        t1.join(2.0)
        t2.join(2.0)
        self.assertEqual(
            observed_max, 1, "a second thread entered the shared transport concurrently"
        )

    def test_read_snapshot_captures_banner_atomically(self):
        # snapshot(read) must read the banner under the SAME lock as read(), so a
        # concurrent disconnect can't null the banner between the two reads — which
        # would return live data with the LIVE/UNVALIDATED warning silently dropped.
        c = FordScopeController()
        c.connect(DEMO_PORT)
        c.banner = "LIVE-MARKER"
        entered = threading.Event()
        release = threading.Event()
        captured = {}

        def parked_read():
            entered.set()
            release.wait(1.0)
            return "scan-data"

        t1 = threading.Thread(
            target=lambda: captured.update(pair=c.snapshot(parked_read)), daemon=True
        )
        t1.start()
        self.assertTrue(entered.wait(1.0))  # snapshot holds the lock, parked in read
        t2 = threading.Thread(target=c.disconnect, daemon=True)
        t2.start()
        time.sleep(0.2)  # let the disconnect try to run — it must block on the lock
        release.set()
        t1.join(1.0)
        t2.join(1.0)
        self.assertEqual(captured["pair"], ("scan-data", "LIVE-MARKER"))


class RunEntryPointTests(unittest.TestCase):
    def test_run_closes_socket_on_keyboard_interrupt(self):
        # run() must release the listening socket on Ctrl-C (shutdown() alone leaks
        # the fd — only server_close() releases it).
        from unittest import mock
        from fordscope.webapp import server as srv

        fake = mock.MagicMock()
        fake.serve_forever.side_effect = KeyboardInterrupt
        fake.server_address = ("127.0.0.1", 8737)
        with mock.patch.object(srv, "create_server", return_value=fake):
            srv.run(open_browser=False)
        fake.server_close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
