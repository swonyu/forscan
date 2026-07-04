"""Tier 0 — transport layer: CanFrame validation + SimulatorTransport behaviour.

Fixtures are hand-derived from the classic-CAN and OBD-II byte formats, not from
the code under test (see docs/DESIGN.md §6).
"""
import unittest

from fordscope.transport.base import (
    CanFrame,
    Transport,
    TransportNotOpen,
    CAN_MAX_CLASSIC_DLC,
)
from fordscope.transport.simulator import (
    SimulatorTransport,
    null_responder,
    echo_responder,
    canned_obd_responder,
)


class CanFrameTests(unittest.TestCase):
    def test_valid_standard_frame(self):
        f = CanFrame(0x7DF, bytes([0x02, 0x01, 0x0C]))
        self.assertEqual(f.arbitration_id, 0x7DF)
        self.assertFalse(f.is_extended)
        self.assertEqual(len(f.data), 3)

    def test_rejects_oversized_payload(self):
        with self.assertRaises(ValueError):
            CanFrame(0x100, bytes(CAN_MAX_CLASSIC_DLC + 1))

    def test_rejects_negative_id(self):
        with self.assertRaises(ValueError):
            CanFrame(-1)

    def test_rejects_id_over_11bit_when_standard(self):
        with self.assertRaises(ValueError):
            CanFrame(0x800, is_extended=False)

    def test_allows_29bit_id_when_extended(self):
        # 0x18DAF110 is a typical Ford enhanced physical-response ID.
        f = CanFrame(0x18DAF110, is_extended=True)
        self.assertTrue(f.is_extended)
        self.assertEqual(f.arbitration_id, 0x18DAF110)

    def test_rejects_id_over_29bit_even_when_extended(self):
        with self.assertRaises(ValueError):
            CanFrame(0x1FFFFFFF + 1, is_extended=True)

    def test_rejects_non_bytes_payload(self):
        with self.assertRaises(TypeError):
            CanFrame(0x100, data=[1, 2, 3])  # type: ignore[arg-type]

    def test_frozen_and_hashable(self):
        f = CanFrame(0x123, b"\x01")
        _ = {f}  # hashable -> can live in a set
        with self.assertRaises(Exception):
            f.arbitration_id = 5  # type: ignore[misc]  # frozen


class SimulatorLifecycleTests(unittest.TestCase):
    def test_is_a_transport(self):
        self.assertIsInstance(SimulatorTransport(), Transport)

    def test_send_before_open_raises(self):
        t = SimulatorTransport()
        with self.assertRaises(TransportNotOpen):
            t.send(CanFrame(0x7DF))

    def test_recv_before_open_raises(self):
        t = SimulatorTransport()
        with self.assertRaises(TransportNotOpen):
            t.recv()

    def test_context_manager_opens_and_closes(self):
        t = SimulatorTransport()
        self.assertFalse(t.is_open)
        with t as conn:
            self.assertTrue(conn.is_open)
        self.assertFalse(t.is_open)

    def test_close_clears_pending_rx(self):
        t = SimulatorTransport(echo_responder)
        t.open()
        t.send(CanFrame(0x7E0, b"\x01"))
        t.close()
        t.open()
        self.assertIsNone(t.recv())  # queue was cleared on close


class SimulatorResponderTests(unittest.TestCase):
    def test_null_responder_is_a_silent_bus(self):
        with SimulatorTransport(null_responder) as t:
            t.send(CanFrame(0x7DF, bytes([0x02, 0x01, 0x0C])))
            self.assertIsNone(t.recv())

    def test_echo_responder_offsets_id_by_8_and_mirrors_payload(self):
        with SimulatorTransport(echo_responder) as t:
            t.send(CanFrame(0x7E0, b"\xde\xad"))
            reply = t.recv()
            self.assertIsNotNone(reply)
            assert reply is not None
            self.assertEqual(reply.arbitration_id, 0x7E8)
            self.assertEqual(reply.data, b"\xde\xad")

    def test_canned_obd_rpm_decodes_to_1000(self):
        with SimulatorTransport(canned_obd_responder) as t:
            t.send(CanFrame(0x7DF, bytes([0x02, 0x01, 0x0C, 0, 0, 0, 0, 0])))
            reply = t.recv()
            self.assertIsNotNone(reply)
            assert reply is not None
            self.assertEqual(reply.arbitration_id, 0x7E8)
            self.assertEqual(reply.data[1], 0x41)  # 0x01 + 0x40 = positive response
            self.assertEqual(reply.data[2], 0x0C)  # echoed PID
            a, b = reply.data[3], reply.data[4]
            rpm = ((a * 256) + b) / 4
            self.assertEqual(rpm, 1000)

    def test_canned_obd_ignores_a_different_pid(self):
        with SimulatorTransport(canned_obd_responder) as t:
            # PID 0x05 = coolant temp, not stubbed -> silent.
            t.send(CanFrame(0x7DF, bytes([0x02, 0x01, 0x05, 0, 0, 0, 0, 0])))
            self.assertIsNone(t.recv())

    def test_multiple_replies_queue_in_order(self):
        def two_reply_responder(frame):
            return (CanFrame(0x7E8, b"\x01"), CanFrame(0x7E9, b"\x02"))

        with SimulatorTransport(two_reply_responder) as t:
            t.send(CanFrame(0x7DF, b"\x00"))
            first = t.recv()
            second = t.recv()
            assert first is not None and second is not None
            self.assertEqual(first.arbitration_id, 0x7E8)
            self.assertEqual(second.arbitration_id, 0x7E9)
            self.assertIsNone(t.recv())

    def test_sent_frames_are_recorded(self):
        with SimulatorTransport() as t:
            f = CanFrame(0x7DF, b"\x01")
            t.send(f)
            self.assertEqual(t.sent, [f])


if __name__ == "__main__":
    unittest.main()
