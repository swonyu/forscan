"""Drive-cycle coach — EVAP Ford-verified; everything else labeled generic."""
import unittest

from fordscope.obd.drive_cycle import drive_cycle_tips


class DriveCycleTests(unittest.TestCase):
    def test_evap_is_ford_verified(self):
        tips = {t.monitor: t for t in drive_cycle_tips(["Evaporative system", "Catalyst"])}
        self.assertTrue(tips["Evaporative system"].ford_verified)
        self.assertIn("45–65 mph", tips["Evaporative system"].guidance)

    def test_catalyst_is_generic_not_ford_verified(self):
        # The Ford-specific catalyst cycle was REFUTED in verification — must not be
        # asserted as Ford-verified.
        tips = {t.monitor: t for t in drive_cycle_tips(["Catalyst"])}
        self.assertFalse(tips["Catalyst"].ford_verified)

    def test_unknown_monitor_gets_generic_default(self):
        tips = drive_cycle_tips(["Something Odd"])
        self.assertEqual(len(tips), 1)
        self.assertFalse(tips[0].ford_verified)
        self.assertIn("drive cycle", tips[0].guidance.lower())


if __name__ == "__main__":
    unittest.main()
