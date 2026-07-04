"""CLI tests — drive main() with argv, capture output, assert behavior + exit codes."""
import contextlib
import io
import os
import tempfile
import unittest

from fordscope.cli import main, DEMO_VIN, open_backend, default_modules, modules_for_profile
from fordscope.transport import SlcanTransport, Elm327Transport
from fordscope.ford import fusion_2016


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

    def test_features_lists_examples_as_unverified(self):
        code, out, _ = run("features")
        self.assertEqual(code, 0)
        self.assertIn("fog_drl", out)
        self.assertIn("gauge_sweep", out)
        self.assertIn("UNVERIFIED", out)

    def test_read_feature_reports_off_and_warns(self):
        code, out, _ = run("read-feature", "fog_drl")
        self.assertEqual(code, 0)
        self.assertIn("off", out)
        self.assertIn("UNVERIFIED", out)

    def test_read_feature_on_ipc_module(self):
        code, out, _ = run("read-feature", "gauge_sweep")
        self.assertEqual(code, 0)
        self.assertIn("off", out)

    def test_read_feature_unknown_key_errors(self):
        code, _out, err = run("read-feature", "nope")
        self.assertEqual(code, 3)
        self.assertIn("unknown feature", err)

    def test_set_feature_dry_run_does_not_write(self):
        code, out, _ = run("set-feature", "fog_drl", "on")  # no --confirm
        self.assertEqual(code, 0)
        self.assertIn("off -> on", out)
        self.assertIn("DRY RUN", out)

    def test_set_feature_confirm_writes_and_verifies(self):
        code, out, _ = run("set-feature", "fog_drl", "on", "--confirm")
        self.assertEqual(code, 0)
        self.assertIn("off -> on", out)
        self.assertIn("read-back verified", out)
        self.assertIn("backed up", out)

    def test_set_feature_refuses_on_live_backend(self):
        code, _out, err = run(
            "--backend", "elm327", "--port", "/dev/fake", "set-feature", "fog_drl", "on", "--confirm",
            port_factory=fake_port_factory,
        )
        self.assertEqual(code, 2)
        self.assertIn("simulator only", err)

    def test_set_feature_unknown_option_errors(self):
        code, _out, err = run("set-feature", "fog_drl", "maybe")
        self.assertEqual(code, 3)
        self.assertIn("unknown option", err)

    def test_set_feature_unknown_feature_errors(self):
        code, _out, err = run("set-feature", "nope", "on")
        self.assertEqual(code, 3)
        self.assertIn("unknown feature", err)

    def test_set_then_restore_feature_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            bf = os.path.join(d, "backups.json")
            code1, out1, _ = run("--backup-file", bf, "set-feature", "fog_drl", "on", "--confirm")
            self.assertEqual(code1, 0)
            self.assertIn("saved to", out1)
            self.assertTrue(os.path.exists(bf))
            # Second invocation restores from the persisted backup.
            code2, out2, _ = run("--backup-file", bf, "restore-feature", "fog_drl")
            self.assertEqual(code2, 0)
            self.assertIn("restored", out2)

    def test_restore_without_backup_errors(self):
        code, _out, err = run("restore-feature", "fog_drl")  # no backup file / none saved
        self.assertEqual(code, 3)
        self.assertIn("no backup", err.lower())

    def test_restore_feature_refuses_on_live_backend(self):
        code, _out, err = run(
            "--backend", "elm327", "--port", "/dev/fake", "restore-feature", "fog_drl",
            port_factory=fake_port_factory,
        )
        self.assertEqual(code, 2)
        self.assertIn("simulator only", err)

    def test_log_to_stdout(self):
        code, out, _ = run("log", "--pids", "0C,05", "--samples", "2", "--interval", "0")
        self.assertEqual(code, 0)
        self.assertIn("Engine RPM (rpm)", out)
        self.assertIn("1000.0", out)

    def test_log_to_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "drive.csv")
            code, out, _ = run("log", "--pids", "0C", "--samples", "2", "--out", path)
            self.assertEqual(code, 0)
            self.assertIn("logged 2 samples", out)
            self.assertTrue(os.path.exists(path))
            with open(path) as fh:
                self.assertIn("Engine RPM (rpm)", fh.read())

    def test_log_bad_pid_errors(self):
        code, _out, err = run("log", "--pids", "zz")
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


class ProfileTests(unittest.TestCase):
    def test_modules_for_profile_fusion2016(self):
        mods = modules_for_profile("fusion2016")
        self.assertEqual(mods, fusion_2016.confirmed_modules())
        self.assertEqual({m.name for m in mods}, {"PCM", "ABS", "RCM", "APIM", "IPC", "BCM"})

    def test_modules_for_profile_generic_and_none(self):
        self.assertEqual(modules_for_profile("generic"), default_modules())
        self.assertIsNone(modules_for_profile(None))

    def test_open_backend_applies_profile_over_demo(self):
        _bus, modules, banner = open_backend("simulator", None, profile="fusion2016")
        self.assertEqual({m.name for m in modules}, {"PCM", "ABS", "RCM", "APIM", "IPC", "BCM"})
        self.assertIn("SIMULATED", banner)

    def test_cli_scan_with_fusion_profile(self):
        code, out, _ = run("--profile", "fusion2016", "scan")
        self.assertEqual(code, 0)
        self.assertIn("PCM", out)
        # RCM (0x737) and APIM (0x7D0) are not in the demo bus -> shown not present.
        self.assertIn("RCM", out)
        self.assertIn("not present", out)


if __name__ == "__main__":
    unittest.main()
