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
from fordscope.isotp import IsoTpSocket
from fordscope.obd import ObdClient, ObdError
from fordscope.uds import UdsClient
from fordscope.ford import extended_module


class ScriptedElmPort:
    """A fake vLinker-FS adapter for END-TO-END reads: it returns a ``>`` prompt to
    every ``AT`` command, and after each pure-hex (OBD/ISO-TP) payload it emits the
    next queued ELM327 response block (headers-on / spaces-on format). This lets a
    real Elm327Transport -> IsoTpSocket -> ObdClient stack run against scripted
    adapter output, with no hardware. Multi-line blocks (``\\r``-joined) model an
    adapter returning several CAN frames (e.g. consecutive frames) in one read."""

    def __init__(self, response_blocks) -> None:
        self._blocks = list(response_blocks)
        self._armed = None

    def write(self, data: bytes) -> int:
        text = bytes(data).decode("ascii", "ignore").strip()
        if text and not text.upper().startswith("AT") and self._blocks:
            self._armed = self._blocks.pop(0)  # a non-AT payload arms the next reply
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if self._armed is not None:
            block, self._armed = self._armed, None
            return (block + "\r>").encode("ascii")
        return b">"

    def close(self) -> None:
        pass


class FakeSerial:
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

    def test_oversized_data_returns_none_not_crash(self):
        # More than 8 data bytes after the header must return None (skippable),
        # not raise out of the receive loop.
        self.assertIsNone(parse_response_line("7E8 06 41 00 00 00 00 00 00 00 00"))

    def test_out_of_range_11bit_id_returns_none_not_crash(self):
        # A header token above the 11-bit max (0x7FF) is malformed; skip (None),
        # don't raise out of the receive loop.
        self.assertIsNone(parse_response_line("FFF 41 0C 0F A0"))

    def test_out_of_range_29bit_id_returns_none_not_crash(self):
        # A 29-bit header above 0x1FFFFFFF must be skipped, not crash.
        self.assertIsNone(parse_response_line("FF FF FF FF 06 62 F1 90", is_extended=True))


class TransportTests(unittest.TestCase):
    def test_is_a_transport(self):
        self.assertIsInstance(Elm327Transport(FakeSerial()), Transport)

    def test_close_closes_the_underlying_port(self):
        # close() must release the owned serial fd, not leave it to GC — else the
        # webapp leaks one fd per connect/disconnect cycle.
        port = FakeSerial()
        t = Elm327Transport(port)
        t.open()
        t.close()
        self.assertTrue(port.closed)

    def test_open_writes_init_sequence(self):
        port = FakeSerial()
        Elm327Transport(port, protocol="6").open()
        written = bytes(port.written)
        for expected in (b"ATZ\r", b"ATE0\r", b"ATH1\r", b"ATCAF0\r", b"ATSP6\r"):
            self.assertIn(expected, written)

    def test_open_survives_realistic_clone_adapter_quirks(self):
        # A real ELM327 clone's init is noisy: ATZ returns a version banner, a command
        # can echo before ATE0 takes effect, protocol detection emits "SEARCHING...".
        # open() must consume all of it (each _read_until_prompt reads to the '>' prompt)
        # and must NOT leak the version-string noise as a fake CAN frame. (Live TIMING is
        # NEEDS ON-CAR CHECK; this pins the codec's robustness to the wire CONTENT.)
        class QuirkyPort:
            def __init__(self):
                self._q = [
                    b"\r\rELM327 v1.5\r\r>",   # ATZ -> version banner
                    b"ATE0\rOK\r>",           # echo before ATE0 takes effect, then OK
                    b"OK\r>", b"OK\r>", b"OK\r>", b"OK\r>",  # ATL0/ATS1/ATH1/ATCAF0
                    b"SEARCHING...\rOK\r>",   # ATSP -> protocol search
                ]

            def write(self, data):
                return len(data)

            def read(self, n=1):
                return self._q.pop(0) if self._q else b">"

            def close(self):
                pass

        t = Elm327Transport(QuirkyPort())
        t.open()
        self.assertTrue(t.is_open)
        self.assertIsNone(t.recv())  # version-string / SEARCHING noise must not become a frame

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

    def test_recv_skips_oversized_line_and_returns_next_frame(self):
        port = FakeSerial()
        t = Elm327Transport(port)
        t.open()
        # Oversized (11-token) corrupt line, then a valid one — must not crash.
        port.feed(b"7E8 06 41 00 00 00 00 00 00 00 00\r7E8 06 41 0C 0F A0 00 00 00\r>")
        frame = t.recv()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.arbitration_id, 0x7E8)
        self.assertEqual(len(frame.data), 8)


