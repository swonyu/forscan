"""ISO-TP transport layer: segmentation, flow control, reassembly.

Round-trips run a real ``IsoTpSocket`` (client) against a ``SimulatedIsoTpEcu``
over the in-memory bus. Flow-control edge cases use hand-built responders so the
exact frames are visible to a reviewer.
"""
import unittest

from fordscope.transport import CanFrame, SimulatorTransport
from fordscope.isotp import (
    IsoTpSocket,
    SimulatedIsoTpEcu,
    IsoTpFrameType,
    FlowStatus,
    IsoTpError,
    IsoTpSequenceError,
    parse_isotp,
    encode_flow_control,
    stmin_to_seconds,
    FF_FIRST_DATA,
)

REQ_ID = 0x7E0
RESP_ID = 0x7E8


def make_pair(handler, **ecu_kwargs):
    ecu = SimulatedIsoTpEcu(handler, request_id=REQ_ID, response_id=RESP_ID, **ecu_kwargs)
    bus = SimulatorTransport(ecu)
    bus.open()
    sock = IsoTpSocket(bus, tx_id=REQ_ID, rx_id=RESP_ID)
    return sock, ecu, bus


def reassemble_client_frames(frames):
    """Rebuild the payload the client emitted (FF + CFs), trimming CF padding."""
    out = bytearray()
    total = None
    for f in frames:
        pci = parse_isotp(f.data)
        if pci.type is IsoTpFrameType.SINGLE:
            out.extend(pci.data)
        elif pci.type is IsoTpFrameType.FIRST:
            total = pci.length
            out.extend(pci.data[: min(FF_FIRST_DATA, total)])
        elif pci.type is IsoTpFrameType.CONSECUTIVE:
            out.extend(pci.data)
    return bytes(out[:total]) if total is not None else bytes(out)


def cf_sequence_numbers(frames):
    """The 4-bit sequence number of each CONSECUTIVE frame the client emitted."""
    return [
        parse_isotp(f.data).sequence_number
        for f in frames
        if parse_isotp(f.data).type is IsoTpFrameType.CONSECUTIVE
    ]


class StminTests(unittest.TestCase):
    def test_millisecond_range(self):
        self.assertEqual(stmin_to_seconds(0x00), 0.0)
        self.assertEqual(stmin_to_seconds(0x0A), 0.010)
        self.assertEqual(stmin_to_seconds(0x7F), 0.127)

    def test_microsecond_range(self):
        self.assertAlmostEqual(stmin_to_seconds(0xF1), 0.0001)
        self.assertAlmostEqual(stmin_to_seconds(0xF9), 0.0009)

    def test_reserved_values_clamp_to_max(self):
        self.assertEqual(stmin_to_seconds(0x80), 0.127)
        self.assertEqual(stmin_to_seconds(0xFF), 0.127)


