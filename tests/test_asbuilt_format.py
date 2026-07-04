"""As-Built block format: parse, checksum, edit, and coder integration."""
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
)

LABEL = "726-01-01"
DID = 0x5100


class ChecksumTests(unittest.TestCase):
    def test_sum_to_zero(self):
        # sum(0x01,0x02,0x03)=6 -> checksum 0xFA, and (6 + 0xFA) & 0xFF == 0.
        self.assertEqual(compute_checksum(bytes([0x01, 0x02, 0x03])), 0xFA)
        self.assertEqual((0x01 + 0x02 + 0x03 + 0xFA) & 0xFF, 0)

    def test_empty_data_checksum_zero(self):
        self.assertEqual(compute_checksum(b""), 0)


class BlockTests(unittest.TestCase):
    def test_parse_splits_data_and_checksum(self):
        block = parse_block(LABEL, bytes([0x12, 0x34, 0x56, 0x64]))
        self.assertEqual(block.data, bytes([0x12, 0x34, 0x56]))
        self.assertEqual(block.checksum, 0x64)

    def test_is_valid_true_and_false(self):
        good = parse_block(LABEL, bytes([0x01, 0x02, 0x03, 0xFA]))
        self.assertTrue(good.is_valid)
        bad = parse_block(LABEL, bytes([0x01, 0x02, 0x03, 0x00]))
        self.assertFalse(bad.is_valid)

    def test_parse_rejects_empty(self):
        with self.assertRaises(ValueError):
            parse_block(LABEL, b"")

    def test_with_data_recomputes_checksum(self):
        block = AsBuiltBlock(LABEL, bytes([0x00]), 0x00).with_data(bytes([0x10, 0x20]))
        self.assertTrue(block.is_valid)

    def test_set_byte_keeps_block_valid(self):
        block = parse_block(LABEL, bytes([0x01, 0x02, 0x03, 0xFA]))
        edited = block.set_byte(0, 0xAB)
        self.assertEqual(edited.data[0], 0xAB)
        self.assertTrue(edited.is_valid)

    def test_set_byte_out_of_range(self):
        block = parse_block(LABEL, bytes([0x01, 0xFF]))
        with self.assertRaises(IndexError):
            block.set_byte(5, 0x00)

    def test_set_nibble_high_and_low(self):
        block = parse_block(LABEL, bytes([0x00, 0x00]))  # data [0x00], cksum 0x00
        hi = block.set_nibble(0, high=True, value=0xA)
        self.assertEqual(hi.data[0], 0xA0)
        lo = hi.set_nibble(0, high=False, value=0x5)
        self.assertEqual(lo.data[0], 0xA5)
        self.assertTrue(lo.is_valid)

    def test_nibble_value_validated(self):
        block = parse_block(LABEL, bytes([0x00, 0x00]))
        with self.assertRaises(ValueError):
            block.set_nibble(0, high=True, value=0x10)

    def test_to_bytes_roundtrips_through_parse(self):
        block = parse_block(LABEL, bytes([0x12, 0x34, 0x56, 0x64]))
        self.assertEqual(parse_block(LABEL, block.to_bytes()), block)

    def test_format_shows_label_and_bad_checksum(self):
        good = parse_block(LABEL, bytes([0x01, 0x02, 0x03, 0xFA]))
        self.assertIn("726-01-01", good.format())
        self.assertNotIn("BAD", good.format())
        bad = parse_block(LABEL, bytes([0x01, 0x02, 0x03, 0x00]))
        self.assertIn("BAD CHECKSUM", bad.format())


class CoderIntegrationTests(unittest.TestCase):
    def _coder(self, raw_block: bytes):
        ecu = SimulatedUdsEcu(dids={DID: raw_block})
        isotp_ecu = SimulatedIsoTpEcu(ecu, request_id=0x726, response_id=0x72E)
        bus = SimulatorTransport(isotp_ecu)
        bus.open()
        client = UdsClient(IsoTpSocket(bus, tx_id=0x726, rx_id=0x72E))
        return AsBuiltCoder(client, InMemoryBackupStore(), scope="VIN"), ecu

    def test_read_as_built_parses_block(self):
        coder, _ = self._coder(bytes([0x12, 0x34, 0x56, 0x64]))
        block = coder.read_as_built(DID, LABEL)
        self.assertEqual(block.label, LABEL)
        self.assertEqual(block.data, bytes([0x12, 0x34, 0x56]))

    def test_code_as_built_writes_edited_block_safely(self):
        original_raw = bytes([0x12, 0x34, 0x56, compute_checksum(bytes([0x12, 0x34, 0x56]))])
        coder, ecu = self._coder(original_raw)
        block = coder.read_as_built(DID, LABEL).set_byte(0, 0xAB)
        coder.code_as_built(DID, block)  # backup -> write -> verify
        # ECU now holds the edited block (data + fresh checksum).
        self.assertEqual(ecu.dids[DID], block.to_bytes())
        # ...and the original is restorable.
        coder.restore_block(DID)
        self.assertEqual(ecu.dids[DID], original_raw)


if __name__ == "__main__":
    unittest.main()
