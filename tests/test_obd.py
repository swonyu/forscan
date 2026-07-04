"""OBD-II tests: PID/DTC decoders (pure) + ObdClient over the simulated stack.

Decoder fixtures are hand-derived from SAE J1979 scaling formulas.
"""
import unittest

from fordscope.transport import SimulatorTransport
from fordscope.isotp import IsoTpSocket, SimulatedIsoTpEcu
from fordscope.obd import (
    decode_pid,
    decode_dtc,
    encode_dtc,
    decode_dtcs,
    decode_supported_pids,
    decode_monitor_status,
    ObdClient,
    ObdNegativeResponse,
    SimulatedObdEcu,
)

# OBD-II CAN functional request address; responses come from 0x7E8.
REQ_ID = 0x7DF
RESP_ID = 0x7E8
VIN = "1FMHK8D89ABA12345"  # 17 chars -> multi-frame Mode 09 response


def make_obd(**ecu_kwargs):
    ecu = SimulatedObdEcu(**ecu_kwargs)
    isotp_ecu = SimulatedIsoTpEcu(ecu, request_id=REQ_ID, response_id=RESP_ID)
    bus = SimulatorTransport(isotp_ecu)
    bus.open()
    return ObdClient(IsoTpSocket(bus, tx_id=REQ_ID, rx_id=RESP_ID)), ecu


class PidDecodeTests(unittest.TestCase):
    def test_rpm(self):
        r = decode_pid(0x0C, bytes([0x0F, 0xA0]))  # (0x0FA0)/4 = 1000
        self.assertEqual(r.value, 1000.0)
        self.assertEqual(r.unit, "rpm")

    def test_coolant_temp_offset(self):
        self.assertEqual(decode_pid(0x05, bytes([90])).value, 50)  # 90 - 40

    def test_throttle_percent(self):
        self.assertEqual(decode_pid(0x11, bytes([0xFF])).value, 100.0)

    def test_fuel_trim_zero_and_positive(self):
        self.assertEqual(decode_pid(0x06, bytes([128])).value, 0.0)
        self.assertEqual(decode_pid(0x06, bytes([192])).value, 50.0)

    def test_maf(self):
        self.assertEqual(decode_pid(0x10, bytes([0x01, 0x00])).value, 2.56)

    def test_timing_advance(self):
        self.assertEqual(decode_pid(0x0E, bytes([128])).value, 0.0)  # 128/2 - 64

    def test_unknown_pid_raises(self):
        with self.assertRaises(KeyError):
            decode_pid(0xEE, bytes([0]))


class ExtendedPidDecodeTests(unittest.TestCase):
    """Hand-derived from SAE J1979 for the added Mode 01 PIDs."""

    def test_run_time(self):
        r = decode_pid(0x1F, bytes([0x01, 0x00]))  # 256*1 + 0
        self.assertEqual(r.value, 256)
        self.assertEqual(r.unit, "s")

    def test_commanded_egr(self):
        self.assertEqual(decode_pid(0x2C, bytes([0xFF])).value, 100.0)

    def test_egr_error_signed(self):
        self.assertEqual(decode_pid(0x2D, bytes([128])).value, 0.0)
        self.assertEqual(decode_pid(0x2D, bytes([192])).value, 50.0)

    def test_oil_temp(self):
        self.assertEqual(decode_pid(0x5C, bytes([90])).value, 50)  # 90 - 40

    def test_equivalence_ratio(self):
        self.assertEqual(decode_pid(0x44, bytes([0x80, 0x00])).value, 1.0)  # 32768/32768

    def test_catalyst_temperature(self):
        self.assertEqual(decode_pid(0x3C, bytes([0x0F, 0xA0])).value, 360.0)  # 4000/10 - 40

    def test_absolute_load(self):
        self.assertEqual(decode_pid(0x43, bytes([0x00, 0xFF])).value, 100.0)  # 255*100/255

    def test_time_with_mil(self):
        self.assertEqual(decode_pid(0x4D, bytes([0x00, 0x0A])).value, 10)  # minutes

    def test_engine_fuel_rate(self):
        self.assertEqual(decode_pid(0x5E, bytes([0x00, 0x14])).value, 1.0)  # 20/20

    def test_warm_ups_count(self):
        self.assertEqual(decode_pid(0x30, bytes([0x05])).value, 5)

    def test_short_data_raises(self):
        with self.assertRaises(ValueError):
            decode_pid(0x0C, bytes([0x0F]))  # RPM needs 2 bytes