class SendPathTests(unittest.TestCase):
    def test_single_frame_send(self):
        sock, _ecu, bus = make_pair(lambda req: None)
        sock.send(bytes([0x22, 0xF1, 0x90]))
        self.assertEqual(len(bus.sent), 1)
        self.assertEqual(bus.sent[0].data[0], 0x03)  # SF, length 3

    def test_rejects_empty_payload(self):
        sock, _ecu, _bus = make_pair(lambda req: None)
        with self.assertRaises(ValueError):
            sock.send(b"")

    def test_rejects_payload_over_classic_max(self):
        sock, _ecu, _bus = make_pair(lambda req: None)
        with self.assertRaises(Exception):
            sock.send(bytes(4096))

    def test_multiframe_send_with_block_size_two(self):
        # ECU that grants clear-to-send in blocks of 2 CFs, forcing multiple
        # flow-control rounds. Verifies the client honours block size.
        class BlockSizeTwoEcu:
            def __init__(self):
                self.cf_in_block = 0
                self.fcs_sent = 0

            def __call__(self, frame):
                pci = parse_isotp(frame.data)
                if pci.type is IsoTpFrameType.FIRST:
                    self.cf_in_block = 0
                    self.fcs_sent += 1
                    return (CanFrame(RESP_ID, encode_flow_control(FlowStatus.CONTINUE, 2, 0)),)
                if pci.type is IsoTpFrameType.CONSECUTIVE:
                    self.cf_in_block += 1
                    if self.cf_in_block == 2:
                        self.cf_in_block = 0
                        self.fcs_sent += 1
                        return (CanFrame(RESP_ID, encode_flow_control(FlowStatus.CONTINUE, 2, 0)),)
                return ()

        ecu = BlockSizeTwoEcu()
        bus = SimulatorTransport(ecu)
        bus.open()
        sock = IsoTpSocket(bus, tx_id=REQ_ID, rx_id=RESP_ID)
        payload = bytes(range(30))  # FF(6) + 24 -> 4 consecutive frames
        sock.send(payload)
        # The frames the client actually put on the bus reassemble to the payload.
        self.assertEqual(reassemble_client_frames(bus.sent), payload)
        # 1 FF + 4 CFs.
        self.assertEqual(len(bus.sent), 5)
        self.assertGreaterEqual(ecu.fcs_sent, 2)  # at least two flow-control rounds

    def test_reserved_flow_status_aborts_with_fs_error(self):
        # ISO 15765-2 §6.5.5.3: an FC frame with a reserved FlowStatus (0x3-0xF) is
        # an N_PCI error — abort with an FS error, don't silently treat it as WAIT.
        class ReservedFsEcu:
            def __call__(self, frame):
                if parse_isotp(frame.data).type is IsoTpFrameType.FIRST:
                    return (CanFrame(RESP_ID, bytes([0x35, 0x00, 0x00])),)  # FS nibble 5
                return ()

        bus = SimulatorTransport(ReservedFsEcu())
        bus.open()
        sock = IsoTpSocket(bus, tx_id=REQ_ID, rx_id=RESP_ID)
        with self.assertRaises(IsoTpError) as ctx:
            sock.send(bytes(range(20)))  # forces FF + FC
        self.assertIn("reserved", str(ctx.exception).lower())


class RoundTripTests(unittest.TestCase):
    def test_short_request_short_response(self):
        # UDS-style positive response: service byte | 0x40, echo the rest.
        sock, ecu, _bus = make_pair(lambda req: bytes([req[0] | 0x40]) + req[1:])
        sock.send(bytes([0x22, 0xF1, 0x90]))
        resp = sock.recv()
        self.assertEqual(resp, bytes([0x62, 0xF1, 0x90]))
        self.assertEqual(ecu.last_request, bytes([0x22, 0xF1, 0x90]))

    def test_short_request_long_response(self):
        long_resp = bytes([0x62, 0xF1, 0x90]) + bytes(range(17))  # 20 bytes
        sock, _ecu, _bus = make_pair(lambda req: long_resp)
        sock.send(bytes([0x22, 0xF1, 0x90]))
        self.assertEqual(sock.recv(), long_resp)

    def test_long_request_short_response(self):
        captured = {}

        def handler(req):
            captured["req"] = req
            return bytes([0x71, 0x01])  # short ack

        sock, ecu, _bus = make_pair(handler)
        long_req = bytes([0x2E, 0xF1, 0x90]) + bytes(range(17))  # 20 bytes
        sock.send(long_req)
        resp = sock.recv()
        self.assertEqual(resp, bytes([0x71, 0x01]))
        self.assertEqual(captured["req"], long_req)
        self.assertEqual(ecu.last_request, long_req)

    def test_long_request_long_response(self):
        long_resp = bytes([0x62]) + bytes(range(29))  # 30 bytes
        sock, _ecu, _bus = make_pair(lambda req: long_resp)
        long_req = bytes([0x2E]) + bytes(range(19))  # 20 bytes
        sock.send(long_req)
        self.assertEqual(sock.recv(), long_resp)

    def test_sequence_number_wraps_past_15_both_directions(self):
        # The 4-bit CF sequence number wraps 15 -> 0. That only happens on messages
        # longer than ~111 bytes (FF's 6 + 15 CFs x 7), and NOTHING else in the suite
        # crosses that boundary -- yet real Ford As-Built ReadDataByIdentifier blocks
        # and long DTC lists routinely do. Round-trip a long request (exercises the
        # send-side wrap in _stream_cfs) AND a long response (exercises the recv-side
        # wrap in _reassemble). A broken mask fails LOUDLY: send would call
        # encode_consecutive_frame(16, ...) -> ValueError; recv would raise
        # IsoTpSequenceError when its expected_sn (16) meets the on-wire SN (0).
        long_resp = bytes([0x62, 0xF1, 0x90]) + bytes(range(180))   # 183 B -> 26 CFs
        sock, _ecu, bus = make_pair(lambda req: long_resp)
        long_req = bytes([0x2E, 0xF1, 0x90]) + bytes(range(160))    # 163 B -> 23 CFs
        sock.send(long_req)
        # recv-side wrap: the long response reassembles byte-exact across 15 -> 0.
        self.assertEqual(sock.recv(), long_resp)
        # send-side wrap: emitted CF sequence numbers are exactly 1,2,...,15,0,1,...
        sns = cf_sequence_numbers(bus.sent)
        self.assertGreater(len(sns), 16, "payload must need >16 CFs to cross the wrap")
        self.assertEqual(sns, [(i + 1) & 0x0F for i in range(len(sns))])
        # and those frames still reassemble to the exact request that was sent.
        self.assertEqual(reassemble_client_frames(bus.sent), long_req)

    def test_recv_returns_none_on_silent_bus(self):
        sock, _ecu, _bus = make_pair(lambda req: None)
        # Nothing sent; no response queued.
        self.assertIsNone(sock.recv())


