"""UDS ReadDTCInformation (0x19) + whole-car DTC aggregation."""
import unittest

from fordscope.transport import SimulatorTransport, CanFrame
from fordscope.isotp import (
    SimulatedIsoTpEcu,
    multiplex,
    parse_isotp,
    IsoTpFrameType,
    encode_first_frame,
)
from fordscope.uds import (
    UdsClient,
    SimulatedUdsEcu,
    UdsDtc,
    decode_dtc_records,
    encode_dtc_record,
    STATUS_CONFIRMED,
    STATUS_PENDING,
)
from fordscope.isotp import IsoTpSocket
from fordscope.ford import eleven_bit_module
from fordscope.services import (
    scan_vehicle_dtcs,
    total_dtc_count,
    format_dtc_report,
)

PCM = eleven_bit_module(0x7E0, name="PCM")
ABS = eleven_bit_module(0x760, name="ABS")
APIM_ABSENT = eleven_bit_module(0x7D0, name="APIM")


def uds_at(pair, **kw):
    return SimulatedIsoTpEcu(
        SimulatedUdsEcu(**kw), request_id=pair.request_id, response_id=pair.response_id
    )


class UdsDtcRecordTests(unittest.TestCase):
    def test_encode_decode_roundtrip(self):
        rec = encode_dtc_record("P0143", 0x00, STATUS_CONFIRMED)
        self.assertEqual(len(rec), 4)
        decoded = decode_dtc_records(rec)
        self.assertEqual(decoded[0].code, "P0143")
        self.assertTrue(decoded[0].confirmed)

    def test_status_flags(self):
        d = UdsDtc("P0300", 0x00, STATUS_PENDING)
        self.assertTrue(d.pending)
        self.assertFalse(d.confirmed)
        self.assertEqual(d.display, "P0300-00")


class ReadDtcInformationTests(unittest.TestCase):
    def _client(self, **kw):
        ecu = uds_at(PCM, **kw)
        bus = SimulatorTransport(ecu)
        bus.open()
        return UdsClient(IsoTpSocket(bus, tx_id=PCM.request_id, rx_id=PCM.response_id))

    def test_reads_all_dtcs(self):
        client = self._client(dtcs=[
            UdsDtc("P0143", 0x00, STATUS_CONFIRMED),
            UdsDtc("P0300", 0x00, STATUS_PENDING),
        ])
        codes = [d.code for d in client.read_dtc_information()]
        self.assertEqual(codes, ["P0143", "P0300"])

    def test_status_mask_filters(self):
        client = self._client(dtcs=[
            UdsDtc("P0143", 0x00, STATUS_CONFIRMED),  # 0x08
            UdsDtc("P0300", 0x00, STATUS_PENDING),    # 0x04
        ])
        confirmed_only = client.read_dtc_information(status_mask=STATUS_CONFIRMED)
        self.assertEqual([d.code for d in confirmed_only], ["P0143"])

    def test_no_dtcs(self):
        client = self._client(dtcs=[])
        self.assertEqual(client.read_dtc_information(), [])


class WholeCarDtcScanTests(unittest.TestCase):
    def setUp(self):
        pcm = uds_at(PCM, dtcs=[UdsDtc("P0143", 0x00, STATUS_CONFIRMED)])
        abs_mod = uds_at(ABS, dtcs=[])  # present, no codes
        self.bus = SimulatorTransport(multiplex(pcm, abs_mod))
        self.bus.open()

    def test_aggregates_across_modules(self):
        reports = scan_vehicle_dtcs(self.bus, [PCM, ABS, APIM_ABSENT], timeout=0.1)
        by_name = {r.name: r for r in reports}
        self.assertEqual([d.code for d in by_name["PCM"].dtcs], ["P0143"])
        self.assertTrue(by_name["ABS"].present)
        self.assertEqual(by_name["ABS"].dtcs, [])
        self.assertFalse(by_name["APIM"].present)
        self.assertEqual(total_dtc_count(reports), 1)

    def test_isotp_fault_marks_present_and_does_not_abort(self):
        def ff_then_silent(frame):
            if frame.arbitration_id != PCM.request_id:
                return ()
            if parse_isotp(frame.data).type is IsoTpFrameType.SINGLE:
                return (CanFrame(PCM.response_id, encode_first_frame(20, bytes(range(6)))),)
            return ()  # ignore FC -> client times out mid-multi-frame

        abs_mod = uds_at(ABS, dtcs=[])
        bus = SimulatorTransport(multiplex(ff_then_silent, abs_mod))
        bus.open()
        reports = {r.name: r for r in scan_vehicle_dtcs(bus, [PCM, ABS], timeout=0.02)}
        self.assertTrue(reports["PCM"].present)   # answered a FF -> present
        self.assertEqual(reports["PCM"].dtcs, [])
        self.assertTrue(reports["ABS"].present)   # scan continued, not aborted

    def test_report_includes_descriptions(self):
        reports = scan_vehicle_dtcs(self.bus, [PCM, ABS, APIM_ABSENT], timeout=0.1)
        report = format_dtc_report(reports)
        self.assertIn("PCM", report)
        self.assertIn("O2 Sensor Circuit Low Voltage", report)  # from the DTC database
        self.assertIn("confirmed", report)
        self.assertIn("ABS", report)
        self.assertIn("no codes", report)
        self.assertIn("not present", report)


if __name__ == "__main__":
    unittest.main()
