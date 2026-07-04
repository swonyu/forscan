"""ELM327 transport tests — parser + command builder + sequencing over a fake port.

Response-line fixtures are hand-written in the ELM327 headers-on / spaces-on format.
Live-device behavior (timing, prompts, 29-bit, multi-frame FC) is NEEDS ON-CAR CHECK.
"""
import unittest

from fordscope.transport import (
    CanFrame,
    Transport,
    TransportNotOpen,
    Elm327Transport,
    header_command,
    payload_line,
    parse_response_line,
)


class FakeSerial:
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


class CommandBuilderTests(unittest.TestCase):
    def test_header_command_11bit(self):
        self.assertEqual(header_command(0x7E0), b"ATSH7E0\r")

    def test_header_command_29bit(self):
        self.assertEqual(header_command(0x18DAF110, is_extended=True), b"ATSH18DAF110\r")

    def test_payload_line(self):
        self.assertEqual(payload_line(bytes([0x02, 0x01, 0x0C])), b"02010C\r")


class ParseResponseTests(unittest.TestCase):
    def test_11bit_line(self):
        # A full 8-byte CAN frame: header 7E8, then 8 data bytes.
        frame = parse_response_line("7E8 06 41 0C 0F A0 00 00 00")
        self.assertEqual(frame.arbitration_id, 0x7E8)
        self.assertEqual(frame.data, bytes([0x06, 0x41, 0x0C, 0x0F, 0xA0, 0x00, 0x00, 0x00]))
        self.assertFalse(frame.is_extended)

    def test_29bit_line(self):
        frame = parse_response_line("18 DA F1 10 06 62 F1 90 31 32", is_extended=True)
        self.assertEqual(frame.arbitration_id, 0x18DAF110)
        self.assertEqual(frame.data, bytes([0x06, 0x62, 0xF1, 0x90, 0x31, 0x32]))
        self.assertTrue(frame.is_extended)

    def test_status_and_prompt_lines_are_ignored(self):
        for junk in ("SEARCHING...", "NO DATA", "?", "OK", "", ">", "UNABLE TO CONNECT"):
            self.assertIsNone(parse_response_line(junk), junk)

    def test_prompt_stripped_from_data_line(self):
        frame = parse_response_line("7E8 41 0D 20 >")
        self.assertIsNotNone(frame)
        self.assertEqual(frame.arbitration_id, 0x7E8)


class TransportTests(unittest.TestCase):
    def test_is_a_transport(self):
        self.assertIsInstance(Elm327Transport(FakeSerial()), Transport)

    def test_open_writes_init_sequence(self):
        port = FakeSerial()
        Elm327Transport(port, protocol="6").open()
        written = bytes(port.written)
        for expected in (b"ATZ\r", b"ATE0\r", b"ATH1\r", b"ATCAF0\r", b"ATSP6\r"):
            self.assertIn(expected, written)

    def test_send_sets_header_then_payload(self):
        port = FakeSerial()
        t = Elm327Transport(port)
        t.open()
        port.written.clear()
        t.send(CanFrame(0x7E0, bytes([0x02, 0x01, 0x0C])))
        written = bytes(port.written)
        self.assertIn(b"ATSH7E0\r", written)
        self.assertIn(b"02010C\r", written)
        self.assertLess(written.index(b"ATSH7E0\r"), written.index(b"02010C\r"))

    def test_header_only_set_once_for_same_id(self):
        port = FakeSerial()
        t = Elm327Transport(port)
        t.open()
        port.written.clear()
        t.send(CanFrame(0x7E0, bytes([0x01])))
        t.send(CanFrame(0x7E0, bytes([0x02])))
        self.assertEqual(bytes(port.written).count(b"ATSH7E0\r"), 1)

    def test_send_before_open_raises(self):
        with self.assertRaises(TransportNotOpen):
            Elm327Transport(FakeSerial()).send(CanFrame(0x7E0))

    def test_recv_parses_fed_response(self):
        port = FakeSerial()
        t = Elm327Transport(port)
        t.open()
        port.feed(b"7E8 06 41 0C 0F A0 00 00\r>")
        frame = t.recv()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.arbitration_id, 0x7E8)
        self.assertEqual(frame.data[1:3], bytes([0x41, 0x0C]))

    def test_recv_no_data_returns_none(self):
        port = FakeSerial()
        t = Elm327Transport(port)
        t.open()
        port.feed(b"NO DATA\r>")
        self.assertIsNone(t.recv())


if __name__ == "__main__":
    unittest.main()
