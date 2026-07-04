"""Named As-Built feature tests — mechanism + the honesty caveat on example data."""
import unittest

from fordscope.transport import SimulatorTransport
from fordscope.isotp import IsoTpSocket, SimulatedIsoTpEcu
from fordscope.uds import UdsClient, SimulatedUdsEcu
from fordscope.ford import (
    AsBuiltBlock,
    parse_block,
    compute_checksum,
    AsBuiltCoder,
    InMemoryBackupStore,
    FeatureDefinition,
    FeatureCoder,
    EXAMPLE_FEATURES,
)

# A test feature at a known location: high nibble of byte 2, off=0 / on=4.
FEATURE = FeatureDefinition(
    key="test_feat", name="Test feature", module="BCM",
    did=0x5200, label="726-01-01", byte_index=2, nibble="high",
    options={"off": 0x0, "on": 0x4}, note="test",
)
DID = 0x5200


def block_with_high_nibble(byte2_high: int) -> bytes:
    data = bytes([0x00, 0x00, byte2_high << 4])
    return data + bytes([compute_checksum(data)])


class FeatureDefinitionTests(unittest.TestCase):
    def test_current_option_reads_nibble(self):
        block = parse_block("726-01-01", block_with_high_nibble(0x4))
        self.assertEqual(FEATURE.current_option(block), "on")
        block_off = parse_block("726-01-01", block_with_high_nibble(0x0))
        self.assertEqual(FEATURE.current_option(block_off), "off")

    def test_current_option_none_when_unmapped(self):
        block = parse_block("726-01-01", block_with_high_nibble(0x9))  # no option = 9
        self.assertIsNone(FEATURE.current_option(block))

    def test_apply_sets_value_and_keeps_valid(self):
        block = parse_block("726-01-01", block_with_high_nibble(0x0))
        applied = FEATURE.apply(block, "on")
        self.assertEqual((applied.data[2] >> 4) & 0x0F, 0x4)
        self.assertTrue(applied.is_valid)

    def test_read_value_rejects_out_of_range_byte_index(self):
        # A negative byte_index silently read the WRONG byte and returned it as the
        # feature's value (audit finding #5). It must raise, not fabricate a value.
        block = parse_block("726-01-01", block_with_high_nibble(0x4))
        bad = FeatureDefinition(
            key="bad", name="Bad", module="BCM", did=DID, label="726-01-01",
            byte_index=-1, nibble=None, options={"x": 0x00},
        )
        with self.assertRaises(IndexError):
            bad._read_value(block)

    def test_apply_unknown_option_raises(self):
        block = parse_block("726-01-01", block_with_high_nibble(0x0))
        with self.assertRaises(KeyError):
            FEATURE.apply(block, "maybe")


class FeatureCoderTests(unittest.TestCase):
    def _coder(self, raw):
        ecu = SimulatedUdsEcu(dids={DID: raw})
        isotp_ecu = SimulatedIsoTpEcu(ecu, request_id=0x726, response_id=0x72E)
        bus = SimulatorTransport(isotp_ecu)
        bus.open()
        client = UdsClient(IsoTpSocket(bus, tx_id=0x726, rx_id=0x72E))
        coder = AsBuiltCoder(client, InMemoryBackupStore(), scope="VIN")
        return FeatureCoder(coder, {"test_feat": FEATURE}), ecu

    def test_read_feature_reports_current(self):
        fc, _ = self._coder(block_with_high_nibble(0x0))
        _def, current = fc.read_feature("test_feat")
        self.assertEqual(current, "off")

    def test_set_feature_applies_safely_and_is_restorable(self):
        original = block_with_high_nibble(0x0)
        fc, ecu = self._coder(original)
        fc.set_feature("test_feat", "on")  # backup -> write -> verify
        _def, current = fc.read_feature("test_feat")
        self.assertEqual(current, "on")
        # backup captured -> restorable to the original off state
        fc.coder.restore_block(DID)
        self.assertEqual(ecu.dids[DID], original)

    def test_unknown_feature_raises(self):
        fc, _ = self._coder(block_with_high_nibble(0x0))
        with self.assertRaises(KeyError):
            fc.set_feature("nope", "on")


class ExampleFeatureHonestyTests(unittest.TestCase):
    def test_every_example_feature_is_flagged_unverified(self):
        # Guard against silently shipping example mappings as if authoritative.
        self.assertTrue(EXAMPLE_FEATURES)
        for key, feat in EXAMPLE_FEATURES.items():
            self.assertIn("UNVERIFIED", feat.note, f"{key} must be flagged unverified")


if __name__ == "__main__":
    unittest.main()
