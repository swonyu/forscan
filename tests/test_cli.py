"""CLI tests — drive main() with argv, capture output, assert behavior + exit codes."""
import contextlib
import io
import unittest

from fordscope.cli import main, DEMO_VIN, open_backend, default_modules
from fordscope.transport import SlcanTransport, Elm327Transport


class FakeSerial:
    """Duck-typed serial port with no responses (a silent live bus)."""

    def __init__(self, rx: bytes = b"") -> None:
        self.written = bytearray()
        self._rx = bytearray(rx)

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def read(self, size: int = 1) -> bytes:
        chunk = bytes(self._rx[:size])
        del self._rx[:size]
        return chunk


def fake_port_factory(_name):
    return FakeSerial()


def run(*argv, port_factory=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv), port_factory=port_factory)
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_scan_lists_modules_and_absent(self):
        code, out, _ = run("scan")
        self.assertEqual(code, 0)
        self.assertIn("SIMULATED VEHICLE", out)
        self.assertIn("PCM", out)
        self.assertIn("BCM", out)
        self.assertIn("not present", out)  # APIM

    def test_dtc_report_with_description(self):
        code, out, _ = run("dtc")
        self.assertEqual(code, 0)
        self.assertIn("PCM", out)
        self.assertIn("O2 Sensor Circuit Low Voltage", out)
        self.assertIn("confirmed", out)

    def test_read_rpm_pid(self):
        code, out, _ = run("read", "0C")
        self.assertEqual(code, 0)
        self.assertIn("Engine RPM", out)
        self.assertIn("1000", out)

    def test_read_coolant_pid(self):
        code, out, _ = run("read", "05")
        self.assertEqual(code, 0)
        self.assertIn("coolant", out.lower())
        self.assertIn("50", out)

    def test_vin(self):
        code, out, _ = run("vin")
        self.assertEqual(code, 0)
        self.assertIn(DEMO_VIN, out)

    def test_clear_dtc(self):
        code, out, _ = run("clear-dtc")
        self.assertEqual(code, 0)
        self.assertIn("cleared", out)

    def test_live_backend_requires_port(self):
        code, out, err = run("--backend", "slcan", "scan")  # no --port
        self.assertEqual(code, 2)
        self.assertIn("port is required", err)
        self.assertNotIn("SIMULATED VEHICLE", out)
        self.assertNotIn("LIVE", out)  # never pretended to connect

    def test_live_backend_with_injected_port_runs_and_labels_unvalidated(self):
        code, out, _ = run(
            "--backend", "elm327", "--port", "/dev/fake", "scan",
            port_factory=fake_port_factory,
        )
        self.assertEqual(code, 0)
        self.assertIn("LIVE", out)
        self.assertIn("UNVALIDATED", out)
        self.assertIn("NEEDS ON-CAR CHECK", out)
        # Silent fake bus -> every module reads as not present (honest, no fake data).
        self.assertIn("not present", out)

    def test_no_command_prints_help(self):
        code, out, _ = run()
        self.assertEqual(code, 1)
        self.assertIn("usage", out.lower())

    def test_bad_pid_is_clean_error(self):
        code, _out, err = run("read", "zz")
        self.assertEqual(code, 3)
        self.assertIn("error", err.lower())


class OpenBackendTests(unittest.TestCase):
    def test_simulator_returns_demo_and_simulated_banner(self):
        bus, modules, banner = open_backend("simulator", None)
        self.assertIn("SIMULATED", banner)
        self.assertTrue(modules)

    def test_slcan_constructs_slcan_transport(self):
        bus, modules, banner = open_backend("slcan", "/dev/x", port_factory=fake_port_factory)
        self.assertIsInstance(bus, SlcanTransport)
        self.assertIn("LIVE", banner)
        self.assertEqual(modules, default_modules())

    def test_elm327_constructs_elm327_transport(self):
        bus, _modules, banner = open_backend("elm327", "/dev/x", port_factory=fake_port_factory)
        self.assertIsInstance(bus, Elm327Transport)
        self.assertIn("elm327", banner)

    def test_live_backend_without_port_raises(self):
        with self.assertRaises(ValueError):
            open_backend("slcan", None)


if __name__ == "__main__":
    unittest.main()
