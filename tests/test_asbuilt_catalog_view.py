"""As-Built catalog VIEW layer — filter + human-readable render, READ-ONLY.

This is a display layer over the community-sourced ``FUSION_2016_ASBUILT`` catalog
(``ford/fusion_2016_asbuilt.py``, honesty-tested separately in
``test_fusion_2016_asbuilt.py``). These tests do NOT re-litigate the catalog's own data
correctness — they pin two different things:

1. Filtering is correct: by module name, by module address, and by case-insensitive
   substring search over name+key — including the empty/no-match case.
2. Every rendering path is honesty-preserving: the UNVERIFIED/NEEDS-ON-CAR-CHECK caveat,
   the SOURCE provenance string, and each feature's own ``module_confidence`` must appear
   in ANY rendered output, even a filtered/narrow one and even an empty result — because a
   rendering that silently drops the caveat is exactly the failure mode this whole tool
   exists to prevent.

Expected values below are hand-derived directly from reading ``fusion_2016_asbuilt.py``
(the entries' own ``block_line``/``module``/``module_addr`` fields), never from the
filter/format code under test.
"""
import unittest

from fordscope.ford.fusion_2016_asbuilt import FUSION_2016_ASBUILT, SOURCE, features_at_block_line
from fordscope.ford.asbuilt_catalog_view import (
    filter_features, format_catalog, format_block_line_lookup,
)

# Hand-derived from fusion_2016_asbuilt.py: the IPC module (0x720) has exactly these
# four block lines, and no other module uses the name "IPC" or the address 0x720.
_IPC_BLOCK_LINES = {"720-01-01", "720-04-01", "720-07-01", "720-03-02"}

# Hand-derived: the two door/lock "honk" features and their block lines.
_HONK_KEYS = {"door_close_double_honk", "lock_honk_2x_fob"}
_HONK_BLOCK_LINES = {"726-41-02", "726-38-02"}


class FilterFeaturesTests(unittest.TestCase):
    def test_no_filters_returns_the_whole_catalog(self):
        result = filter_features(FUSION_2016_ASBUILT)
        self.assertEqual(len(result), len(FUSION_2016_ASBUILT))

    def test_filter_by_module_name_ipc_returns_only_0x720_entries(self):
        result = filter_features(FUSION_2016_ASBUILT, module="IPC")
        self.assertEqual(len(result), 4)
        self.assertTrue(all(f.module == "IPC" for f in result))
        self.assertTrue(all(f.module_addr == 0x720 for f in result))
        self.assertEqual({f.block_line for f in result}, _IPC_BLOCK_LINES)

    def test_filter_by_module_name_is_case_insensitive(self):
        result = filter_features(FUSION_2016_ASBUILT, module="ipc")
        self.assertEqual({f.block_line for f in result}, _IPC_BLOCK_LINES)
        result_mixed = filter_features(FUSION_2016_ASBUILT, module="Ipc")
        self.assertEqual({f.block_line for f in result_mixed}, _IPC_BLOCK_LINES)

    def test_filter_by_numeric_module_address_matches_the_same_set_as_the_name(self):
        by_addr_int = filter_features(FUSION_2016_ASBUILT, module=0x720)
        by_addr_hexstr = filter_features(FUSION_2016_ASBUILT, module="0x720")
        by_name = filter_features(FUSION_2016_ASBUILT, module="IPC")
        self.assertEqual({f.key for f in by_addr_int}, {f.key for f in by_name})
        self.assertEqual({f.key for f in by_addr_hexstr}, {f.key for f in by_name})

    def test_search_honk_matches_both_door_honk_features_and_excludes_others(self):
        result = filter_features(FUSION_2016_ASBUILT, search="honk")
        self.assertEqual({f.key for f in result}, _HONK_KEYS)
        self.assertEqual({f.block_line for f in result}, _HONK_BLOCK_LINES)
        # Excludes an unrelated feature that shares neither the substring nor the module.
        self.assertNotIn("awd_gauge", {f.key for f in result})
        self.assertNotIn("reverse_camera", {f.key for f in result})

    def test_search_is_case_insensitive_and_matches_key_too(self):
        # "HONK" (upper) must still match; the substring also appears in the KEY
        # ("lock_honk_2x_fob"), not just the display name, so search must cover both.
        result = filter_features(FUSION_2016_ASBUILT, search="HONK")
        self.assertEqual({f.key for f in result}, _HONK_KEYS)

    def test_module_and_search_combine_as_an_and_filter(self):
        # BCM has both honk features; asking for IPC + "honk" must yield nothing (BCM != IPC),
        # proving module/search are ANDed, not ORed.
        result = filter_features(FUSION_2016_ASBUILT, module="IPC", search="honk")
        self.assertEqual(result, [])

    def test_no_match_search_yields_an_empty_list_not_a_crash(self):
        result = filter_features(FUSION_2016_ASBUILT, search="nonexistent_feature_zzz")
        self.assertEqual(result, [])

    def test_no_match_module_yields_an_empty_list_not_a_crash(self):
        result = filter_features(FUSION_2016_ASBUILT, module="ZZZ")
        self.assertEqual(result, [])
        result_addr = filter_features(FUSION_2016_ASBUILT, module=0xFFF)
        self.assertEqual(result_addr, [])


