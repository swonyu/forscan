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

    def test_disconnect_clears_state(self):
        c = FordScopeController()
        c.connect(DEMO_PORT)
        c.disconnect()
        self.assertFalse(c.connected)
        with self.assertRaises(NotConnectedError):
            c.scan()


class ServerTests(unittest.TestCase):
    def setUp(self):
        # Fresh server (and fresh controller) per test — no cross-test state.
        self.server = create_server(port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
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


if __name__ == "__main__":
    unittest.main()