class Elm327EndToEndReadTests(unittest.TestCase):
    """The real-adapter path proven as an INTEGRATED read, not just per-layer units:
    scripted ELM327 lines -> Elm327Transport parse -> IsoTpSocket reassembly ->
    ObdClient decode -> a correct value. Each layer was unit-tested in isolation;
    nothing exercised their composition through the real wire codec until here."""

    def _obd(self, response_blocks):
        t = Elm327Transport(ScriptedElmPort(response_blocks))
        t.open()
        return ObdClient(IsoTpSocket(t, tx_id=0x7E0, rx_id=0x7E8))

    def test_single_frame_read_rpm_end_to_end(self):
        # ECU single-frame reply to Mode 01 PID 0C: PCI 04, [41 0C 0F A0], padded.
        obd = self._obd(["7E8 04 41 0C 0F A0 00 00 00"])
        r = obd.current_data(0x0C)
        self.assertEqual((r.name, r.value, r.unit), ("Engine RPM", 1000.0, "rpm"))

    def test_multiframe_vin_read_end_to_end(self):
        # Multiframe VIN exercises the HARDER integration: the client's flow-control
        # frame goes DOWN through elm327 send, and the consecutive frames come UP
        # through elm327 recv. FF (49 02 01 '1F M') then CF1 'HK8D89A' + CF2 'BA12345'.
        obd = self._obd([
            "7E8 10 14 49 02 01 31 46 4D",
            "7E8 21 48 4B 38 44 38 39 41\r7E8 22 42 41 31 32 33 34 35",
        ])
        self.assertEqual(obd.read_vin(), "1FMHK8D89ABA12345")

    def test_no_data_surfaces_clean_error_not_a_hang(self):
        # The #1 real-world event on a live car: query an unsupported PID and the
        # adapter replies "NO DATA". The full stack (elm327 recognizes the status
        # line -> None -> ISO-TP None -> ObdClient) must surface a clean ObdError so
        # the GUI can say "no response" -- never hang or crash on the first drive.
        obd = self._obd(["NO DATA"])
        with self.assertRaises(ObdError) as ctx:
            obd.current_data(0x0C)
        self.assertIn("no response", str(ctx.exception))

    def test_extended_29bit_uds_read_end_to_end(self):
        # Ford ENHANCED diagnostics (the As-Built half of the tool) use 29-bit
        # addressing (0x18DA{TA}{SA}) -- a DISTINCT elm327 code path (the 4-token
        # extended header parse) and extended ISO-TP framing, never composed
        # end-to-end before (every prior integration test was 11-bit). A UDS
        # ReadDataByIdentifier over the REAL extended_module() pair must decode
        # through the whole extended stack. (elm327 only: it is the owner's vLinker
        # FS and carries the trickier multi-token header parse; slcan's extended
        # form is a simpler single 8-hex token, already unit-tested.)
        pair = extended_module(0x10, name="PCM-ext")
        self.assertTrue(pair.is_extended)
        self.assertEqual((pair.request_id, pair.response_id), (0x18DA10F1, 0x18DAF110))
        t = Elm327Transport(
            ScriptedElmPort(["18 DA F1 10 06 62 F1 90 31 32 33 00"]), protocol="7"
        )
        t.open()
        uds = UdsClient(IsoTpSocket(
            t, tx_id=pair.request_id, rx_id=pair.response_id, is_extended=pair.is_extended
        ))
        self.assertEqual(uds.read_data_by_identifier(0xF190), b"123")


if __name__ == "__main__":
    unittest.main()
