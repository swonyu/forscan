"""Web-app tests — controller logic + the HTTP API over a real in-process server.

No browser and no real serial: the demo (simulator) path exercises the full stack;
the live serial path is NEEDS ON-CAR CHECK.
"""
import http.client
import json
import threading
import unittest

from fordscope.webapp.controller import FordScopeController, NotConnectedError, DEMO_PORT, list_ports
from fordscope.webapp.server import create_server


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

    def test_ports_endpoint(self):
        _s, j = self._json("GET", "/api/ports")
        self.assertIn(DEMO_PORT, j["ports"])

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


if __name__ == "__main__":
    unittest.main()
