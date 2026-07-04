"""CLI tests — drive main() with argv, capture output, assert behavior + exit codes."""
import contextlib
import io
import unittest

from fordscope.cli import main, DEMO_VIN


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
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

    def test_unimplemented_backend_refuses(self):
        code, out, err = run("--backend", "slcan", "scan")
        self.assertEqual(code, 2)
        self.assertIn("not implemented", err)
        self.assertNotIn("SIMULATED VEHICLE", out)  # never pretended to connect

    def test_no_command_prints_help(self):
        code, out, _ = run()
        self.assertEqual(code, 1)
        self.assertIn("usage", out.lower())

    def test_bad_pid_is_clean_error(self):
        code, _out, err = run("read", "zz")
        self.assertEqual(code, 3)
        self.assertIn("error", err.lower())


if __name__ == "__main__":
    unittest.main()