class MonitorStatusTests(unittest.TestCase):
    def test_ready_all_supported_complete(self):
        # A=00 MIL off/0 DTC; B=07 continuous supported+complete; C=01 catalyst
        # supported; D=00 catalyst complete.
        ms = decode_monitor_status(bytes([0x00, 0x07, 0x01, 0x00]))
        self.assertFalse(ms.mil_on)
        self.assertEqual(ms.dtc_count, 0)
        self.assertFalse(ms.compression_ignition)
        self.assertTrue(ms.monitors["Catalyst"]["supported"])
        self.assertTrue(ms.monitors["Catalyst"]["complete"])
        self.assertTrue(ms.ready)
        self.assertEqual(ms.not_ready, [])

    def test_incomplete_monitor_makes_not_ready(self):
        # A=81 MIL on/1 DTC; C=01 catalyst supported; D=01 catalyst INCOMPLETE.
        ms = decode_monitor_status(bytes([0x81, 0x07, 0x01, 0x01]))
        self.assertTrue(ms.mil_on)
        self.assertEqual(ms.dtc_count, 1)
        self.assertFalse(ms.monitors["Catalyst"]["complete"])
        self.assertEqual(ms.not_ready, ["Catalyst"])
        self.assertFalse(ms.ready)

    def test_compression_ignition_uses_diesel_monitor_names(self):
        ms = decode_monitor_status(bytes([0x00, 0x08, 0x01, 0x00]))  # B bit3 = compression
        self.assertTrue(ms.compression_ignition)
        self.assertIn("NMHC catalyst", ms.monitors)

    def test_short_data_raises(self):
        with self.assertRaises(ValueError):
            decode_monitor_status(bytes([0x00, 0x00]))

    def test_client_reads_monitor_status(self):
        client, _ = make_obd(pids={0x01: bytes([0x00, 0x07, 0x01, 0x00])})
        self.assertTrue(client.monitor_status().ready)


class FreezeFrameTests(unittest.TestCase):
    def test_freeze_frame_pid_values(self):
        client, _ = make_obd(freeze_frame={0x0C: bytes([0x0F, 0xA0]), 0x05: bytes([90])})
        self.assertEqual(client.freeze_frame(0x0C).value, 1000.0)  # frozen RPM
        self.assertEqual(client.freeze_frame(0x05).value, 50)       # frozen coolant

    def test_freeze_frame_dtc(self):
        client, _ = make_obd(freeze_dtc="P0143")
        self.assertEqual(client.freeze_frame_dtc(), "P0143")

    def test_no_freeze_frame_dtc_is_none(self):
        client, _ = make_obd()  # nothing frozen
        self.assertIsNone(client.freeze_frame_dtc())

    def test_freeze_frame_unsupported_pid_raises(self):
        client, _ = make_obd(freeze_frame={0x0C: bytes([0x0F, 0xA0])})
        with self.assertRaises(ObdNegativeResponse):
            client.freeze_frame(0x99)


class DtcCodecTests(unittest.TestCase):
    def test_decode_known(self):
        self.assertEqual(decode_dtc(0x01, 0x43), "P0143")

    def test_decode_all_letters(self):
        self.assertTrue(decode_dtc(0x00, 0x00).startswith("P"))
        self.assertTrue(decode_dtc(0x40, 0x00).startswith("C"))
        self.assertTrue(decode_dtc(0x80, 0x00).startswith("B"))
        self.assertTrue(decode_dtc(0xC0, 0x00).startswith("U"))

    def test_encode_roundtrip(self):
        for code in ("P0143", "C0196", "B1234", "U0100"):
            self.assertEqual(decode_dtc(*encode_dtc(code)), code)

    def test_encode_known_bytes(self):
        self.assertEqual(encode_dtc("P0143"), bytes([0x01, 0x43]))

    def test_encode_rejects_malformed(self):
        with self.assertRaises(ValueError):
            encode_dtc("X0143")
        with self.assertRaises(ValueError):
            encode_dtc("P143")

    def test_decode_dtcs_block_with_count(self):
        block = bytes([0x02, 0x01, 0x43, 0x01, 0x96])
        self.assertEqual(decode_dtcs(block), ["P0143", "P0196"])

    def test_decode_dtcs_empty(self):
        self.assertEqual(decode_dtcs(bytes([0x00])), [])


