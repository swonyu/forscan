"""2GFusions community As-Built catalog — honesty + spec cross-checks.

The catalog is community-sourced reference data (UNVERIFIED). These tests do NOT assert the data
is correct on a car (it cannot be, from a simulator) — they assert the transcription is internally
consistent with the *verified* layers: every entry sits on a CONFIRMED module, every block label
matches its module address, and every full-line value carries a correct Ford additive checksum
(the one spec-derivable fact about these values). They also lock the honesty flags so community
data can never be shipped as if verified.
"""
import re
import unittest

from fordscope.ford import fusion_2016, FUSION_2016_ASBUILT, AsBuiltFeatureRef, additive_checksum
from fordscope.ford.fusion_2016_asbuilt import (
    SOURCE, parse_hex_bytes, verify_full_line, features_at_block_line,
)

# The verified module registry (address -> confidence) the catalog must stay consistent with.
REGISTRY = {m.address: m.confidence for m in fusion_2016.FUSION_2016_MODULES}


def _covers_2016(my: str) -> bool:
    """True if a model-year tag ('2014+', '2015+', '2013+', '2013-2016') includes 2016."""
    m = re.fullmatch(r"(\d{4})\+", my)
    if m:
        return int(m.group(1)) <= 2016
    m = re.fullmatch(r"(\d{4})-(\d{4})", my)
    if m:
        return int(m.group(1)) <= 2016 <= int(m.group(2))
    return bool(re.fullmatch(r"\d{4}", my)) and int(my) == 2016


class CatalogHonestyTests(unittest.TestCase):
    def test_catalog_nonempty_with_unique_keys(self):
        self.assertTrue(FUSION_2016_ASBUILT)
        keys = [f.key for f in FUSION_2016_ASBUILT]
        self.assertEqual(len(keys), len(set(keys)), "duplicate feature keys")

    def test_every_entry_is_unverified_and_sourced(self):
        # Community data must never be flagged verified, and the provenance must say so.
        self.assertIn("UNVERIFIED", SOURCE)
        self.assertIn("2GFusions", SOURCE)
        for f in FUSION_2016_ASBUILT:
            self.assertFalse(f.verified, f"{f.key} must not be marked verified")
            self.assertIn("UNVERIFIED", f.note.upper() + SOURCE, f"{f.key} missing caveat")

    def test_every_entry_applies_to_the_2016_target(self):
        # The target is a 2016. Exclude 2013-ONLY blocks (they differ), but keep any range that
        # covers 2016 — "2013+" and "2013-2016" legitimately apply. A bare "2013" is rejected.
        for f in FUSION_2016_ASBUILT:
            self.assertNotEqual(f.my, "2013", f"{f.key}: 2013-only blocks differ — exclude")
            self.assertTrue(_covers_2016(f.my), f"{f.key}: my={f.my!r} does not cover 2016")


class CatalogConsistencyTests(unittest.TestCase):
    def test_module_confidence_mirrors_the_verified_registry(self):
        # Honesty gate: each entry's module_confidence must match fusion_2016's tag for that
        # address, and a module absent from the registry may never be claimed "confirmed". This is
        # what keeps trim-dependent (plausible) modules from masquerading as verified.
        for f in FUSION_2016_ASBUILT:
            self.assertIn(f.module_confidence,
                          {"confirmed", "confirm-on-vehicle", "plausible"}, f.key)
            if f.module_addr in REGISTRY:
                self.assertEqual(
                    f.module_confidence, REGISTRY[f.module_addr],
                    f"{f.key}: 0x{f.module_addr:X} confidence must match the fusion_2016 registry",
                )
            else:
                self.assertNotEqual(
                    f.module_confidence, "confirmed",
                    f"{f.key}: 0x{f.module_addr:X} absent from registry — cannot be 'confirmed'",
                )

    def test_catalog_spans_confirmed_and_plausible_modules(self):
        # Lock the expansion in: the catalog must reach past the confirmed core into the plausible
        # door/audio/steering modules (else a regression silently drops them).
        confidences = {f.module_confidence for f in FUSION_2016_ASBUILT}
        self.assertIn("confirmed", confidences)
        self.assertIn("plausible", confidences)
        addrs = {f.module_addr for f in FUSION_2016_ASBUILT}
        for a in (0x740, 0x741, 0x727, 0x724, 0x7A7, 0x714, 0x7A5):
            self.assertIn(a, addrs, f"remaining module 0x{a:X} missing from the catalog")

    def test_block_label_matches_module_address(self):
        for f in FUSION_2016_ASBUILT:
            mod = f.block_line.split("-")[0]
            self.assertEqual(int(mod, 16), f.module_addr, f"{f.key}: label vs module_addr")
            hi, lo, _block, _line = f.address_bytes()
            self.assertEqual((hi << 8) | lo, f.module_addr, f"{f.key}: address_bytes")

    def test_option_values_are_valid_hex_with_meanings(self):
        for f in FUSION_2016_ASBUILT:
            self.assertTrue(f.options, f"{f.key} has no options")
            for value, meaning in f.options:
                int(value, 16)  # raises ValueError if the transcription isn't hex
                self.assertTrue(meaning.strip(), f"{f.key} option {value!r} has no meaning")


