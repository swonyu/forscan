"""2016 Fusion profile tests — verified module addresses + honesty on soft data."""
import unittest

from fordscope.ford import fusion_2016 as fz


class ModuleTests(unittest.TestCase):
    def test_confirmed_modules_are_the_six_established_ones(self):
        names = {m.name for m in fz.confirmed_modules()}
        self.assertEqual(names, {"PCM", "ABS", "RCM", "APIM", "IPC", "BCM"})

    def test_pcm_address_pair(self):
        pcm = next(p for p in fz.confirmed_modules() if p.name == "PCM")
        self.assertEqual((pcm.request_id, pcm.response_id), (0x7E0, 0x7E8))
        self.assertFalse(pcm.is_extended)

    def test_bcm_and_ipc_addresses(self):
        by_name = {p.name: p for p in fz.confirmed_modules()}
        self.assertEqual(by_name["BCM"].request_id, 0x726)
        self.assertEqual(by_name["IPC"].request_id, 0x720)

    def test_all_modules_includes_lower_confidence(self):
        self.assertEqual(len(fz.all_modules()), len(fz.FUSION_2016_MODULES))
        self.assertGreater(len(fz.all_modules()), len(fz.confirmed_modules()))

    def test_every_module_has_a_valid_confidence(self):
        for m in fz.FUSION_2016_MODULES:
            self.assertIn(m.confidence, {"confirmed", "confirm-on-vehicle", "plausible"})

    def test_response_ids_follow_plus_eight(self):
        for p in fz.all_modules():
            self.assertEqual(p.response_id, p.request_id + 8)


class AsBuiltHonestyTests(unittest.TestCase):
    def test_notes_are_only_community_or_uncorroborated(self):
        # Guard: no As-Built note may claim to be verified/authoritative.
        for n in fz.FUSION_2016_ASBUILT_NOTES:
            self.assertIn(n.confidence, {"community", "uncorroborated"})

    def test_attribution_correction_is_encoded(self):
        blocks = {n.block: n for n in fz.FUSION_2016_ASBUILT_NOTES}
        # The verification separated walk-away honk (726-41) from lock-chirp (726-38).
        self.assertIn("726-41-02", blocks)
        self.assertIn("726-38", blocks)
        self.assertIn("lock-chirp", blocks["726-41-02"].note)
        self.assertIn("honk", blocks["726-38"].note)

    def test_uncorroborated_lines_are_flagged(self):
        flagged = [n for n in fz.FUSION_2016_ASBUILT_NOTES if n.confidence == "uncorroborated"]
        self.assertTrue(flagged)
        for n in flagged:
            self.assertIn("confirm", n.note.lower())


class ScopeTests(unittest.TestCase):
    def test_scope_excludes_later_years(self):
        self.assertIn("2016", fz.SCOPE)
        self.assertIn("no secure gateway", fz.SCOPE)
        self.assertIn("no secure gateway", fz.__doc__.lower().replace("no secure gateway", "no secure gateway"))
        self.assertIn("2017+", fz.__doc__)


if __name__ == "__main__":
    unittest.main()
