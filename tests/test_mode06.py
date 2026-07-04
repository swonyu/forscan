"""Mode 06 (on-board monitoring test results) — decode + client + sim.

Research-grounded (docs/RESEARCH_2026-07-04): MID numbering is SAE-standardized so we
name the monitor CATEGORY; TID meaning/limit semantics are OEM-calibrated so we show
raw value + the ECU's OWN min/max + pass/fail-from-those, and flag TID as OEM-specific.
Fixtures are hand-derived from the ISO 15031-5 record layout, not from the code.
"""
import unittest

from fordscope.transport import SimulatorTransport
from fordscope.isotp import IsoTpSocket, SimulatedIsoTpEcu
from fordscope.obd import ObdClient, ObdNegativeResponse, SimulatedObdEcu
from fordscope.obd.mode06 import decode_monitor_tests, describe_mid

REQ_ID = 0x7DF
RESP_ID = 0x7E8


def make_obd(**ecu_kwargs):
    ecu = SimulatedObdEcu(**ecu_kwargs)
    isotp = SimulatedIsoTpEcu(ecu, request_id=REQ_ID, response_id=RESP_ID)
    bus = SimulatorTransport(isotp)
    bus.open()
    return ObdClient(IsoTpSocket(bus, tx_id=REQ_ID, rx_id=RESP_ID))


class Mode06DecodeTests(unittest.TestCase):
    def test_describe_mid_standard_and_manufacturer(self):
        self.assertEqual(describe_mid(0x21), "Catalyst Monitor Bank 1")
        self.assertEqual(describe_mid(0x31), "EGR Monitor Bank 1")
        self.assertEqual(describe_mid(0xA1), "Misfire Monitor (General)")
        self.assertIn("manufacturer-specific", describe_mid(0x50))

    def test_decode_ignores_truncated_trailing_record(self):
        # one full 9-byte record + a 3-byte partial -> one test, partial dropped
        data = bytes([0x21, 0x80, 0x01, 0x00, 100, 0x00, 50, 0x00, 200]) + bytes([0x22, 0x81, 0x01])
        self.assertEqual(len(decode_monitor_tests(data)), 1)


class Mode06ClientTests(unittest.TestCase):
    def test_single_record_value_limits_and_pass(self):
        client = make_obd(monitor_tests={0x21: [(0x80, 0x01, 100, 50, 200)]})
        tests = client.monitor_tests(0x21)
        self.assertEqual(len(tests), 1)
        t = tests[0]
        self.assertEqual((t.mid, t.tid, t.value, t.min_limit, t.max_limit), (0x21, 0x80, 100, 50, 200))
        self.assertEqual(t.category, "Catalyst Monitor Bank 1")
        self.assertTrue(t.standardized_mid)
        self.assertTrue(t.passed)  # 50 <= 100 <= 200

    def test_fail_when_value_out_of_limits(self):
        client = make_obd(monitor_tests={0x21: [(0x80, 0x01, 250, 50, 200)]})  # 250 > max 200
        self.assertFalse(client.monitor_tests(0x21)[0].passed)

    def test_manufacturer_specific_mid_flagged_not_fabricated(self):
        client = make_obd(monitor_tests={0x50: [(0x01, 0x01, 10, 0, 20)]})  # 0x50 not standardized
        t = client.monitor_tests(0x50)[0]
        self.assertIn("manufacturer-specific", t.category)
        self.assertFalse(t.standardized_mid)

    def test_multiple_records_in_one_mid(self):
        client = make_obd(monitor_tests={0x01: [(0x8E, 0x10, 5, 0, 10), (0x8F, 0x10, 8, 0, 10)]})
        self.assertEqual(len(client.monitor_tests(0x01)), 2)

    def test_unsupported_mid_negative_response(self):
        client = make_obd(monitor_tests={0x21: [(0x80, 0x01, 100, 50, 200)]})
        with self.assertRaises(ObdNegativeResponse):
            client.monitor_tests(0x99)


if __name__ == "__main__":
    unittest.main()