class SupportedPidsTests(unittest.TestCase):
    def test_decode_single_pids(self):
        # PID 0x01 = MSB (bit 31); mask 0x80000000.
        self.assertEqual(decode_supported_pids(0x00, bytes([0x80, 0x00, 0x00, 0x00])), [0x01])
        # PID 0x20 (continuation) = LSB (bit 0); mask 0x00000001.
        self.assertEqual(decode_supported_pids(0x00, bytes([0x00, 0x00, 0x00, 0x01])), [0x20])

    def test_decode_multiple_pids(self):
        # PIDs 0x05,0x0C,0x0D -> bits 27,20,19 -> 0x08180000.
        self.assertEqual(
            decode_supported_pids(0x00, bytes([0x08, 0x18, 0x00, 0x00])), [0x05, 0x0C, 0x0D]
        )

    def test_decode_rejects_short_mask(self):
        with self.assertRaises(ValueError):
            decode_supported_pids(0x00, bytes([0x00, 0x00]))

    def test_client_lists_supported(self):
        client, _ = make_obd(pids={0x0C: bytes([0x0F, 0xA0]), 0x05: bytes([90]), 0x0D: bytes([0x40])})
        self.assertEqual(client.supported_pids(), [0x05, 0x0C, 0x0D])

    def test_client_follows_continuation_to_next_range(self):
        # A PID in the 0x21-0x40 range forces the client to query PID 0x20 too.
        client, _ = make_obd(pids={0x05: bytes([90]), 0x2F: bytes([0xFF])})
        self.assertEqual(client.supported_pids(), [0x05, 0x20, 0x2F])


class ObdClientTests(unittest.TestCase):
    def test_current_data_rpm(self):
        client, _ = make_obd(pids={0x0C: bytes([0x0F, 0xA0])})
        r = client.current_data(0x0C)
        self.assertEqual(r.value, 1000.0)
        self.assertEqual(r.name, "Engine RPM")

    def test_current_data_coolant(self):
        client, _ = make_obd(pids={0x05: bytes([90])})
        self.assertEqual(client.current_data(0x05).value, 50)

    def test_unsupported_pid_negative_response(self):
        client, _ = make_obd(pids={0x0C: bytes([0x0F, 0xA0])})
        with self.assertRaises(ObdNegativeResponse) as ctx:
            client.current_data(0x99)
        self.assertEqual(ctx.exception.nrc, 0x31)

    def test_read_stored_dtcs(self):
        client, _ = make_obd(dtcs=["P0143", "P0196"])
        self.assertEqual(client.read_dtcs(), ["P0143", "P0196"])

    def test_read_no_dtcs(self):
        client, _ = make_obd(dtcs=[])
        self.assertEqual(client.read_dtcs(), [])

    def test_clear_dtcs(self):
        client, ecu = make_obd(dtcs=["P0143"])
        client.clear_dtcs()
        self.assertTrue(ecu.cleared)
        self.assertEqual(client.read_dtcs(), [])

    def test_pending_dtcs_mode_07(self):
        client, _ = make_obd(pending=["P0300"])
        self.assertEqual(client.read_dtcs(mode=0x07), ["P0300"])

    def test_read_vin_multiframe(self):
        client, _ = make_obd(vin=VIN)
        self.assertEqual(client.read_vin(), VIN)

    def test_read_calibration_ids(self):
        # Mode 09 InfoType 0x04 — the "which calibration am I on?" datapoint.
        client, _ = make_obd(calibration_ids=["JR3A-14C204-BF"])
        self.assertEqual(client.read_calibration_ids(), ["JR3A-14C204-BF"])

    def test_read_multiple_calibration_ids(self):
        # Several modules/calibrations come back as several 16-byte items.
        client, _ = make_obd(calibration_ids=["CAL-ONE-A", "CAL-TWO-B"])
        self.assertEqual(client.read_calibration_ids(), ["CAL-ONE-A", "CAL-TWO-B"])

    def test_over_long_calibration_seed_stays_one_wire_width_item(self):
        # A fixture that over-fills the 16-byte CALID field must still be emitted
        # as ONE valid fixed-width item, not mis-split into several by the decoder.
        client, _ = make_obd(calibration_ids=["THIS-CALID-IS-WAY-TOO-LONG-FOR-16"])
        result = client.read_calibration_ids()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "THIS-CALID-IS-WA")  # first 16 chars

    def test_read_cvns_as_hex(self):
        # Mode 09 InfoType 0x06 — 4-byte verification number, surfaced as hex.
        client, _ = make_obd(cvns=[bytes([0xA5, 0xB3, 0xC1, 0xD2])])
        self.assertEqual(client.read_cvns(), ["A5B3C1D2"])

    def test_read_ecu_names(self):
        # Mode 09 InfoType 0x0A — 20-byte ASCII ECU name.
        client, _ = make_obd(ecu_names=["ECM-EngineControl"])
        self.assertEqual(client.read_ecu_names(), ["ECM-EngineControl"])

    def test_calibration_id_unsupported_raises(self):
        client, _ = make_obd()  # no calibration data seeded
        with self.assertRaises(ObdNegativeResponse):
            client.read_calibration_ids()

    def test_invalid_dtc_mode_rejected_client_side(self):
        client, _ = make_obd()
        with self.assertRaises(ValueError):
            client.read_dtcs(mode=0x01)


if __name__ == "__main__":
    unittest.main()
