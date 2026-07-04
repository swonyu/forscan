"""Live-data logging tests — deterministic via an injected clock, no real sleeping."""
import os
import tempfile
import unittest

from fordscope.transport import SimulatorTransport
from fordscope.isotp import IsoTpSocket, SimulatedIsoTpEcu, IsoTpError
from fordscope.obd import SimulatedObdEcu, ObdClient
from fordscope.services import DataLogger, rows_to_csv, write_csv_file, column_header


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1.0
        return self.t


def make_client(pids):
    ecu = SimulatedObdEcu(pids=pids)
    isotp_ecu = SimulatedIsoTpEcu(ecu, request_id=0x7E0, response_id=0x7E8)
    bus = SimulatorTransport(isotp_ecu)
    bus.open()
    return ObdClient(IsoTpSocket(bus, tx_id=0x7E0, rx_id=0x7E8))


class DataLoggerTests(unittest.TestCase):
    def test_logs_requested_pids(self):
        client = make_client({0x0C: bytes([0x0F, 0xA0]), 0x05: bytes([90])})
        logger = DataLogger(client, [0x0C, 0x05], clock=_Clock(), sleep=lambda s: None)
        rows = logger.run(3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].values[0x0C].value, 1000.0)
        self.assertEqual(rows[0].values[0x05].value, 50)

    def test_clock_advances_between_samples(self):
        client = make_client({0x0C: bytes([0x0F, 0xA0])})
        rows = DataLogger(client, [0x0C], clock=_Clock(), sleep=lambda s: None).run(2)
        self.assertNotEqual(rows[0].t, rows[1].t)

    def test_unsupported_pid_logs_blank(self):
        client = make_client({0x0C: bytes([0x0F, 0xA0])})
        row = DataLogger(client, [0x0C, 0x99]).sample()
        self.assertIsNotNone(row.values[0x0C])
        self.assertIsNone(row.values[0x99])

    def test_interval_zero_never_sleeps(self):
        client = make_client({0x0C: bytes([0x0F, 0xA0])})
        calls = []
        DataLogger(client, [0x0C], sleep=lambda s: calls.append(s)).run(3, interval=0.0)
        self.assertEqual(calls, [])


class CsvTests(unittest.TestCase):
    def test_column_header_named_and_fallback(self):
        self.assertEqual(column_header(0x0C), "Engine RPM (rpm)")
        self.assertEqual(column_header(0x99), "PID_99")

    def test_rows_to_csv_header_and_values(self):
        client = make_client({0x0C: bytes([0x0F, 0xA0]), 0x05: bytes([90])})
        rows = DataLogger(client, [0x0C, 0x05], clock=_Clock(), sleep=lambda s: None).run(2)
        text = rows_to_csv(rows, [0x0C, 0x05])
        self.assertIn("Engine RPM (rpm)", text)
        self.assertIn("Engine coolant temperature (degC)", text)
        self.assertIn("1000.0", text)
        self.assertIn("50", text)

    def test_blank_cell_for_unsupported(self):
        client = make_client({0x0C: bytes([0x0F, 0xA0])})
        rows = DataLogger(client, [0x0C, 0x99], clock=_Clock(), sleep=lambda s: None).run(1)
        lines = rows_to_csv(rows, [0x0C, 0x99]).strip().splitlines()
        self.assertTrue(lines[1].endswith(","))  # trailing empty cell for PID 0x99

    def test_write_csv_file(self):
        client = make_client({0x0C: bytes([0x0F, 0xA0])})
        rows = DataLogger(client, [0x0C], clock=_Clock(), sleep=lambda s: None).run(2)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.csv")
            write_csv_file(rows, [0x0C], path)
            with open(path) as fh:
                content = fh.read()
            self.assertIn("Engine RPM (rpm)", content)
            self.assertIn("1000.0", content)


class NoisyBusTests(unittest.TestCase):
    def test_sample_blanks_pid_on_malformed_frame_not_aborts(self):
        # Bus NOISE -> a malformed ISO-TP frame -> IsoTpError during a read. That must
        # blank that cell (like an unsupported PID), NOT abort the whole sample/log.
        # IsoTpError is a different hierarchy than ObdError, so it was slipping past the
        # DataLogger's per-PID catch (sibling of the iter-115 controller fix).
        class NoisyClient:
            def current_data(self, pid):
                raise IsoTpError("malformed ISO-TP frame: bus noise")

        logger = DataLogger(NoisyClient(), [0x0C, 0x05])
        row = logger.sample()  # must NOT raise
        self.assertIsNone(row.values[0x0C])
        self.assertIsNone(row.values[0x05])


if __name__ == "__main__":
    unittest.main()