class FormatCatalogHonestyTests(unittest.TestCase):
    def test_render_contains_a_known_features_block_line_caveat_and_confidence(self):
        text = format_catalog(FUSION_2016_ASBUILT)
        # Positive behavior: a specific known feature's block_line is actually present...
        self.assertIn("726-41-02", text)  # door_close_double_honk
        # ...alongside the mandatory honesty caveat...
        self.assertIn("UNVERIFIED", text)
        self.assertIn("NEEDS ON-CAR CHECK", text)
        # ...and that feature's own module_confidence tag (BCM is "confirmed").
        self.assertIn("confirmed", text)

    def test_render_includes_the_source_provenance_string(self):
        text = format_catalog(FUSION_2016_ASBUILT)
        self.assertIn(SOURCE, text)

    def test_render_shows_plausible_confidence_for_a_plausible_module_feature(self):
        # heated_wheel_temp sits on HSWM (0x714), tagged "plausible" in the catalog data.
        text = format_catalog(FUSION_2016_ASBUILT, module="HSWM")
        self.assertIn("714-02-01", text)
        self.assertIn("plausible", text)

    def test_filtered_render_still_carries_every_honesty_label(self):
        # Even a narrow, filtered view must not be able to drop the caveat/source/confidence —
        # this is the crux of the honesty requirement: no rendering path may omit them.
        text = format_catalog(FUSION_2016_ASBUILT, module="IPC")
        self.assertIn("UNVERIFIED", text)
        self.assertIn(SOURCE, text)
        self.assertIn("confirmed", text)  # IPC entries are all "confirmed"
        for line in _IPC_BLOCK_LINES:
            self.assertIn(line, text)

    def test_empty_result_renders_a_clean_no_matches_message_not_a_crash(self):
        text = format_catalog(FUSION_2016_ASBUILT, search="nonexistent_feature_zzz")
        self.assertIn("no match", text.lower())
        # The caveat/source must still be present even on a no-results render, so a user
        # scanning only the header of an empty result still sees the honesty framing.
        self.assertIn("UNVERIFIED", text)
        self.assertIn(SOURCE, text)

    def test_render_shows_bits_mask_and_options_as_value_equals_meaning(self):
        # door_close_double_honk: bits "xxxX xxxx xxxx", options ("1","enabled (default)")
        # and ("0","disabled") -- hand-derived directly from fusion_2016_asbuilt.py.
        text = format_catalog(FUSION_2016_ASBUILT, search="door-close double horn honk")
        self.assertIn("xxxX xxxx xxxx", text)
        self.assertIn("1 = enabled (default)", text)
        self.assertIn("0 = disabled", text)

    def test_render_groups_by_module(self):
        # Both BCM "honk" features must appear contiguously (grouped), not interleaved
        # with a DIFFERENT module's name -- i.e. no other module label appears between
        # the two matching feature lines.
        text = format_catalog(FUSION_2016_ASBUILT, search="honk")
        lines = text.splitlines()
        first = next(i for i, l in enumerate(lines) if "726-41-02" in l or "726-38-02" in l)
        last = max(i for i, l in enumerate(lines) if "726-41-02" in l or "726-38-02" in l)
        other_modules = {"IPC", "APIM", "DDM", "PDM", "ACM", "SCCM", "FCIM", "HSWM", "FCDIM"}
        for l in lines[first:last + 1]:
            self.assertFalse(any(m in l for m in other_modules), l)


class FormatBlockLineLookupTests(unittest.TestCase):
    """format_block_line_lookup() is the reverse-lookup renderer: given a block-line
    label (and the features_at_block_line() result for it), render a human-readable
    answer to "what is this line / does its checksum add up?" -- always honesty-
    preserving, never fabricating a specific-nibble decode it can't actually determine.
    """

    def test_renders_the_matched_feature_with_its_details(self):
        # Hand-derived: 726-17-01 is global_windows_close (BCM, confirmed), bits
        # "xXxX xXxX xXxx", options include "01010101014A = enabled (default)".
        features = features_at_block_line("726-17-01")
        text = format_block_line_lookup("726-17-01", features)
        self.assertIn("global_windows_close".replace("_", " "), text.lower().replace("_", " "))
        self.assertIn("Global windows remote close", text)
        self.assertIn("BCM", text)
        self.assertIn("confirmed", text)
        self.assertIn("xXxX xXxX xXxx", text)
        self.assertIn("01010101014A", text)
        self.assertIn("enabled (default)", text)

    def test_render_always_carries_the_honesty_header_and_source(self):
        features = features_at_block_line("726-17-01")
        text = format_block_line_lookup("726-17-01", features)
        self.assertIn("UNVERIFIED", text)
        self.assertIn("NEEDS ON-CAR CHECK", text)
        self.assertIn(SOURCE, text)

    def test_no_feature_at_this_block_line_prints_a_clean_reference_only_message(self):
        # Hand-derived: no catalog entry uses "999-99-99".
        text = format_block_line_lookup("999-99-99", [])
        self.assertIn("no catalog feature recorded", text.lower())
        self.assertIn("reference only", text.lower())
        # Even the empty/no-match render must still carry the mandatory honesty header.
        self.assertIn("UNVERIFIED", text)
        self.assertIn("NEEDS ON-CAR CHECK", text)
        self.assertIn(SOURCE, text)

    def test_render_shows_a_plausible_modules_confidence_honestly(self):
        # heated_wheel_temp (714-02-01) is module_confidence="plausible" -- the render
        # must not upgrade it to "confirmed".
        features = features_at_block_line("714-02-01")
        self.assertEqual({f.key for f in features}, {"heated_wheel_temp"})
        text = format_block_line_lookup("714-02-01", features)
        self.assertIn("plausible", text)
        self.assertNotIn("confirmed", text)


if __name__ == "__main__":
    unittest.main()
