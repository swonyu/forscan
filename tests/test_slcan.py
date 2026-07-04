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
from fordscope.isotp import IsoTpSocket
from fordscope.obd import ObdClient


class ScriptedSlcanPort:
    """A fake CANable adapter for END-TO-END reads: S/O/C setup commands are silent,
    and after each CAN frame (``t``/``T``) is written it emits the next queued slcan
    response block (LAWICEL line format). Drives a real SlcanTransport -> IsoTpSocket
    -> ObdClient stack with no hardware. A ``\\r``-joined block models the adapter
    returning several frames (e.g. consecutive frames) in one read."""

    def __init__(self, response_blocks) -> None:
        self._blocks = list(response_blocks)
        self._armed = None

    def write(self, data: bytes) -> int:
        text = bytes(data).decode("ascii", "ignore").strip()
        if text and text[0] in "tTrR" and self._blocks:  # a CAN frame, not an S/O/C cmd
            self._armed = self._blocks.pop(0)
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if self._armed is not None:
            block, self._armed = self._armed, None
            return (block + "\r").encode("ascii")
        return b""

    def close(self) -> None:
        pass


class FakeSerial:
    """A minimal duck-typed serial port: records writes, replays fed bytes."""

    def __init__(self, rx: bytes = b"") -> None:
        self.written = bytearray()
        self._rx = bytearray(rx)
        self.closed = False

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def read(self, size: int = 1) -> bytes:
        chunk = bytes(self._rx[:size])
        del self._rx[:size]
        return chunk

    def feed(self, data: bytes) -> None:
        self._rx.extend(data)

    def close(self) -> None:
        self.closed = True


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

    def test_oversized_dlc_returns_none_not_crash(self):
        # DLC 9 exceeds the classic-CAN max of 8. Per the docstring this must
        # return None (so recv can skip it), NOT raise out of the receive loop.
        self.assertIsNone(parse_frame(b"t7DF9010203040506070809"))

    def test_out_of_range_11bit_id_returns_none_not_crash(self):
        # A 't' line whose 3-hex ID exceeds the 11-bit max (0x7FF) is malformed;
        # it must be skipped (None), not raised out of the receive loop.
        self.assertIsNone(parse_frame(b"tFFF3010203"))

    def test_out_of_range_29bit_id_returns_none_not_crash(self):
        # A 'T' line whose 8-hex ID exceeds the 29-bit max (0x1FFFFFFF).
        self.assertIsNone(parse_frame(b"TFFFFFFFF3010203"))

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

    def test_close_closes_the_underlying_port(self):
        # close() must release the owned serial fd, not leave it to GC — else the
        # webapp leaks one fd per connect/disconnect cycle.
        port = FakeSerial()
        t = SlcanTransport(port)
        t.open()
        t.close()
        self.assertTrue(port.closed)

    def test_close_releases_fd_even_if_close_command_write_raises(self):
        # Adapter yanked mid-session: the CLOSE_COMMAND write raises OSError. close()
        # must still release the fd and flip is_open, not propagate and leak.
        class _CloseWriteRaises(FakeSerial):
            def write(self, data):
                if bytes(data) == b"C\r":  # CLOSE_COMMAND
                    raise OSError("device not configured")
                return super().write(data)

        port = _CloseWriteRaises()
        t = SlcanTransport(port)
        t.open()
        t.close()  # must not propagate
        self.assertTrue(port.closed)
        self.assertFalse(t.is_open)

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

    def test_recv_skips_oversized_line_and_returns_next_frame(self):
        port = FakeSerial()
        t = SlcanTransport(port)
        t.open()
        # A corrupted oversized line, then a valid frame — recv must not crash.
        port.feed(b"t7DF9010203040506070809\rt7E84410C0FA0\r")
        frame = t.recv()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.arbitration_id, 0x7E8)


class SlcanEndToEndReadTests(unittest.TestCase):
    """The slcan (CANable) real-adapter path proven as an INTEGRATED read: scripted
    slcan lines -> SlcanTransport parse -> IsoTpSocket reassembly -> ObdClient decode
    -> a correct value. Mirrors the elm327 end-to-end tests so BOTH shipped real
    backends have their full-stack composition covered, not just per-layer units."""

    def _obd(self, response_blocks):
        t = SlcanTransport(ScriptedSlcanPort(response_blocks))
        t.open()
        return ObdClient(IsoTpSocket(t, tx_id=0x7E0, rx_id=0x7E8))

    def test_single_frame_read_rpm_end_to_end(self):
        # SF reply to Mode 01 PID 0C: id 7E8, dlc 8, [04 41 0C 0F A0 00 00 00].
        obd = self._obd(["t7E8804410C0FA0000000"])
        r = obd.current_data(0x0C)
        self.assertEqual((r.name, r.value, r.unit), ("Engine RPM", 1000.0, "rpm"))

    def test_multiframe_vin_read_end_to_end(self):
        # Multiframe VIN: the client's flow-control frame goes DOWN through slcan send
        # and the consecutive frames come UP through slcan recv. FF (49 02 01 '1F M')
        # then CF1 'HK8D89A' + CF2 'BA12345'. All frames dlc 8.
        obd = self._obd([
            "t7E88101449020131464D",
            "t7E8821484B3844383941\rt7E882242413132333435",
        ])
        self.assertEqual(obd.read_vin(), "1FMHK8D89ABA12345")


if __name__ == "__main__":
    unittest.main()
