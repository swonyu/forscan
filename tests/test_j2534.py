"""J2534 (PassThru) raw-CAN wire-codec tests.

Every expected value is hand-derived from SAE J2534-1: the raw-CAN ``PASSTHRU_MSG``
``Data`` field is the 4-byte BIG-ENDIAN arbitration ID followed by the payload, and
the ``CAN_29BIT_ID`` (0x100) bit in ``TxFlags``/``RxStatus`` marks a 29-bit extended
ID. The real ``PassThru*`` C entry points (a vendor .dylib over ctypes) are out of
scope here and are [NEEDS ON-CAR CHECK]; only the pure marshalling is proven.
"""
import unittest

from fordscope.transport import (
    CanFrame,
    encode_can_message,
    parse_can_message,
    can_baudrate,
    PROTOCOL_CAN,
    CAN_29BIT_ID,
)


class SpecConstantTests(unittest.TestCase):
    """Pin the two J2534-1 constants the codec depends on to their spec values."""

    def test_protocol_id_for_raw_can_is_5(self):
        self.assertEqual(PROTOCOL_CAN, 5)

    def test_can_29bit_flag_is_0x100(self):
        self.assertEqual(CAN_29BIT_ID, 0x00000100)


class EncodeTests(unittest.TestCase):
    def test_standard_frame(self):
        # ID 0x7DF as 4 big-endian bytes 00 00 07 DF, then payload 02 01 0C.
        # Standard ID => TxFlags has no CAN_29BIT_ID bit => 0.
        tx_flags, data = encode_can_message(CanFrame(0x7DF, bytes([0x02, 0x01, 0x0C])))
        self.assertEqual(tx_flags, 0)
        self.assertEqual(data, bytes.fromhex("000007DF02010C"))

    def test_extended_frame(self):
        # ID 0x18DAF110 as 4 big-endian bytes 18 DA F1 10, then payload 22 F1 90.
        # Extended ID => TxFlags carries CAN_29BIT_ID (0x100).
        tx_flags, data = encode_can_message(
            CanFrame(0x18DAF110, bytes([0x22, 0xF1, 0x90]), is_extended=True)
        )
        self.assertEqual(tx_flags, 0x100)
        self.assertEqual(data, bytes.fromhex("18DAF11022F190"))

    def test_empty_data(self):
        # No payload => Data is just the 4-byte big-endian ID (DataSize would be 4).
        tx_flags, data = encode_can_message(CanFrame(0x123))
        self.assertEqual(tx_flags, 0)
        self.assertEqual(data, bytes.fromhex("00000123"))

    def test_flag_not_id_bytes_distinguishes_extended(self):
        # The SAME numeric ID 0x123 encodes to IDENTICAL 4-byte Data whether standard
        # or extended; only the CAN_29BIT_ID flag differs. This is the crux of J2534's
        # id-width handling and the reason parse takes width from RxStatus, not size.
        std_flags, std_data = encode_can_message(CanFrame(0x123))
        ext_flags, ext_data = encode_can_message(CanFrame(0x123, is_extended=True))
        self.assertEqual(std_data, ext_data)              # identical ID bytes
        self.assertEqual((std_flags, ext_flags), (0, 0x100))  # only the flag differs


class ParseTests(unittest.TestCase):
    def test_standard(self):
        # 00 00 07 E8 (ID 0x7E8) + 41 0C 0F A0; RxStatus 0 => standard.
        frame = parse_can_message(bytes.fromhex("000007E8410C0FA0"), rx_status=0)
        self.assertEqual(frame.arbitration_id, 0x7E8)
        self.assertEqual(frame.data, bytes([0x41, 0x0C, 0x0F, 0xA0]))
        self.assertFalse(frame.is_extended)

    def test_extended(self):
        # 18 DA F1 10 (ID 0x18DAF110) + 22 F1 90; RxStatus has CAN_29BIT_ID => extended.
        frame = parse_can_message(
            bytes.fromhex("18DAF11022F190"), rx_status=CAN_29BIT_ID
        )
        self.assertEqual(frame.arbitration_id, 0x18DAF110)
        self.assertEqual(frame.data, bytes([0x22, 0xF1, 0x90]))
        self.assertTrue(frame.is_extended)

    def test_extended_flag_beats_id_magnitude(self):
        # A small ID (0x123) with the 29-bit RxStatus flag set MUST parse as extended,
        # proving width comes from the flag, not from the ID being > 0x7FF.
        frame = parse_can_message(bytes.fromhex("00000123"), rx_status=CAN_29BIT_ID)
        self.assertEqual(frame.arbitration_id, 0x123)
        self.assertTrue(frame.is_extended)

    def test_runt_shorter_than_id_returns_none_not_crash(self):
        # Fewer than the 4 mandatory ID bytes is malformed -> None (skippable).
        self.assertIsNone(parse_can_message(bytes.fromhex("000007"), rx_status=0))

    def test_payload_boundary_8_ok_9_none(self):
        # Classic CAN carries at most 8 payload bytes. 8 must parse; 9 must be skipped
        # (None), not crash -- a genuine straddle of the 8-byte limit.
        eight = parse_can_message(bytes.fromhex("000007E8") + bytes(8), rx_status=0)
        self.assertIsNotNone(eight)
        self.assertEqual(len(eight.data), 8)
        nine = parse_can_message(bytes.fromhex("000007E8") + bytes(9), rx_status=0)
        self.assertIsNone(nine)

    def test_11bit_id_boundary_7ff_ok_800_none(self):
        # Standard frame: 0x7FF is the 11-bit max (ok); 0x800 exceeds it (None).
        ok = parse_can_message((0x7FF).to_bytes(4, "big"), rx_status=0)
        self.assertIsNotNone(ok)
        self.assertEqual(ok.arbitration_id, 0x7FF)
        self.assertIsNone(parse_can_message((0x800).to_bytes(4, "big"), rx_status=0))

    def test_29bit_id_boundary_max_ok_over_none(self):
        # Extended frame: 0x1FFFFFFF is the 29-bit max (ok); 0x20000000 exceeds (None).
        ok = parse_can_message((0x1FFFFFFF).to_bytes(4, "big"), rx_status=CAN_29BIT_ID)
        self.assertIsNotNone(ok)
        self.assertEqual(ok.arbitration_id, 0x1FFFFFFF)
        self.assertIsNone(
            parse_can_message((0x20000000).to_bytes(4, "big"), rx_status=CAN_29BIT_ID)
        )

    def test_roundtrip_std_and_ext(self):
        # encode -> parse (feeding TxFlags back as RxStatus) must restore the frame,
        # for both a standard and an extended identifier.
        for f in (
            CanFrame(0x7DF, bytes([0x02, 0x01, 0x0C])),
            CanFrame(0x18DAF110, bytes([0x22, 0xF1, 0x90]), is_extended=True),
        ):
            tx_flags, data = encode_can_message(f)
            self.assertEqual(parse_can_message(data, rx_status=tx_flags), f)


class BaudrateTests(unittest.TestCase):
    def test_ford_baudrates(self):
        self.assertEqual(can_baudrate(500), 500_000)  # HS-CAN
        self.assertEqual(can_baudrate(125), 125_000)  # MS-CAN

    def test_unsupported_baudrate(self):
        with self.assertRaises(ValueError):
            can_baudrate(333)


if __name__ == "__main__":
    unittest.main()
