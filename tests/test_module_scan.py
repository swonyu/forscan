"""Whole-car module scan tests over a multi-module simulated bus."""
import unittest

from fordscope.transport import SimulatorTransport
from fordscope.isotp import SimulatedIsoTpEcu, multiplex
from fordscope.uds import SimulatedUdsEcu
from fordscope.ford import eleven_bit_module
from fordscope.services import scan_vehicle, format_scan_report

VIN = b"1FMHK8D89ABA12345"

PCM = eleven_bit_module(0x7E0, name="PCM")
BCM = eleven_bit_module(0x726, name="BCM")
APIM_ABSENT = eleven_bit_module(0x7D0, name="APIM")
PSCM_EMPTY = eleven_bit_module(0x730, name="PSCM")


def build_bus(*ecus):
    bus = SimulatorTransport(multiplex(*ecus))
    bus.open()
    return bus


def ecu_at(pair, dids):
    return SimulatedIsoTpEcu(
        SimulatedUdsEcu(dids), request_id=pair.request_id, response_id=pair.response_id
    )


class WholeCarScanTests(unittest.TestCase):
    def setUp(self):
        self.pcm = ecu_at(PCM, {0xF190: VIN, 0xF187: b"AB-1234-CD", 0xF188: b"SW-99"})
        self.bcm = ecu_at(BCM, {0xF187: b"BCM-PART-01", 0xF194: b"v3.1"})
        self.bus = build_bus(self.pcm, self.bcm)  # APIM has no ECU -> absent

    def test_present_module_identifiers(self):
        infos = {m.name: m for m in scan_vehicle(self.bus, [PCM, BCM, APIM_ABSENT], timeout=0.1)}
        self.assertTrue(infos["PCM"].present)
        self.assertEqual(infos["PCM"].text("VIN"), "1FMHK8D89ABA12345")
        self.assertEqual(infos["PCM"].text("Spare part number"), "AB-1234-CD")
        self.assertTrue(infos["BCM"].present)
        self.assertEqual(infos["BCM"].text("ECU software version"), "v3.1")

    def test_absent_module_detected(self):
        infos = {m.name: m for m in scan_vehicle(self.bus, [PCM, BCM, APIM_ABSENT], timeout=0.1)}
        self.assertFalse(infos["APIM"].present)
        self.assertEqual(infos["APIM"].identifiers, {})

    def test_module_present_but_no_supported_dids(self):
        # An ECU that answers every identification DID with a negative response
        # is still present (it answered), just carries no identifiers.
        empty = ecu_at(PSCM_EMPTY, {})  # no DIDs -> NRC 0x31 to each read
        bus = build_bus(empty)
        infos = scan_vehicle(bus, [PSCM_EMPTY], timeout=0.1)
        self.assertTrue(infos[0].present)
        self.assertEqual(infos[0].identifiers, {})

    def test_report_formatting(self):
        infos = scan_vehicle(self.bus, [PCM, BCM, APIM_ABSENT], timeout=0.1)
        report = format_scan_report(infos)
        self.assertIn("[OK] PCM", report)
        self.assertIn("1FMHK8D89ABA12345", report)
        self.assertIn("[--] APIM", report)
        self.assertIn("not present", report)


if __name__ == "__main__":
    unittest.main()
