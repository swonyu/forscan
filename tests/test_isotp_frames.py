"""ISO-TP frame codec tests. Fixtures hand-derived from ISO 15765-2 byte formats.

Worked example bytes are written out explicitly so a reviewer can check them
against the spec, not against the implementation.
"""
import unittest

from fordscope.isotp.frames import (
    IsoTpFrameType,
    FlowStatus,
    encode_single_frame,
    encode_first_frame,
    encode_consecutive_frame,
    encode_flow_control,
    parse_isotp,
    pci_type,
    SF_MAX_DATA,
    FF_FIRST_DATA,
    ISOTP_MAX_CLASSIC_LEN,
)


class SingleFrameTests(unittest.TestCase):
    def test_encode_obd_rpm_request(self):
        # Service 0x01, PID 0x0C -> 2 data bytes -> SF length 2.
        out = encode_single_frame(bytes([0x01, 0x0C]))
        self.assertEqual(out, bytes([0x02, 0x01, 0x0C, 0, 0, 0, 0, 0]))

    def test_encode_no_padding(self):
        out = encode_single_frame(bytes([0xAA]), pad_to_8=False)
        self.assertEqual(out, bytes([0x01, 0xAA]))

    def test_encode_max_seven_bytes(self):
        out = encode_single_frame(bytes(range(1, 8)))  # 7 bytes
        self.assertEqual(out[0], 0x07)
        self.assertEqual(len(out), 8)

    def test_encode_rejects_empty_and_oversized(self):
        with self.assertRaises(ValueError):
            encode_single_frame(b"")
        with self.assertRaises(ValueError):
            encode_single_frame(bytes(SF_MAX_DATA + 1))

    def test_parse_roundtrip(self):
        pci = parse_isotp(encode_single_frame(bytes([0x01, 0x0C])))
        self.assertIs(pci.type, IsoTpFrameType.SINGLE)
        self.assertEqual(pci.length, 2)
        self.assertEqual(pci.data, bytes([0x01, 0x0C]))

    def test_parse_rejects_sf_length_zero(self):
        with self.assertRaises(ValueError):
            parse_isotp(bytes([0x00, 0, 0, 0, 0, 0, 0, 0]))


class FirstFrameTests(unittest.TestCase):
    def test_encode_length_split_across_nibble_and_byte(self):
        # total 0x123 (291): b0 = 0x11, b1 = 0x23.
        first = bytes([0x62, 0xF1, 0x90, 0x31, 0x32, 0x33])
        out = encode_first_frame(0x123, first)
        self.assertEqual(out[0], 0x11)
        self.assertEqual(out[1], 0x23)
        self.assertEqual(out[2:8], first)

    def test_encode_small_multiframe(self):
        first = bytes([0x62, 0xF1, 0x90, 0x31, 0x32, 0x33])
        out = encode_first_frame(10, first)
        self.assertEqual(out, bytes([0x10, 0x0A]) + first)

    def test_encode_requires_exactly_six_data_bytes(self):
        with self.assertRaises(ValueError):
            encode_first_frame(10, bytes(5))
        with self.assertRaises(ValueError):
            encode_first_frame(10, bytes(7))

    def test_encode_rejects_out_of_range_total_length(self):
        with self.assertRaises(ValueError):
            encode_first_frame(SF_MAX_DATA, bytes(FF_FIRST_DATA))  # too short for FF
        with self.assertRaises(ValueError):
            encode_first_frame(ISOTP_MAX_CLASSIC_LEN + 1, bytes(FF_FIRST_DATA))

    def test_parse_roundtrip(self):
        first = bytes([0x62, 0xF1, 0x90, 0x31, 0x32, 0x33])
        pci = parse_isotp(encode_first_frame(0x123, first))
        self.assertIs(pci.type, IsoTpFrameType.FIRST)
        self.assertEqual(pci.length, 0x123)
        self.assertEqual(pci.data, first)

    def test_parse_rejects_ff_total_below_multiframe_minimum(self):
        # FF declaring total=3: lengths 1-7 must be Single Frames (ISO 15765-2).
        # The encoder enforces this; the parser must too (else a bit-flipped SF is
        # silently accepted as a bogus multi-frame message).
        with self.assertRaises(ValueError):
            parse_isotp(bytes([0x10, 0x03, 0, 0, 0, 0, 0, 0]))

    def test_parse_accepts_ff_at_minimum_length(self):
        pci = parse_isotp(bytes([0x10, 0x08, 1, 2, 3, 4, 5, 6]))  # total 8 = minimum
        self.assertIs(pci.type, IsoTpFrameType.FIRST)
        self.assertEqual(pci.length, 8)

    def test_parse_rejects_truncated_ff_short_first_data(self):
        # A First Frame must carry the full 6 first-data bytes; a short FF payload
        # is malformed and must be rejected (mirroring SF's truncation guard), not
        # silently accepted with fewer bytes than the wire shape requires.
        with self.assertRaises(ValueError):
            parse_isotp(bytes([0x10, 0x0A, 0xAA]))  # total 10 (valid) but only 1 data byte