class FlowControlErrorTests(unittest.TestCase):
    def test_out_of_sequence_consecutive_frame_raises(self):
        # ECU sends FF then a CF with the wrong sequence number (2 instead of 1).
        class BadSequenceEcu:
            def __call__(self, frame):
                pci = parse_isotp(frame.data)
                if pci.type is IsoTpFrameType.SINGLE:
                    # Start a 14-byte response: FF carries 6, one CF carries the rest.
                    from fordscope.isotp import encode_first_frame
                    return (CanFrame(RESP_ID, encode_first_frame(14, bytes(range(6)))),)
                if pci.type is IsoTpFrameType.FLOW_CONTROL:
                    from fordscope.isotp import encode_consecutive_frame
                    # Wrong sequence number (2, expected 1) -> client rejects before
                    # length matters. CF carries a valid 7 bytes (8 is impossible).
                    return (CanFrame(RESP_ID, encode_consecutive_frame(2, bytes(range(7)))),)
                return ()

        bus = SimulatorTransport(BadSequenceEcu())
        bus.open()
        sock = IsoTpSocket(bus, tx_id=REQ_ID, rx_id=RESP_ID)
        sock.send(bytes([0x22, 0xF1, 0x90]))
        with self.assertRaises(IsoTpSequenceError):
            sock.recv()


class MalformedFrameTests(unittest.TestCase):
    def test_recv_wraps_malformed_frame_as_isotp_error(self):
        # A frame with an unknown PCI nibble (bus noise / cross-talk) must surface as
        # IsoTpError, not a bare ValueError — so the whole-car scan (which catches
        # IsoTpError) skips the glitching module and continues instead of aborting.
        class _Garbage:
            def __init__(self):
                self._open = True

            def open(self):
                self._open = True

            def close(self):
                self._open = False

            @property
            def is_open(self):
                return self._open

            def send(self, frame):
                pass

            def recv(self, timeout=1.0):
                return CanFrame(RESP_ID, bytes([0x40, 0, 0, 0, 0, 0, 0, 0]))  # PCI nibble 0x4

        sock = IsoTpSocket(_Garbage(), tx_id=REQ_ID, rx_id=RESP_ID)
        with self.assertRaises(IsoTpError):
            sock.recv()


if __name__ == "__main__":
    unittest.main()
