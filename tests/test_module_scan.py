"""Whole-car module scan tests over a multi-module simulated bus."""
import unittest

from fordscope.transport import SimulatorTransport, CanFrame, Elm327Transport
from fordscope.isotp import (
    SimulatedIsoTpEcu,
    multiplex,
    parse_isotp,
    IsoTpFrameType,
    encode_first_frame,
)
from fordscope.uds import SimulatedUdsEcu
from fordscope.ford import eleven_bit_module
from fordscope.services import scan_vehicle, format_scan_report

VIN = b"1FMHK8D89ABA12345"

PCM = eleven_bit_module(0x7E0, name="PCM")
BCM = eleven_bit_module(0x726, name="BCM")
APIM_ABSENT = eleven_bit_module(0x7D0, name="APIM")
PSCM_EMPTY = eleven_bit_module(0x730, name="PSCM")


def build_bus(*ecus):
    bus = SimulatorTransport(multiplex(*ecus))
    bus.open()
    return bus


def ecu_at(pair, dids):
    return SimulatedIsoTpEcu(
        SimulatedUdsEcu(dids), request_id=pair.request_id, response_id=pair.response_id
    )


class WholeCarScanTests(unittest.TestCase):
    def setUp(self):
        self.pcm = ecu_at(PCM, {0xF190: VIN, 0xF187: b"AB-1234-CD", 0xF188: b"SW-99"})
        self.bcm = ecu_at(BCM, {0xF187: b"BCM-PART-01", 0xF194: b"v3.1"})
        self.bus = build_bus(self.pcm, self.bcm)  # APIM has no ECU -> absent

    def test_present_module_identifiers(self):
        infos = {m.name: m for m in scan_vehicle(self.bus, [PCM, BCM, APIM_ABSENT], timeout=0.1)}
        self.assertTrue(infos["PCM"].present)
        self.assertEqual(infos["PCM"].text("VIN"), "1FMHK8D89ABA12345")
        self.assertEqual(infos["PCM"].text("Spare part number"), "AB-1234-CD")
        self.assertTrue(infos["BCM"].present)
        self.assertEqual(infos["BCM"].text("ECU software version"), "v3.1")

    def test_absent_module_detected(self):
        infos = {m.name: m for m in scan_vehicle(self.bus, [PCM, BCM, APIM_ABSENT], timeout=0.1)}
        self.assertFalse(infos["APIM"].present)
        self.assertEqual(infos["APIM"].identifiers, {})

    def test_module_present_but_no_supported_dids(self):
        # An ECU that answers every identification DID with a negative response
        # is still present (it answered), just carries no identifiers.
        empty = ecu_at(PSCM_EMPTY, {})  # no DIDs -> NRC 0x31 to each read
        bus = build_bus(empty)
        infos = scan_vehicle(bus, [PSCM_EMPTY], timeout=0.1)
        self.assertTrue(infos[0].present)
        self.assertEqual(infos[0].identifiers, {})

    def test_report_formatting(self):
        infos = scan_vehicle(self.bus, [PCM, BCM, APIM_ABSENT], timeout=0.1)
        report = format_scan_report(infos)
        self.assertIn("[OK] PCM", report)
        self.assertIn("1FMHK8D89ABA12345", report)
        self.assertIn("[--] APIM", report)
        self.assertIn("not present", report)


def _ff_then_silent(frame):
    """A module that answers with a First Frame then never sends consecutive
    frames — reproduces a real bus dropout mid-multi-frame response. Only replies
    on 0x726."""
    if frame.arbitration_id != 0x726:
        return ()
    pci = parse_isotp(frame.data)
    if pci.type is IsoTpFrameType.SINGLE:  # the request -> reply with a bare FF
        return (CanFrame(0x72E, encode_first_frame(20, bytes(range(6)))),)
    return ()  # ignore the client's Flow Control -> it times out on the CFs


class MidTransferFaultTests(unittest.TestCase):
    def test_isotp_fault_marks_present_and_does_not_abort_scan(self):
        # BCM answers a FF then goes silent (IsoTpTimeout); ABS is normal.
        normal_abs = ecu_at(eleven_bit_module(0x760, name="ABS"), {0xF187: b"ABS-9"})
        bus = SimulatorTransport(multiplex(_ff_then_silent, normal_abs))
        bus.open()
        infos = {
            m.name: m
            for m in scan_vehicle(
                bus,
                [eleven_bit_module(0x726, name="BCM"), eleven_bit_module(0x760, name="ABS")],
                timeout=0.02,
            )
        }
        # The faulty module must be PRESENT (it answered), scan must NOT abort,
        # and the normal module must still be reached.
        self.assertTrue(infos["BCM"].present)
        self.assertEqual(infos["BCM"].identifiers, {})
        self.assertTrue(infos["ABS"].present)
        self.assertEqual(infos["ABS"].text("Spare part number"), "ABS-9")


class RealBackendScanTests(unittest.TestCase):
    """The flagship whole-car scan proven over a REAL backend (elm327/vLinker FS),
    not the simulator: it must mark a responding module PRESENT and a silent one
    ABSENT in ONE scan. This exercises the subtle correctness the simulator can't --
    that an adapter's "NO DATA" maps to UdsError -> not-present (so the scan neither
    crashes nor mis-reports an absent module as present) through the real wire codec."""

    class RoutingElmPort:
        """Routes replies by the current ATSH header, so one scan sees a real reply
        for one module and "NO DATA" (absent) for another."""

        def __init__(self, by_header):
            self._map = by_header
            self._current = None
            self._armed = None

        def write(self, data):
            text = bytes(data).decode("ascii", "ignore").strip().upper()
            if text.startswith("ATSH"):
                self._current = text[4:]
            elif text and not text.startswith("AT"):
                self._armed = self._map.get(self._current, "NO DATA")
            return len(data)

        def read(self, size=1):
            if self._armed is not None:
                block, self._armed = self._armed, None
                return (block + "\r>").encode("ascii")
            return b">"

        def close(self):
            pass

    def test_scan_over_elm327_marks_present_and_absent(self):
        modules = [eleven_bit_module(0x7E0, name="PCM"), eleven_bit_module(0x7E1, name="TCM")]
        # PCM (header 7E0) answers RDBI F190 -> "123"; TCM (header 7E1) is silent.
        port = self.RoutingElmPort({
            "7E0": "7E8 06 62 F1 90 31 32 33 00",
            "7E1": "NO DATA",
        })
        t = Elm327Transport(port)
        t.open()
        infos = {m.name: m for m in scan_vehicle(t, modules, timeout=0.2)}
        self.assertTrue(infos["PCM"].present)
        self.assertEqual(infos["PCM"].text("VIN"), "123")
        self.assertFalse(infos["TCM"].present)   # NO DATA -> UdsError -> absent, not a crash
        report = format_scan_report(list(infos.values()))
        self.assertIn("[OK] PCM", report)
        self.assertIn("[--] TCM", report)


if __name__ == "__main__":
    unittest.main()
