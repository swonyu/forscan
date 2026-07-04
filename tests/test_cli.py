"""CLI tests — drive main() with argv, capture output, assert behavior + exit codes."""
import contextlib
import io
import os
import tempfile
import unittest

from fordscope.cli import (
    main, DEMO_VIN, open_backend, default_modules, modules_for_profile,
    _feature_coder_for, build_demo_vehicle,
)
from fordscope.transport import SlcanTransport, Elm327Transport
from fordscope.ford import fusion_2016, FeatureDefinition


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

    def test_ports_command_runs(self):
        code, out, _ = run("ports")
        self.assertEqual(code, 0)
        # either lists adapters or says none found
        self.assertTrue("adapter" in out.lower() or "serial" in out.lower())

    def test_list_serial_ports_returns_list(self):
        from fordscope.cli import list_serial_ports
        self.assertIsInstance(list_serial_ports(), list)

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

    def test_corrupt_backup_file_gives_actionable_cli_error(self):
        # End-to-end: a corrupt --backup-file must fail with a clean, ACTIONABLE
        # message (exit 3), not a cryptic json/hex error. Pins the real user-facing
        # behavior of the iter-105 CorruptBackupStoreError through the CLI's error path.
        with tempfile.TemporaryDirectory() as d:
            bf = os.path.join(d, "backups.json")
            with open(bf, "w") as fh:
                fh.write("{not valid json")
            code, _out, err = run("--backup-file", bf, "restore-feature", "fog_drl")
            self.assertEqual(code, 3)
            self.assertIn("unreadable/corrupt", err)   # actionable, not a raw json message
            self.assertIn(bf, err)                      # names the offending file

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

    def test_connect_failure_closes_the_port(self):
        # If the port opens but the transport handshake fails, the already-open
        # serial handle must be closed (else a failed retry leaks fds -> device busy).
        class RaisingPort:
            def __init__(self):
                self.closed = False

            def write(self, data):
                raise OSError("device fell off the bus")

            def read(self, n=1):
                return b""

            def close(self):
                self.closed = True

        port = RaisingPort()
        with self.assertRaises(OSError):
            open_backend("elm327", "/dev/x", port_factory=lambda _name: port)
        self.assertTrue(port.closed)

    def test_every_backend_choice_is_handled(self):
        # Invariant guard (root-cause of the iter-98 doc drift): EVERY --backend
        # value argparse accepts must be wired in open_backend(). If a choice is
        # added to the parser but not handled, open_backend() hits its "unknown
        # backend" branch and a user picking a valid-per-argparse backend crashes.
        # Introspect the real choices (a hardcoded list here would drift identically).
        from fordscope.cli import _build_parser

        backend_action = next(a for a in _build_parser()._actions if a.dest == "backend")
        self.assertTrue(backend_action.choices, "expected --backend to define choices")
        for choice in backend_action.choices:
            with self.subTest(backend=choice):
                # simulator ignores the port; live backends consume the fake one.
                _bus, _modules, banner = open_backend(
                    choice, "/dev/x", port_factory=fake_port_factory
                )
                self.assertIsInstance(banner, str)
                self.assertTrue(banner)


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


class FeatureBackupScopeTests(unittest.TestCase):
    def test_backup_keys_are_module_scoped(self):
        # Two features on DIFFERENT modules that reuse the same DID must NOT share a
        # backup slot — else restore-feature would write one module's backup bytes
        # into the other module (a corrupting write that still passes read-back).
        bus, _ = build_demo_vehicle()
        fa = FeatureDefinition(key="a", name="A", module="BCM", did=0xDE01,
                               label="L", byte_index=0, nibble="high", options={"on": 1})
        fb = FeatureDefinition(key="b", name="B", module="IPC", did=0xDE01,
                               label="L", byte_index=0, nibble="high", options={"on": 1})
        ka = _feature_coder_for(bus, fa).coder._key(0xDE01)
        kb = _feature_coder_for(bus, fb).coder._key(0xDE01)
        self.assertNotEqual(ka, kb)


if __name__ == "__main__":
    unittest.main()
