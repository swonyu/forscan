"""UDS client tests — request/response over the full simulated stack.

Stack under test: UdsClient -> IsoTpSocket -> SimulatorTransport(SimulatedIsoTpEcu(
SimulatedUdsEcu)). Response bytes are hand-derived from ISO 14229 (positive =
SID+0x40; negative = 7F SID NRC).
"""
import unittest

from fordscope.transport import CanFrame, SimulatorTransport
from fordscope.isotp import (
    IsoTpSocket,
    IsoTpFrameType,
    SimulatedIsoTpEcu,
    parse_isotp,
    encode_single_frame,
)
from fordscope.uds import (
    UdsClient,
    SimulatedUdsEcu,
    NegativeResponseError,
    UnexpectedResponseError,
    nrc_name,
)
from fordscope.uds import services as S

REQ_ID = 0x7E0
RESP_ID = 0x7E8
VIN = b"1FMHK8D89ABA12345"  # 17 bytes -> forces a multi-frame response


def make_uds(dids=None):
    ecu = SimulatedUdsEcu(dids if dids is not None else {0xF190: VIN, 0xF188: b"AB12"})
    isotp_ecu = SimulatedIsoTpEcu(ecu, request_id=REQ_ID, response_id=RESP_ID)
    bus = SimulatorTransport(isotp_ecu)
    bus.open()
    client = UdsClient(IsoTpSocket(bus, tx_id=REQ_ID, rx_id=RESP_ID))
    return client, ecu


class NrcNameTests(unittest.TestCase):
    def test_known_codes(self):
        self.assertEqual(nrc_name(0x33), "securityAccessDenied")
        self.assertEqual(nrc_name(0x31), "requestOutOfRange")
        self.assertEqual(nrc_name(0x78), "requestCorrectlyReceived-ResponsePending")

    def test_unknown_code_is_labelled(self):
        self.assertIn("unknown", nrc_name(0xAB))


class ReadDataByIdentifierTests(unittest.TestCase):
    def test_reads_short_did(self):
        client, _ = make_uds()
        self.assertEqual(client.read_data_by_identifier(0xF188), b"AB12")

    def test_reads_multiframe_vin(self):
        client, _ = make_uds()
        self.assertEqual(client.read_data_by_identifier(0xF190), VIN)

    def test_unknown_did_raises_request_out_of_range(self):
        client, _ = make_uds()
        with self.assertRaises(NegativeResponseError) as ctx:
            client.read_data_by_identifier(0xDEAD)
        self.assertEqual(ctx.exception.nrc, S.NRC_REQUEST_OUT_OF_RANGE)
        self.assertEqual(ctx.exception.request_sid, S.READ_DATA_BY_IDENTIFIER)

    def test_did_range_validated_client_side(self):
        client, _ = make_uds()
        with self.assertRaises(ValueError):
            client.read_data_by_identifier(0x10000)


class WriteDataByIdentifierTests(unittest.TestCase):
    def test_write_then_read_roundtrip(self):
        client, ecu = make_uds()
        client.write_data_by_identifier(0xF188, b"ZZ99")
        self.assertEqual(ecu.dids[0xF188], b"ZZ99")
        self.assertEqual(client.read_data_by_identifier(0xF188), b"ZZ99")

    def test_write_long_value_multiframe_request(self):
        client, ecu = make_uds()
        payload = bytes(range(20))  # forces a multi-frame 0x2E request
        client.write_data_by_identifier(0xF190, payload)
        self.assertEqual(ecu.dids[0xF190], payload)


class SessionAndResetTests(unittest.TestCase):
    def test_session_control_switches_and_returns_timing(self):
        client, ecu = make_uds()
        resp = client.diagnostic_session_control(S.SESSION_EXTENDED)
        self.assertEqual(resp[0], 0x50)
        self.assertEqual(resp[1], S.SESSION_EXTENDED)
        self.assertEqual(len(resp), 6)  # includes P2/P2* timing
        self.assertEqual(ecu.session, S.SESSION_EXTENDED)

    def test_unsupported_session_raises_subfunction_not_supported(self):
        client, _ = make_uds()
        with self.assertRaises(NegativeResponseError) as ctx:
            client.diagnostic_session_control(0x09)
        self.assertEqual(ctx.exception.nrc, S.NRC_SUBFUNCTION_NOT_SUPPORTED)

    def test_ecu_reset(self):
        client, ecu = make_uds()
        resp = client.ecu_reset(S.RESET_HARD)
        self.assertEqual(resp, bytes([0x51, S.RESET_HARD]))
        self.assertEqual(ecu.last_reset, S.RESET_HARD)


