"""slcan transport tests — wire codec + transport sequencing over a fake port.

The codec is hand-derived from the LAWICEL/slcan line format. Real serial timing
is out of scope (NEEDS ON-CAR CHECK); a FakeSerial stands in for the port.
"""
import unittest

from fordscope.transport import (
    CanFrame,
    Transport,
    TransportNotOpen,
    SlcanTransport,
    encode_frame,
    parse_frame,
    bitrate_command,
)


class FakeSerial:
    """A minimal duck-typed serial port: records writes, replays fed bytes."""

    def __init__(self, rx: bytes = b"") -> None:
        self.written = bytearray()
        self._rx = bytearray(rx)

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def read(self, size: int = 1) -> bytes:
        chunk = bytes(self._rx[:size])
        del self._rx[:size]
        return chunk

    def feed(self, data: bytes) -> None:
        self._rx.extend(data)


class EncodeTests(unittest.TestCase):
    def test_standard_frame(self):
        f = CanFrame(0x7DF, bytes([0x02, 0x01, 0x0C]))
        self.assertEqual(encode_frame(f), b"t7DF302010C\r")

    def test_extended_frame(self):
        f = CanFrame(0x18DAF110, bytes([0x22, 0xF1, 0x90]), is_extended=True)
        self.assertEqual(encode_frame(f), b"T18DAF110322F190\r")

    def test_empty_data(self):
        self.assertEqual(encode_frame(CanFrame(0x123)), b"t1230\r")


class ParseTests(unittest.TestCase):
    def test_standard(self):
        frame = parse_frame(b"t7E84410C0FA0")
        self.assertEqual(frame.arbitration_id, 0x7E8)
        self.assertEqual(frame.data, bytes([0x41, 0x0C, 0x0F, 0xA0]))
        self.assertFalse(frame.is_extended)

    def test_extended(self):
        frame = parse_frame("T18DAF110322F190")
        self.assertEqual(frame.arbitration_id, 0x18DAF110)
        self.assertEqual(frame.data, bytes([0x22, 0xF1, 0x90]))
        self.assertTrue(frame.is_extended)

    def test_ignores_status_and_empty_lines(self):
        self.assertIsNone(parse_frame(b""))
        self.assertIsNone(parse_frame(b"z"))       # ack line
        self.assertIsNone(parse_frame(b"\x07"))    # bell/error
        self.assertIsNone(parse_frame(b"t7E"))     # truncated

    def test_roundtrip(self):
        for f in (
            CanFrame(0x7DF, bytes([0x02, 0x01, 0x0C])),
            CanFrame(0x18DAF110, bytes([0x22, 0xF1, 0x90]), is_extended=True),
        ):
            line = encode_frame(f).rstrip(b"\r")
            self.assertEqual(parse_frame(line), f)


class BitrateTests(unittest.TestCase):
    def test_ford_bitrates(self):
        self.assertEqual(bitrate_command(500), b"S6\r")  # HS-CAN
        self.assertEqual(bitrate_command(125), b"S4\r")  # MS-CAN

    def test_unsupported_bitrate(self):
        with self.assertRaises(ValueError):
            bitrate_command(333)


class TransportTests(unittest.TestCase):
    def test_is_a_transport(self):
        self.assertIsInstance(SlcanTransport(FakeSerial()), Transport)

    def test_open_sends_bitrate_then_open(self):
        port = FakeSerial()
        t = SlcanTransport(port, bitrate_kbps=500)
        t.open()
        self.assertEqual(bytes(port.written), b"S6\rO\r")
        self.assertTrue(t.is_open)

    def test_close_sends_close_command(self):
        port = FakeSerial()
        t = SlcanTransport(port)
        t.open()
        port.written.clear()
        t.close()
        self.assertEqual(bytes(port.written), b"C\r")
        self.assertFalse(t.is_open)

    def test_send_before_open_raises(self):
        with self.assertRaises(TransportNotOpen):
            SlcanTransport(FakeSerial()).send(CanFrame(0x7DF))

    def test_send_writes_encoded_frame(self):
        port = FakeSerial()
        t = SlcanTransport(port)
        t.open()
        port.written.clear()
        t.send(CanFrame(0x7DF, bytes([0x02, 0x01, 0x0C])))
        self.assertEqual(bytes(port.written), b"t7DF302010C\r")

    def test_recv_parses_a_fed_frame(self):
        port = FakeSerial()
        t = SlcanTransport(port)
        t.open()
        port.feed(b"t7E84410C0FA0\r")
        frame = t.recv()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.arbitration_id, 0x7E8)
        self.assertEqual(frame.data, bytes([0x41, 0x0C, 0x0F, 0xA0]))

    def test_recv_skips_status_line_then_returns_frame(self):
        port = FakeSerial()
        t = SlcanTransport(port)
        t.open()
        port.feed(b"z\rt7E84410C0FA0\r")  # ack line, then a real frame
        frame = t.recv()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.arbitration_id, 0x7E8)

    def test_recv_returns_none_when_no_data(self):
        t = SlcanTransport(FakeSerial())
        t.open()
        self.assertIsNone(t.recv())


if __name__ == "__main__":
    unittest.main()
