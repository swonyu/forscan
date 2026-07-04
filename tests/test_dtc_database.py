"""DTC-definition database tests: curated lookups + structural fallback + honesty.

The key behavior under test: an uncurated code is NEVER given a fabricated
definition — it gets its structural category and an explicit "no specific
definition on file" marker.
"""
import unittest

from fordscope.transport import SimulatorTransport
from fordscope.isotp import IsoTpSocket, SimulatedIsoTpEcu
from fordscope.obd import ObdClient, SimulatedObdEcu, describe_dtc


class CuratedLookupTests(unittest.TestCase):
    def test_known_code_exact_definition(self):
        info = describe_dtc("P0143")
        self.assertEqual(info.definition, "O2 Sensor Circuit Low Voltage (Bank 1, Sensor 3)")
        self.assertEqual(info.system, "Powertrain")
        self.assertFalse(info.manufacturer_specific)
        self.assertEqual(info.summary, "P0143: O2 Sensor Circuit Low Voltage (Bank 1, Sensor 3)")

    def test_misfire_code(self):
        info = describe_dtc("P0300")
        self.assertIn("Misfire", info.definition)
        self.assertEqual(info.subsystem, "Ignition system or misfire")

    def test_network_and_chassis_systems(self):
        self.assertEqual(describe_dtc("U0100").system, "Network")
        self.assertEqual(describe_dtc("C0035").system, "Chassis")

    def test_added_curated_codes(self):
        self.assertIn("Torque Converter", describe_dtc("P0741").definition)
        self.assertIn("Very Small Leak", describe_dtc("P0456").definition)
        self.assertIn("Injector", describe_dtc("P0201").definition)
        info = describe_dtc("U0155")
        self.assertEqual(info.system, "Network")
        self.assertIn("Instrument Panel Cluster", info.definition)

    def test_database_has_broad_coverage(self):
        from fordscope.obd.dtc_database import DTC_DEFINITIONS
        self.assertGreater(len(DTC_DEFINITIONS), 70)


class FallbackHonestyTests(unittest.TestCase):
    def test_uncurated_code_gets_no_fabricated_definition(self):
        info = describe_dtc("P0199")  # not in the curated table
        self.assertIsNone(info.definition)
        self.assertIn("no specific definition on file", info.summary)
        self.assertEqual(info.subsystem, "Fuel and air metering")  # from the "1"

    def test_manufacturer_specific_flagged(self):
        info = describe_dtc("P1234")  # 2nd char "1" -> manufacturer
        self.assertTrue(info.manufacturer_specific)
        self.assertIsNone(info.definition)
        self.assertIn("manufacturer-specific", info.summary)

    def test_subsystem_only_for_powertrain(self):
        self.assertIsNone(describe_dtc("C0035").subsystem)

    def test_no_fabricated_subsystem_for_manufacturer_or_p2_codes(self):
        # The P0-family third-digit taxonomy is only valid for generic P0xxx codes.
        # For manufacturer (P1/P3) and generic P2 codes it is invalid, so asserting
        # it would fabricate a category next to the "no definition" disclaimer.
        self.assertIsNone(describe_dtc("P1250").subsystem)  # Ford manufacturer code
        self.assertIsNone(describe_dtc("P2270").subsystem)  # generic P2, diff taxonomy
        # ...but a generic P0 code still gets its valid subsystem.
        self.assertEqual(describe_dtc("P0143").subsystem, "Fuel and air metering")

    def test_malformed_code_raises(self):
        for bad in ("X0143", "P143", "P01433", ""):
            with self.assertRaises(ValueError):
                describe_dtc(bad)


class ClientIntegrationTests(unittest.TestCase):
    def test_read_dtcs_described(self):
        ecu = SimulatedObdEcu(dtcs=["P0143", "P1250"])
        isotp_ecu = SimulatedIsoTpEcu(ecu, request_id=0x7DF, response_id=0x7E8)
        bus = SimulatorTransport(isotp_ecu)
        bus.open()
        client = ObdClient(IsoTpSocket(bus, tx_id=0x7DF, rx_id=0x7E8))
        described = client.read_dtcs_described()
        self.assertEqual([d.code for d in described], ["P0143", "P1250"])
        self.assertEqual(described[0].definition, "O2 Sensor Circuit Low Voltage (Bank 1, Sensor 3)")
        # P1250 is manufacturer-specific and uncurated -> flagged, not invented.
        self.assertTrue(described[1].manufacturer_specific)
        self.assertIsNone(described[1].definition)


if __name__ == "__main__":
    unittest.main()
