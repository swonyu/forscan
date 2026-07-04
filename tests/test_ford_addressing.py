"""Ford addressing tests.

The addressing MATH is asserted authoritatively (public ISO 15765-4 standard).
The typical module *addresses* are only checked for structural consistency
(response = request + 8), never asserted as correct for a real vehicle.
"""
import unittest

from fordscope.transport import SimulatorTransport
from fordscope.isotp import IsoTpSocket, SimulatedIsoTpEcu
from fordscope.uds import UdsClient, SimulatedUdsEcu
from fordscope.ford import (
    eleven_bit_module,
    legislated_obd_pair,
    extended_module,
    extended_functional_request_id,
    ford_module,
    TYPICAL_FORD_MODULES,
    OBD_FUNCTIONAL_REQUEST_ID,
)


class ElevenBitTests(unittest.TestCase):
    def test_response_is_request_plus_eight(self):
        pair = eleven_bit_module(0x726)
        self.assertEqual((pair.request_id, pair.response_id), (0x726, 0x72E))
        self.assertFalse(pair.is_extended)

    def test_legislated_pairs(self):
        self.assertEqual(legislated_obd_pair(0).request_id, 0x7E0)
        self.assertEqual(legislated_obd_pair(0).response_id, 0x7E8)
        self.assertEqual(legislated_obd_pair(1).request_id, 0x7E1)
        self.assertEqual(legislated_obd_pair(1).response_id, 0x7E9)

    def test_functional_obd_id(self):
        self.assertEqual(OBD_FUNCTIONAL_REQUEST_ID, 0x7DF)

    def test_validation(self):
        with self.assertRaises(ValueError):
            eleven_bit_module(0x800)  # over 11-bit
        with self.assertRaises(ValueError):
            eleven_bit_module(0x7FA)  # +8 would overflow 0x7FF
        with self.assertRaises(ValueError):
            legislated_obd_pair(8)


class ExtendedAddressingTests(unittest.TestCase):
    def test_physical_request_and_response_ids(self):
        pair = extended_module(0x10)  # e.g. PCM target 0x10, tester 0xF1
        self.assertEqual(pair.request_id, 0x18DA10F1)
        self.assertEqual(pair.response_id, 0x18DAF110)
        self.assertTrue(pair.is_extended)

    def test_target_and_source_swap_in_response(self):
        # 29-bit target is a single byte (0x72), NOT the 11-bit module id 0x720.
        pair = extended_module(0x72, 0xF1)
        self.assertEqual(pair.request_id, 0x18DA72F1)
        self.assertEqual(pair.response_id, 0x18DAF172)

    def test_functional_request_id(self):
        self.assertEqual(extended_functional_request_id(), 0x18DB33F1)

    def test_validation(self):
        with self.assertRaises(ValueError):
            extended_module(0x100)  # not a byte


class TypicalModuleMapTests(unittest.TestCase):
    def test_known_names_present(self):
        for name in ("PCM", "BCM", "IPC", "APIM", "ABS"):
            self.assertIn(name, TYPICAL_FORD_MODULES)

    def test_map_entries_are_structurally_consistent(self):
        # Only assert the +8 response relationship, never that the address is
        # correct for a specific truck.
        for name in TYPICAL_FORD_MODULES:
            pair = ford_module(name)
            self.assertEqual(pair.response_id, pair.request_id + 8)
            self.assertEqual(pair.name, name)

    def test_unknown_module_raises(self):
        with self.assertRaises(KeyError):
            ford_module("NOSUCH")


class ExtendedAddressingEndToEndTests(unittest.TestCase):
    def test_uds_over_29bit_addressing(self):
        # Prove 29-bit addressing flows through transport -> ISO-TP -> UDS.
        pair = extended_module(0x72, name="IPC")  # 29-bit target byte
        ecu = SimulatedUdsEcu({0xF111: b"cluster-config-block"})
        isotp_ecu = SimulatedIsoTpEcu(
            ecu, request_id=pair.request_id, response_id=pair.response_id, is_extended=True
        )
        bus = SimulatorTransport(isotp_ecu)
        bus.open()
        client = UdsClient(
            IsoTpSocket(bus, tx_id=pair.request_id, rx_id=pair.response_id, is_extended=True)
        )
        self.assertEqual(client.read_data_by_identifier(0xF111), b"cluster-config-block")


if __name__ == "__main__":
    unittest.main()