class AdditiveChecksumTests(unittest.TestCase):
    def test_checksum_matches_the_documented_example(self):
        # Pin the helper to the spec's own worked example (report §5): 760-01-04 3733 -> D6.
        # Hand-derived: 07+60+01+04+37+33 = 0xD6. Independent of the catalog data below.
        self.assertEqual(additive_checksum("760-01-04", bytes([0x37, 0x33])), 0xD6)

    def test_every_full_line_value_has_a_correct_checksum(self):
        # Each full-line value is <5 data bytes><1 checksum byte>; the checksum must be the Ford
        # additive checksum over the label + data. A transcription slip in any nibble fails here.
        checked = 0
        for f in FUSION_2016_ASBUILT:
            if f.kind != "full_line":
                continue
            for value, meaning in f.options:
                raw = bytes.fromhex(value)
                self.assertEqual(len(raw), 6, f"{f.key} {value!r}: expected 6 bytes")
                data, checksum = raw[:-1], raw[-1]
                self.assertEqual(
                    additive_checksum(f.block_line, data), checksum,
                    f"{f.key} option {value!r} ({meaning}) fails the additive checksum",
                )
                checked += 1
        self.assertGreaterEqual(checked, 8, "expected several full-line values to validate")


class ParseHexBytesTests(unittest.TestCase):
    """Flexible hex-bytes parsing for the CLI tool -- accepts both a bare run of hex
    digits and space-separated byte pairs, and cleanly rejects malformed input rather
    than crashing or silently truncating."""

    def test_parses_a_bare_hex_run(self):
        self.assertEqual(parse_hex_bytes("0101010101"), bytes([0x01] * 5))

    def test_parses_space_separated_bytes(self):
        self.assertEqual(parse_hex_bytes("01 01 01 01 01"), bytes([0x01] * 5))

    def test_bare_and_spaced_forms_agree(self):
        self.assertEqual(parse_hex_bytes("3733"), parse_hex_bytes("37 33"))
        self.assertEqual(parse_hex_bytes("3733"), bytes([0x37, 0x33]))

    def test_odd_length_hex_raises_valueerror_not_crash(self):
        with self.assertRaises(ValueError):
            parse_hex_bytes("373")

    def test_non_hex_characters_raise_valueerror(self):
        with self.assertRaises(ValueError):
            parse_hex_bytes("37ZZ")

    def test_empty_input_raises_valueerror(self):
        with self.assertRaises(ValueError):
            parse_hex_bytes("")
        with self.assertRaises(ValueError):
            parse_hex_bytes("   ")


class VerifyFullLineTests(unittest.TestCase):
    """verify_full_line() re-derives the additive checksum over a full line value
    (label + data bytes + trailing checksum byte) and reports match/mismatch --
    hand-derived expectations, independent of the catalog data or the implementation."""

    def test_known_valid_full_line_reports_valid_with_matching_expected_byte(self):
        # Hand-derived (independent of additive_checksum's own test above):
        # 726-17-01 label = 07+26+17+01 = 0x45; data 01*5 = 5; total = 0x4A.
        result = verify_full_line("726-17-01", "01010101014A")
        self.assertTrue(result.valid)
        self.assertEqual(result.expected_checksum, 0x4A)
        self.assertEqual(result.actual_checksum, 0x4A)

    def test_flipped_data_byte_reports_invalid_with_the_correct_expected_byte(self):
        # Flip the first data byte 01->02 but keep the original trailing checksum (4A).
        # Hand-derived: label 0x45 + data(02+01+01+01+01=6) = 0x4B != stored 0x4A -> INVALID,
        # and the tool must report what the checksum SHOULD be (0x4B), not just "wrong".
        result = verify_full_line("726-17-01", "02010101014A")
        self.assertFalse(result.valid)
        self.assertEqual(result.expected_checksum, 0x4B)
        self.assertEqual(result.actual_checksum, 0x4A)

    def test_documented_example_line_is_valid(self):
        # 760-01-04 3733 D6 is the spec's own worked example -- assembled as a full line.
        result = verify_full_line("760-01-04", "3733D6")
        self.assertTrue(result.valid)
        self.assertEqual(result.expected_checksum, 0xD6)

    def test_accepts_spaced_hex_in_the_full_line_value(self):
        result = verify_full_line("726-17-01", "01 01 01 01 01 4A")
        self.assertTrue(result.valid)
        self.assertEqual(result.expected_checksum, 0x4A)

    def test_full_line_shorter_than_a_checksum_byte_raises_valueerror(self):
        with self.assertRaises(ValueError):
            verify_full_line("726-17-01", "")

    def test_malformed_label_with_no_dashes_raises_valueerror(self):
        with self.assertRaises(ValueError):
            verify_full_line("not-a-label-at-all-nope", "01010101014A")
        with self.assertRaises(ValueError):
            verify_full_line("726", "01010101014A")

    def test_odd_length_hex_in_full_line_raises_valueerror(self):
        with self.assertRaises(ValueError):
            verify_full_line("726-17-01", "0101010101A")  # odd length, missing a nibble