class TesterPresentTests(unittest.TestCase):
    def test_suppressed_tester_present_expects_no_response(self):
        client, _ = make_uds()
        # Must not raise despite the ECU staying silent (suppress bit set).
        client.tester_present(suppress_response=True)

    def test_unsuppressed_tester_present_gets_response(self):
        client, _ = make_uds()
        client.tester_present(suppress_response=False)  # no exception

    def test_suppressed_tester_present_surfaces_negative_response(self):
        # The suppress bit suppresses only the POSITIVE response; a conformant ECU
        # still NRCs on error. A rejected keep-alive must raise, not be silently
        # believed to be keeping the session alive.
        sock = _RecordingSocket([bytes([0x7F, 0x3E, 0x7F])])  # serviceNotSupportedInActiveSession
        client = UdsClient(sock)
        with self.assertRaises(NegativeResponseError):
            client.tester_present(suppress_response=True)

    def test_suppressed_tester_present_ignores_response_pending(self):
        # 0x78 (responsePending) is NOT a rejection — the ECU is busy but the session
        # is alive. The keepalive probe must not tear a healthy session down.
        sock = _RecordingSocket([bytes([0x7F, 0x3E, 0x78])])
        client = UdsClient(sock)
        client.tester_present(suppress_response=True)  # must NOT raise


class UnsupportedServiceTests(unittest.TestCase):
    def test_unsupported_service_raises(self):
        client, _ = make_uds()
        with self.assertRaises(NegativeResponseError) as ctx:
            client.request(bytes([0x23, 0x00, 0x00, 0x00]))  # ReadMemoryByAddress, unhandled
        self.assertEqual(ctx.exception.nrc, S.NRC_SERVICE_NOT_SUPPORTED)

    def test_wrong_length_read_raises_length_nrc(self):
        client, _ = make_uds()
        with self.assertRaises(NegativeResponseError) as ctx:
            client.request(bytes([0x22, 0xF1]))  # too short for a DID
        self.assertEqual(ctx.exception.nrc, S.NRC_INCORRECT_LENGTH_OR_FORMAT)


class ResponsePendingTests(unittest.TestCase):
    def test_client_waits_through_response_pending(self):
        # ECU emits a 0x78 (responsePending) then the real positive response.
        class PendingThenOk:
            def __call__(self, frame):
                pci = parse_isotp(frame.data)
                if pci.type is IsoTpFrameType.SINGLE:
                    sid = pci.data[0]
                    pending = encode_single_frame(bytes([0x7F, sid, S.NRC_RESPONSE_PENDING]))
                    ok = encode_single_frame(bytes([sid + 0x40, 0x01, 0x02]))
                    return (CanFrame(RESP_ID, pending), CanFrame(RESP_ID, ok))
                return ()

        bus = SimulatorTransport(PendingThenOk())
        bus.open()
        client = UdsClient(IsoTpSocket(bus, tx_id=REQ_ID, rx_id=RESP_ID))
        resp = client.request(bytes([0x22, 0x01, 0x02]))
        self.assertEqual(resp, bytes([0x62, 0x01, 0x02]))

    def test_too_many_pending_gives_up(self):
        class AlwaysPending:
            def __call__(self, frame):
                pci = parse_isotp(frame.data)
                if pci.type is IsoTpFrameType.SINGLE:
                    sid = pci.data[0]
                    pending = encode_single_frame(bytes([0x7F, sid, S.NRC_RESPONSE_PENDING]))
                    # Flood pending frames so the client's bound is exceeded.
                    return tuple(CanFrame(RESP_ID, pending) for _ in range(10))
                return ()

        bus = SimulatorTransport(AlwaysPending())
        bus.open()
        client = UdsClient(IsoTpSocket(bus, tx_id=REQ_ID, rx_id=RESP_ID), max_response_pending=3)
        from fordscope.uds import UdsError
        with self.assertRaises(UdsError):
            client.request(bytes([0x22, 0x01, 0x02]))


class _RecordingSocket:
    """Minimal IsoTpSocket stand-in: scripts recv() responses and records the
    timeout each recv() was called with."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.recv_timeouts = []

    def send(self, payload):
        pass

    def recv(self, timeout=1.0):
        self.recv_timeouts.append(timeout)
        return self._responses.pop(0) if self._responses else None


class ResponsePendingTimeoutTests(unittest.TestCase):
    def test_response_pending_switches_to_p2_star_timeout(self):
        # ISO 14229: after requestCorrectlyReceived-ResponsePending (0x78) the ECU
        # may take up to P2* (long) — the client must wait that window, not the
        # short P2, or it aborts an operation the ECU is legitimately completing.
        sock = _RecordingSocket([
            bytes([0x7F, 0x22, 0x78]),   # responsePending
            bytes([0x62, 0xF1, 0x90]),   # positive RDBI response
        ])
        client = UdsClient(sock, p2_timeout=1.0, p2_star_timeout=5.0)
        resp = client.request(bytes([0x22, 0xF1, 0x90]))
        self.assertEqual(resp, bytes([0x62, 0xF1, 0x90]))
        # First recv on P2 (1.0); every recv AFTER a 0x78 on P2* (5.0).
        self.assertEqual(sock.recv_timeouts, [1.0, 5.0])

    def test_negative_response_wrong_sid_is_rejected(self):
        # ISO 14229 §7.5: a negative response [0x7F, SID, NRC] must echo the request
        # SID. A crossed-wire reply (SecurityAccess 0x27 error to a RDBI 0x22 request)
        # must be rejected as unexpected, not misattributed to the caller's request.
        sock = _RecordingSocket([bytes([0x7F, 0x27, 0x31])])
        client = UdsClient(sock)
        with self.assertRaises(UnexpectedResponseError):
            client.request(bytes([0x22, 0xF1, 0x90]))  # we sent RDBI (0x22)


if __name__ == "__main__":
    unittest.main()
