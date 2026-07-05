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

    def test_docs_quote_the_exact_live_banner(self):
        # Drift guard: docs that quote the live banner (in backticks, implying a literal)
        # must keep it byte-exact with the real LIVE_BANNER, so the user can match what
        # they see on-car. Both FIRST_RUN.md AND README.md quote it -- the guard covers
        # BOTH (iter 122 guarded only FIRST_RUN, which is exactly why README.md drifted).
        from fordscope.cli import LIVE_BANNER
        exact = LIVE_BANNER.format(backend="elm327")
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for doc in ("FIRST_RUN.md", "README.md"):
            with self.subTest(doc=doc):
                with open(os.path.join(repo_root, doc)) as fh:
                    self.assertIn(exact, fh.read())

    def test_readme_documents_every_cli_command(self):
        # Drift guard, applied PROACTIVELY per iter-126's lesson ("guard the class before
        # it drifts like the banner did"): every real argparse subcommand must appear in
        # the README's command reference so the user can discover it. Fails if a command
        # is added to the CLI but not documented (a real command missing = undiscoverable).
        from fordscope.cli import _build_parser
        subs = next(a.choices for a in _build_parser()._actions
                    if a.__class__.__name__ == "_SubParsersAction")
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(repo_root, "README.md")) as fh:
            readme = fh.read()
        for cmd in subs:
            with self.subTest(command=cmd):
                self.assertIn(f"`{cmd}", readme)  # documented as a `code` reference

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

    def test_asbuilt_features_lists_the_community_catalog_with_honesty_caveat(self):
        # No hardware needed -- this is the community reference catalog, static data.
        code, out, _ = run("asbuilt-features")
        self.assertEqual(code, 0)
        self.assertIn("UNVERIFIED", out)
        self.assertIn("NEEDS ON-CAR CHECK", out)
        self.assertIn("2GFusions", out)          # SOURCE provenance
        self.assertIn("726-41-02", out)          # a known feature's block_line

    def test_asbuilt_features_module_filter_returns_only_ipc_entries(self):
        code, out, _ = run("asbuilt-features", "--module", "IPC")
        self.assertEqual(code, 0)
        self.assertIn("720-01-01", out)      # awd_gauge (IPC) -- present
        self.assertNotIn("726-41-02", out)   # a BCM-only block_line must be excluded

    def test_asbuilt_features_search_matches_honk_features_only(self):
        code, out, _ = run("asbuilt-features", "--search", "honk")
        self.assertEqual(code, 0)
        self.assertIn("726-41-02", out)   # door_close_double_honk
        self.assertIn("726-38-02", out)   # lock_honk_2x_fob
        self.assertNotIn("720-01-01", out)  # awd_gauge must be excluded (unrelated)

    def test_asbuilt_features_no_match_prints_clean_message_not_a_crash(self):
        code, out, _ = run("asbuilt-features", "--search", "nonexistent_feature_zzz")
        self.assertEqual(code, 0)
        self.assertIn("no match", out.lower())
        # Even an empty result must still show the honesty caveat.
        self.assertIn("UNVERIFIED", out)

    def test_asbuilt_checksum_computes_the_documented_example(self):
        # 760-01-04 3733 -> D6 is the spec's own worked example (hand-derived, not read
        # off the implementation -- see test_fusion_2016_asbuilt.py).
        code, out, _ = run("asbuilt-checksum", "760-01-04", "3733")
        self.assertEqual(code, 0)
        self.assertIn("D6", out.upper())
        # The tool must never imply a checksummed line is safe to write to a car.
        self.assertIn("NEEDS ON-CAR CHECK", out)

    def test_asbuilt_checksum_accepts_spaced_hex(self):
        code, out, _ = run("asbuilt-checksum", "726-17-01", "01 01 01 01 01")
        self.assertEqual(code, 0)
        self.assertIn("4A", out.upper())

    def test_asbuilt_checksum_verify_valid_full_line(self):
        code, out, _ = run("asbuilt-checksum", "--verify", "726-17-01", "01010101014A")
        self.assertEqual(code, 0)
        self.assertIn("VALID", out.upper())
        self.assertNotIn("INVALID", out.upper())
        self.assertIn("NEEDS ON-CAR CHECK", out)

    def test_asbuilt_checksum_verify_invalid_full_line_reports_expected_byte(self):
        # Flip one data byte (01->02) but keep the original trailing checksum (4A);
        # hand-derived expected checksum for the flipped line is 4B (see
        # test_fusion_2016_asbuilt.VerifyFullLineTests).
        code, out, _ = run("asbuilt-checksum", "--verify", "726-17-01", "02010101014A")
        self.assertEqual(code, 0)
        self.assertIn("INVALID", out.upper())
        self.assertIn("4B", out.upper())  # the expected byte must be surfaced

    def test_preflight_runs_with_no_vehicle_connection(self):
        # Static/no-vehicle tier, like features/asbuilt-features: no --backend/--port
        # needed, and it must succeed even though no simulator or serial port is involved
        # in reaching this code path (dispatched before open_backend, same as the other
        # static commands).
        code, out, _ = run("preflight")
        self.assertEqual(code, 0)
        self.assertTrue(out.strip())

    def test_preflight_lists_every_confirmed_module_by_name(self):
        # Hand-derived from reading ford/fusion_2016.py directly (not from running the
        # code under test): the six adversarially-verified CONFIRMED modules.
        code, out, _ = run("preflight")
        self.assertEqual(code, 0)
        for name in ("PCM", "ABS", "RCM", "APIM", "IPC", "BCM"):
            with self.subTest(module=name):
                self.assertIn(name, out)

    def test_preflight_tags_confirmed_modules_with_confirmed_confidence(self):
        # The word "confirmed" must appear attached to this run's output at all (i.e. the
        # confidence tagging is actually rendered, not just the bare module names).
        code, out, _ = run("preflight")
        self.assertEqual(code, 0)
        self.assertIn("confirmed", out)

    def test_preflight_lists_plausible_modules_with_plausible_tag(self):
        # Hand-derived from fusion_2016.py: the ten "plausible" entries include DDM, PDM,
        # ACM, SCCM, FCIM, HSWM, FCDIM, PAM, OCS, PSCM. Spot-check the ones the task names
        # explicitly plus confirm the confidence word itself is rendered.
        code, out, _ = run("preflight")
        self.assertEqual(code, 0)
        for name in ("DDM", "PDM", "ACM", "SCCM", "FCIM", "HSWM", "FCDIM"):
            with self.subTest(module=name):
                self.assertIn(name, out)
        self.assertIn("plausible", out)

    def test_preflight_notes_hswm_and_acm_likely_absent_on_base_s(self):
        # These two carry an explicit "likely ABSENT on base S" style note in
        # fusion_2016.py itself (HSWM: heated-steering-wheel module; ACM: premium/Sony
        # audio) -- the preflight checklist must surface that per-module note text, not
        # just the bare name, so the owner isn't surprised when they don't answer.
        code, out, _ = run("preflight")
        self.assertEqual(code, 0)
        self.assertIn("likely ABSENT on base S", out)

    def test_preflight_contains_backup_before_write_reminder(self):
        code, out, _ = run("preflight")
        self.assertEqual(code, 0)
        self.assertIn("backup", out.lower())
        self.assertIn("before", out.lower())
        self.assertIn("write", out.lower())

    def test_preflight_contains_wired_connection_reminder_for_bdycm_writes(self):
        # Central-config / BdyCM (BCM) writes can reboot the module mid-write -- the
        # runbook's Phase-0 safety gate. Must be plain enough to catch a skim-reader.
        code, out, _ = run("preflight")
        self.assertEqual(code, 0)
        self.assertIn("wired", out.lower())

    def test_preflight_contains_a_never_build_boundary_line(self):
        code, out, _ = run("preflight")
        self.assertEqual(code, 0)
        lowered = out.lower()
        # At least one of the three hard boundaries must be named explicitly, not just
        # implied -- pick the least ambiguous keyword from each.
        self.assertTrue(
            any(term in lowered for term in ("emissions", "immobilizer", "pats", "securityaccess"))
        )
        self.assertIn("never", lowered)

    def test_preflight_contains_needs_on_car_check_framing(self):
        code, out, _ = run("preflight")
        self.assertEqual(code, 0)
        self.assertIn("NEEDS ON-CAR CHECK", out)

    def test_preflight_module_list_matches_fusion_2016_drift_guard(self):
        # Drift guard: every module NAME in FUSION_2016_MODULES must appear in the
        # preflight output, so the runbook/CLI checklist cannot silently fall out of sync
        # with the code if a module is added/removed/renamed later.
        code, out, _ = run("preflight")
        self.assertEqual(code, 0)
        for m in fusion_2016.FUSION_2016_MODULES:
            with self.subTest(module=m.name):
                self.assertIn(m.name, out)

    def test_asbuilt_checksum_bad_hex_is_a_clean_error_not_a_crash(self):
        code, out, err = run("asbuilt-checksum", "726-17-01", "01Z")
        self.assertNotEqual(code, 0)
        self.assertIn("error", err.lower())

    def test_asbuilt_checksum_no_vehicle_needed(self):
        # Static computation -- must not require --backend/--port at all.
        code, out, _ = run("asbuilt-checksum", "760-01-04", "3733")
        self.assertEqual(code, 0)
        self.assertNotIn("SIMULATED VEHICLE", out)

    def test_asbuilt_lookup_known_block_line_lists_its_feature(self):
        # Hand-derived: 726-17-01 is global_windows_close's block_line (see
        # test_fusion_2016_asbuilt.py). No --line given -- just the catalog listing.
        code, out, _ = run("asbuilt-lookup", "726-17-01")
        self.assertEqual(code, 0)
        self.assertIn("Global windows remote close", out)
        self.assertIn("BCM", out)
        self.assertIn("UNVERIFIED", out)
        self.assertIn("NEEDS ON-CAR CHECK", out)

    def test_asbuilt_lookup_is_case_and_space_insensitive(self):
        # 7D0-01-01 is reverse_camera's block_line (APIM) -- has hex letters to case-fold.
        code, out, _ = run("asbuilt-lookup", "  7d0-01-01  ")
        self.assertEqual(code, 0)
        self.assertIn("reverse camera", out.lower())

    def test_asbuilt_lookup_unknown_block_line_prints_clean_reference_only_message(self):
        code, out, _ = run("asbuilt-lookup", "999-99-99")
        self.assertEqual(code, 0)
        self.assertIn("no catalog feature recorded", out.lower())
        self.assertIn("reference only", out.lower())
        # Even the no-match case must still carry the honesty header.
        self.assertIn("UNVERIFIED", out)
        self.assertIn("NEEDS ON-CAR CHECK", out)

    def test_asbuilt_lookup_no_vehicle_needed(self):
        code, out, _ = run("asbuilt-lookup", "726-17-01")
        self.assertEqual(code, 0)
        self.assertNotIn("SIMULATED VEHICLE", out)

    def test_asbuilt_lookup_whitespace_only_block_line_is_clean_not_a_crash(self):
        # Adversarial: an empty/whitespace-only argument must degrade to the same clean
        # no-match message as an unknown block, never a traceback or a 500-style failure.
        code, out, _ = run("asbuilt-lookup", "   ")
        self.assertEqual(code, 0)
        self.assertIn("no catalog feature recorded", out.lower())
        self.assertIn("UNVERIFIED", out)

    def test_asbuilt_lookup_option_match_is_exact_not_substring(self):
        # Adversarial: a value that CONTAINS a known option as a substring, or is a
        # case-different near-miss with extra characters, must NOT be reported as a
        # match -- only an exact (case-insensitive) full-hex match counts. Pad the known
        # "enabled (default)" value 01010101014A with a leading byte so it's no longer a
        # valid full-line value ​for THIS block (wrong length) but embeds the exact known
        # option hex as a substring of the raw text.
        code, out, err = run(
            "asbuilt-lookup", "726-17-01", "--line", "FF01010101014A",
        )
        # Either a clean parse error (odd/implausible length rejected upstream) or, if it
        # parses, it must NOT claim a match against global_windows_close's options --
        # a substring-matching bug would wrongly report "matches: enabled (default)".
        if code == 0:
            self.assertNotIn("matches: enabled (default)", out)

    def test_asbuilt_lookup_with_line_reports_valid_checksum_and_matched_option(self):
        # 726-17-01 + 01010101014A: hand-derived VALID (checksum label 0x45 + data 5 =
        # 0x4A, matching trailing byte -- see test_fusion_2016_asbuilt.py), and this exact
        # hex string IS global_windows_close's "enabled (default)" option value.
        code, out, _ = run("asbuilt-lookup", "726-17-01", "--line", "01010101014A")
        self.assertEqual(code, 0)
        self.assertIn("VALID", out.upper())
        self.assertNotIn("INVALID", out.upper())
        self.assertIn("4A", out.upper())
        self.assertIn("matches", out.lower())
        self.assertIn("enabled (default)", out)
        self.assertIn("NEEDS ON-CAR CHECK", out)

    def test_asbuilt_lookup_with_line_matches_the_disabled_option(self):
        # Hand-derived: label 0x45 + data (00*4=0) = 0x45, matching trailing byte 45 ->
        # VALID; 000000000045 is global_windows_close's "disabled" option value.
        code, out, _ = run("asbuilt-lookup", "726-17-01", "--line", "000000000045")
        self.assertEqual(code, 0)
        self.assertIn("VALID", out.upper())
        self.assertIn("matches", out.lower())
        self.assertIn("disabled", out.lower())

    def test_asbuilt_lookup_with_line_wrong_checksum_reports_invalid_and_expected_byte(self):
        # Flip 01->02 in the first data byte but keep the original checksum byte (4A);
        # hand-derived expected is 4B (same fixture as test_asbuilt_checksum_verify_*).
        code, out, _ = run("asbuilt-lookup", "726-17-01", "--line", "02010101014A")
        self.assertEqual(code, 0)
        self.assertIn("INVALID", out.upper())
        self.assertIn("4B", out.upper())

    def test_asbuilt_lookup_with_line_value_not_a_recognized_option(self):
        # Same flipped-byte line as above: checksum is INVALID AND the raw hex string
        # ("02010101014A") is not any of global_windows_close's option values either --
        # both facts must be reported, distinctly.
        code, out, _ = run("asbuilt-lookup", "726-17-01", "--line", "02010101014A")
        self.assertEqual(code, 0)
        self.assertIn("not a recognized", out.lower())

    def test_asbuilt_lookup_with_line_on_nibble_kind_does_not_guess_the_nibble(self):
        # 726-41-02 is door_close_double_honk, kind="nibble", bits "xxxX xxxx xxxx" --
        # a partial-value feature. The tool must show the checksum result and the bits
        # mask but explicitly refuse to guess which specific option the nibble encodes.
        code, out, _ = run("asbuilt-lookup", "726-41-02", "--line", "010101010149")
        self.assertEqual(code, 0)
        self.assertIn("xxxX xxxx xxxx", out)
        self.assertIn("not attempted", out.lower())
        # Must NOT fabricate a specific matched option for a nibble-kind feature.
        self.assertNotIn("matches: enabled", out)

    def test_asbuilt_lookup_with_line_bad_hex_is_a_clean_error_not_a_crash(self):
        code, out, err = run("asbuilt-lookup", "726-17-01", "--line", "01Z")
        self.assertNotEqual(code, 0)
        self.assertIn("error", err.lower())

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

    def test_keyboard_interrupt_during_command_exits_cleanly(self):
        # Ctrl-C during a slow command (log with intervals, a real-adapter scan) must
        # exit cleanly with a message + code 130, NOT dump a KeyboardInterrupt traceback
        # -- the CLI analog of run()'s clean Ctrl-C handling for the webapp. KeyboardInterrupt
        # is BaseException, so the command block's `except Exception` does not catch it.
        from unittest import mock
        import fordscope.cli as cli
        with mock.patch.object(cli, "scan_vehicle", side_effect=KeyboardInterrupt):
            code, _out, err = run("scan")  # must NOT raise
        self.assertEqual(code, 130)
        self.assertIn("Interrupted", err)


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