class FeaturesAtBlockLineTests(unittest.TestCase):
    """features_at_block_line() is the reverse-lookup half of the catalog: given a
    block-line label seen on-screen in FORScan, find which catalog feature(s) live
    there. Expectations are hand-derived directly from reading fusion_2016_asbuilt.py's
    entries -- never from the lookup implementation itself."""

    def test_known_block_line_returns_the_matching_feature(self):
        # Hand-derived: 726-17-01 is global_windows_close's block_line, and no other
        # entry shares it.
        result = features_at_block_line("726-17-01")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].key, "global_windows_close")
        self.assertEqual(result[0].module, "BCM")

    def test_a_different_known_block_line_returns_its_own_feature(self):
        # Hand-derived: 726-41-02 is door_close_double_honk's block_line.
        result = features_at_block_line("726-41-02")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].key, "door_close_double_honk")

    def test_lookup_is_case_and_space_insensitive(self):
        # A user pastes a label with surrounding whitespace or in lowercase off a forum
        # post; the label text itself ("726-17-01") has no letters to case-fold, so use
        # a block_line that DOES contain hex letters: 7D0-01-01 (reverse_camera, APIM).
        canonical = features_at_block_line("7D0-01-01")
        self.assertEqual(len(canonical), 1)
        self.assertEqual(canonical[0].key, "reverse_camera")
        lower = features_at_block_line("7d0-01-01")
        self.assertEqual({f.key for f in lower}, {f.key for f in canonical})
        padded = features_at_block_line("  7D0-01-01  ")
        self.assertEqual({f.key for f in padded}, {f.key for f in canonical})
        mixed = features_at_block_line("  7d0-01-01 ")
        self.assertEqual({f.key for f in mixed}, {f.key for f in canonical})

    def test_unknown_block_line_returns_empty_list_not_a_crash(self):
        result = features_at_block_line("999-99-99")
        self.assertEqual(result, [])

    def test_empty_or_whitespace_block_line_returns_empty_list_not_a_crash(self):
        self.assertEqual(features_at_block_line(""), [])
        self.assertEqual(features_at_block_line("   "), [])

    def test_garbage_block_line_returns_empty_list_not_a_crash(self):
        # No dashes, stray punctuation, etc. -- must degrade to [], never raise.
        self.assertEqual(features_at_block_line("not-a-real-label-at-all-nope"), [])
        self.assertEqual(features_at_block_line("!!!"), [])

    def test_default_catalog_argument_is_the_full_fusion_2016_catalog(self):
        # Calling with just the block_line (no explicit catalog=) must search the real,
        # full catalog -- not an empty default that silently finds nothing.
        result = features_at_block_line("726-17-01")
        self.assertEqual({f.key for f in result}, {"global_windows_close"})

    def test_custom_catalog_argument_is_honored_and_does_not_leak_the_default(self):
        # Passing a narrower catalog restricts the search to it; a block_line that only
        # exists in the DEFAULT catalog must NOT be found against a custom subset that
        # excludes it.
        narrowed = tuple(f for f in FUSION_2016_ASBUILT if f.key != "global_windows_close")
        self.assertEqual(features_at_block_line("726-17-01", catalog=narrowed), [])
        # ...but a block_line that IS still in the narrowed set is still found.
        self.assertEqual(
            {f.key for f in features_at_block_line("726-41-02", catalog=narrowed)},
            {"door_close_double_honk"},
        )


if __name__ == "__main__":
    unittest.main()
