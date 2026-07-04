"""UDS bidirectional controls: InputOutputControl (0x2F) + RoutineControl (0x31)."""
import unittest

from fordscope.transport import SimulatorTransport
from fordscope.isotp import IsoTpSocket, SimulatedIsoTpEcu
from fordscope.uds import UdsClient, SimulatedUdsEcu, NegativeResponseError
from fordscope.uds import services as S

REQ_ID = 0x7E0
RESP_ID = 0x7E8
IO_DID = 0x1234           # e.g. an actuator control identifier
ROUTINE_ID = 0x0203       # e.g. a self-test routine


def make_uds(**ecu_kwargs):
    ecu = SimulatedUdsEcu(**ecu_kwargs)
    isotp_ecu = SimulatedIsoTpEcu(ecu, request_id=REQ_ID, response_id=RESP_ID)
    bus = SimulatorTransport(isotp_ecu)
    bus.open()
    return UdsClient(IsoTpSocket(bus, tx_id=REQ_ID, rx_id=RESP_ID)), ecu


class IoControlTests(unittest.TestCase):
    def test_short_term_adjustment_sets_state(self):
        client, ecu = make_uds(io_dids={IO_DID})
        status = client.io_control(IO_DID, S.IO_SHORT_TERM_ADJUSTMENT, b"\x01")
        self.assertEqual(status, b"\x01")
        self.assertEqual(ecu.io_state[IO_DID], b"\x01")

    def test_return_control_to_ecu_clears_state(self):
        client, ecu = make_uds(io_dids={IO_DID})
        client.io_control(IO_DID, S.IO_SHORT_TERM_ADJUSTMENT, b"\x01")
        client.io_control(IO_DID, S.IO_RETURN_CONTROL_TO_ECU)
        self.assertNotIn(IO_DID, ecu.io_state)

    def test_unsupported_io_did_rejected(self):
        client, _ = make_uds(io_dids={IO_DID})
        with self.assertRaises(NegativeResponseError) as ctx:
            client.io_control(0x9999, S.IO_SHORT_TERM_ADJUSTMENT, b"\x01")
        self.assertEqual(ctx.exception.nrc, S.NRC_REQUEST_OUT_OF_RANGE)


class RoutineControlTests(unittest.TestCase):
    def test_start_then_request_results(self):
        client, ecu = make_uds(routines={ROUTINE_ID: b"\x00\x2A"})
        client.start_routine(ROUTINE_ID)
        self.assertIn(ROUTINE_ID, ecu.routines_started)
        results = client.request_routine_results(ROUTINE_ID)
        self.assertEqual(results, b"\x00\x2A")

    def test_results_before_start_is_sequence_error(self):
        client, _ = make_uds(routines={ROUTINE_ID: b"\x00"})
        with self.assertRaises(NegativeResponseError) as ctx:
            client.request_routine_results(ROUTINE_ID)
        self.assertEqual(ctx.exception.nrc, S.NRC_REQUEST_SEQUENCE_ERROR)

    def test_stop_routine(self):
        client, ecu = make_uds(routines={ROUTINE_ID: b"\x00"})
        client.start_routine(ROUTINE_ID)
        client.stop_routine(ROUTINE_ID)
        self.assertNotIn(ROUTINE_ID, ecu.routines_started)

    def test_unsupported_routine_rejected(self):
        client, _ = make_uds(routines={ROUTINE_ID: b"\x00"})
        with self.assertRaises(NegativeResponseError) as ctx:
            client.start_routine(0xBEEF)
        self.assertEqual(ctx.exception.nrc, S.NRC_REQUEST_OUT_OF_RANGE)


if __name__ == "__main__":
    unittest.main()