class ConsecutiveFrameTests(unittest.TestCase):
    def test_encode_sequence_and_data(self):
        out = encode_consecutive_frame(1, bytes([0x34, 0x35, 0x36, 0x37]))
        self.assertEqual(out[0], 0x21)
        self.assertEqual(out[1:5], bytes([0x34, 0x35, 0x36, 0x37]))
        self.assertEqual(len(out), 8)

    def test_sequence_number_wraps_visually_at_15(self):
        self.assertEqual(encode_consecutive_frame(15, b"\x00")[0], 0x2F)
        self.assertEqual(encode_consecutive_frame(0, b"\x00")[0], 0x20)

    def test_encode_rejects_bad_sequence_or_empty_data(self):
        with self.assertRaises(ValueError):
            encode_consecutive_frame(16, b"\x00")
        with self.assertRaises(ValueError):
            encode_consecutive_frame(1, b"")

    def test_parse_roundtrip_keeps_padding_in_data(self):
        pci = parse_isotp(encode_consecutive_frame(3, bytes([0xAA, 0xBB])))
        self.assertIs(pci.type, IsoTpFrameType.CONSECUTIVE)
        self.assertEqual(pci.sequence_number, 3)
        # Padding stays; the reassembly layer trims to total length.
        self.assertEqual(pci.data[:2], bytes([0xAA, 0xBB]))
        self.assertEqual(len(pci.data), 7)


class FlowControlTests(unittest.TestCase):
    def test_encode_clear_to_send_default(self):
        out = encode_flow_control()
        self.assertEqual(out[:3], bytes([0x30, 0x00, 0x00]))

    def test_encode_with_block_size_and_stmin(self):
        out = encode_flow_control(FlowStatus.CONTINUE, block_size=8, stmin=0x14)
        self.assertEqual(out[:3], bytes([0x30, 0x08, 0x14]))

    def test_encode_wait_and_overflow_status(self):
        self.assertEqual(encode_flow_control(FlowStatus.WAIT)[0], 0x31)
        self.assertEqual(encode_flow_control(FlowStatus.OVERFLOW)[0], 0x32)

    def test_parse_roundtrip(self):
        pci = parse_isotp(encode_flow_control(FlowStatus.CONTINUE, 8, 0x14))
        self.assertIs(pci.type, IsoTpFrameType.FLOW_CONTROL)
        self.assertEqual(pci.flow_status, FlowStatus.CONTINUE)
        self.assertEqual(pci.block_size, 8)
        self.assertEqual(pci.stmin, 0x14)


class PciTypeTests(unittest.TestCase):
    def test_classifies_each_type(self):
        self.assertIs(pci_type(bytes([0x02, 0x01, 0x0C])), IsoTpFrameType.SINGLE)
        self.assertIs(pci_type(bytes([0x10, 0x0A])), IsoTpFrameType.FIRST)
        self.assertIs(pci_type(bytes([0x21, 0x00])), IsoTpFrameType.CONSECUTIVE)
        self.assertIs(pci_type(bytes([0x30, 0x00, 0x00])), IsoTpFrameType.FLOW_CONTROL)

    def test_empty_payload_raises(self):
        with self.assertRaises(ValueError):
            pci_type(b"")


if __name__ == "__main__":
    unittest.main()
