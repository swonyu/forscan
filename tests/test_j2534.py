"""J2534 (PassThru) raw-CAN wire-codec tests.

Every expected value is hand-derived from SAE J2534-1: the raw-CAN ``PASSTHRU_MSG``
``Data`` field is the 4-byte BIG-ENDIAN arbitration ID followed by the payload, and
the ``CAN_29BIT_ID`` (0x100) bit in ``TxFlags``/``RxStatus`` marks a 29-bit extended
ID. The real ``PassThru*`` C entry points (a vendor .dylib over ctypes) are out of
scope here and are [NEEDS ON-CAR CHECK]; only the pure marshalling is proven.
"""
import ctypes
import unittest

from fordscope.transport import (
    CanFrame,
    Transport,
    TransportNotOpen,
    J2534Transport,
    PassThruMsg,
    CPassThruMsg,
    pack_msg,
    unpack_msg,
    PASSTHRU_MSG_DATA_LEN,
    encode_can_message,
    parse_can_message,
    can_baudrate,
    PROTOCOL_CAN,
    CAN_29BIT_ID,
    TX_MSG_TYPE,
    PASS_FILTER,
)
from fordscope.isotp import IsoTpSocket
from fordscope.obd import ObdClient, ObdError


class SpecConstantTests(unittest.TestCase):
    """Pin the two J2534-1 constants the codec depends on to their spec values."""

    def test_protocol_id_for_raw_can_is_5(self):
        self.assertEqual(PROTOCOL_CAN, 5)

    def test_can_29bit_flag_is_0x100(self):
        self.assertEqual(CAN_29BIT_ID, 0x00000100)


class EncodeTests(unittest.TestCase):
    def test_standard_frame(self):
        # ID 0x7DF as 4 big-endian bytes 00 00 07 DF, then payload 02 01 0C.
        # Standard ID => TxFlags has no CAN_29BIT_ID bit => 0.
        tx_flags, data = encode_can_message(CanFrame(0x7DF, bytes([0x02, 0x01, 0x0C])))
        self.assertEqual(tx_flags, 0)
        self.assertEqual(data, bytes.fromhex("000007DF02010C"))

    def test_extended_frame(self):
        # ID 0x18DAF110 as 4 big-endian bytes 18 DA F1 10, then payload 22 F1 90.
        # Extended ID => TxFlags carries CAN_29BIT_ID (0x100).
        tx_flags, data = encode_can_message(
            CanFrame(0x18DAF110, bytes([0x22, 0xF1, 0x90]), is_extended=True)
        )
        self.assertEqual(tx_flags, 0x100)
        self.assertEqual(data, bytes.fromhex("18DAF11022F190"))

    def test_empty_data(self):
        # No payload => Data is just the 4-byte big-endian ID (DataSize would be 4).
        tx_flags, data = encode_can_message(CanFrame(0x123))
        self.assertEqual(tx_flags, 0)
        self.assertEqual(data, bytes.fromhex("00000123"))

    def test_flag_not_id_bytes_distinguishes_extended(self):
        # The SAME numeric ID 0x123 encodes to IDENTICAL 4-byte Data whether standard
        # or extended; only the CAN_29BIT_ID flag differs. This is the crux of J2534's
        # id-width handling and the reason parse takes width from RxStatus, not size.
        std_flags, std_data = encode_can_message(CanFrame(0x123))
        ext_flags, ext_data = encode_can_message(CanFrame(0x123, is_extended=True))
        self.assertEqual(std_data, ext_data)              # identical ID bytes
        self.assertEqual((std_flags, ext_flags), (0, 0x100))  # only the flag differs


class ParseTests(unittest.TestCase):
    def test_standard(self):
        # 00 00 07 E8 (ID 0x7E8) + 41 0C 0F A0; RxStatus 0 => standard.
        frame = parse_can_message(bytes.fromhex("000007E8410C0FA0"), rx_status=0)
        self.assertEqual(frame.arbitration_id, 0x7E8)
        self.assertEqual(frame.data, bytes([0x41, 0x0C, 0x0F, 0xA0]))
        self.assertFalse(frame.is_extended)

    def test_extended(self):
        # 18 DA F1 10 (ID 0x18DAF110) + 22 F1 90; RxStatus has CAN_29BIT_ID => extended.
        frame = parse_can_message(
            bytes.fromhex("18DAF11022F190"), rx_status=CAN_29BIT_ID
        )
        self.assertEqual(frame.arbitration_id, 0x18DAF110)
        self.assertEqual(frame.data, bytes([0x22, 0xF1, 0x90]))
        self.assertTrue(frame.is_extended)

    def test_extended_flag_beats_id_magnitude(self):
        # A small ID (0x123) with the 29-bit RxStatus flag set MUST parse as extended,
        # proving width comes from the flag, not from the ID being > 0x7FF.
        frame = parse_can_message(bytes.fromhex("00000123"), rx_status=CAN_29BIT_ID)
        self.assertEqual(frame.arbitration_id, 0x123)
        self.assertTrue(frame.is_extended)

    def test_runt_shorter_than_id_returns_none_not_crash(self):
        # Fewer than the 4 mandatory ID bytes is malformed -> None (skippable).
        self.assertIsNone(parse_can_message(bytes.fromhex("000007"), rx_status=0))

    def test_payload_boundary_8_ok_9_none(self):
        # Classic CAN carries at most 8 payload bytes. 8 must parse; 9 must be skipped
        # (None), not crash -- a genuine straddle of the 8-byte limit.
        eight = parse_can_message(bytes.fromhex("000007E8") + bytes(8), rx_status=0)
        self.assertIsNotNone(eight)
        self.assertEqual(len(eight.data), 8)
        nine = parse_can_message(bytes.fromhex("000007E8") + bytes(9), rx_status=0)
        self.assertIsNone(nine)

    def test_11bit_id_boundary_7ff_ok_800_none(self):
        # Standard frame: 0x7FF is the 11-bit max (ok); 0x800 exceeds it (None).
        ok = parse_can_message((0x7FF).to_bytes(4, "big"), rx_status=0)
        self.assertIsNotNone(ok)
        self.assertEqual(ok.arbitration_id, 0x7FF)
        self.assertIsNone(parse_can_message((0x800).to_bytes(4, "big"), rx_status=0))

    def test_29bit_id_boundary_max_ok_over_none(self):
        # Extended frame: 0x1FFFFFFF is the 29-bit max (ok); 0x20000000 exceeds (None).
        ok = parse_can_message((0x1FFFFFFF).to_bytes(4, "big"), rx_status=CAN_29BIT_ID)
        self.assertIsNotNone(ok)
        self.assertEqual(ok.arbitration_id, 0x1FFFFFFF)
        self.assertIsNone(
            parse_can_message((0x20000000).to_bytes(4, "big"), rx_status=CAN_29BIT_ID)
        )

    def test_roundtrip_std_and_ext(self):
        # encode -> parse (feeding TxFlags back as RxStatus) must restore the frame,
        # for both a standard and an extended identifier.
        for f in (
            CanFrame(0x7DF, bytes([0x02, 0x01, 0x0C])),
            CanFrame(0x18DAF110, bytes([0x22, 0xF1, 0x90]), is_extended=True),
        ):
            tx_flags, data = encode_can_message(f)
            self.assertEqual(parse_can_message(data, rx_status=tx_flags), f)


class BaudrateTests(unittest.TestCase):
    def test_ford_baudrates(self):
        self.assertEqual(can_baudrate(500), 500_000)  # HS-CAN
        self.assertEqual(can_baudrate(125), 125_000)  # MS-CAN

    def test_unsupported_baudrate(self):
        with self.assertRaises(ValueError):
            can_baudrate(333)


class FakePassThruLibrary:
    """A minimal duck-typed J2534 library: records the call sequence, lets a test
    queue read batches, and captures written messages / installed filters. Stands
    in for the vendor .dylib (whose ctypes binding is [NEEDS ON-CAR CHECK])."""

    def __init__(self) -> None:
        self.calls = []            # ordered (method, *args) trace
        self._read_queue = []      # queued read batches: list[list[PassThruMsg]]
        self.written = []          # every PassThruMsg passed to write_msgs
        self.filters = []          # (filter_type, mask_msg, pattern_msg)
        self.disconnected = False
        self.closed = False
        self.device_id = 0xD1
        self.channel_id = 0xC1

    def open(self):
        self.calls.append(("open",))
        return self.device_id

    def connect(self, device_id, protocol_id, flags, baudrate):
        self.calls.append(("connect", device_id, protocol_id, flags, baudrate))
        return self.channel_id

    def start_msg_filter(self, channel_id, filter_type, mask, pattern):
        self.calls.append(("start_msg_filter", channel_id, filter_type))
        self.filters.append((filter_type, mask, pattern))
        return 1

    def write_msgs(self, channel_id, msgs, timeout):
        self.calls.append(("write_msgs", channel_id, len(msgs)))
        self.written.extend(msgs)

    def read_msgs(self, channel_id, timeout):
        if self._read_queue:
            return self._read_queue.pop(0)
        return []

    def feed(self, msgs):
        """Queue one PassThruReadMsgs batch (a list of PassThruMsg)."""
        self._read_queue.append(list(msgs))

    def disconnect(self, channel_id):
        self.calls.append(("disconnect", channel_id))
        self.disconnected = True

    def close(self, device_id):
        self.calls.append(("close", device_id))
        self.closed = True


class ScriptedPassThruLibrary:
    """A fake J2534 device for END-TO-END reads: open/connect/filter succeed
    silently; after each write_msgs of a CAN frame, the next queued response block
    (a list[PassThruMsg]) is armed and returned by the following read_msgs. Drives a
    real J2534Transport -> IsoTpSocket -> ObdClient stack with no hardware, exactly
    like slcan's ScriptedSlcanPort — a batch models the adapter returning several
    frames (e.g. consecutive frames) in one PassThruReadMsgs call."""

    def __init__(self, response_blocks) -> None:
        self._blocks = list(response_blocks)
        self._armed = None
        self.device_id = 1
        self.channel_id = 2

    def open(self):
        return self.device_id

    def connect(self, device_id, protocol_id, flags, baudrate):
        return self.channel_id

    def start_msg_filter(self, channel_id, filter_type, mask, pattern):
        return 0

    def write_msgs(self, channel_id, msgs, timeout):
        if self._blocks:
            self._armed = self._blocks.pop(0)

    def read_msgs(self, channel_id, timeout):
        if self._armed is not None:
            block, self._armed = self._armed, None
            return block
        return []

    def disconnect(self, channel_id):
        pass

    def close(self, device_id):
        pass


def _rx_msg(data_hex, rx_status=0):
    """A received raw-CAN PASSTHRU_MSG from a hex Data blob (4-byte ID + payload)."""
    return PassThruMsg(PROTOCOL_CAN, bytes.fromhex(data_hex), rx_status=rx_status)


class J2534TransportOpenTests(unittest.TestCase):
    def test_is_a_transport(self):
        self.assertIsInstance(J2534Transport(FakePassThruLibrary()), Transport)

    def test_open_opens_connects_and_installs_pass_all_filter(self):
        # open() must: PassThruOpen -> PassThruConnect(raw CAN, flags, 500k) ->
        # arm exactly one PASS_FILTER with a zero mask + zero pattern (pass-all).
        lib = FakePassThruLibrary()
        t = J2534Transport(lib, baudrate_kbps=500)
        t.open()
        self.assertTrue(t.is_open)
        self.assertEqual(lib.calls[0], ("open",))
        self.assertEqual(
            lib.calls[1], ("connect", 0xD1, PROTOCOL_CAN, 0, 500_000)
        )
        self.assertEqual(len(lib.filters), 1)
        ftype, mask, pattern = lib.filters[0]
        self.assertEqual(ftype, PASS_FILTER)
        self.assertEqual(mask.data, b"\x00\x00\x00\x00")     # zero mask
        self.assertEqual(pattern.data, b"\x00\x00\x00\x00")  # zero pattern => all IDs

    def test_ms_can_baudrate_flows_to_connect(self):
        # A different bus preset must reach PassThruConnect as bit/s: 125 -> 125000
        # (straddles the default 500 -> 500000 asserted above).
        lib = FakePassThruLibrary()
        J2534Transport(lib, baudrate_kbps=125).open()
        connect = next(c for c in lib.calls if c[0] == "connect")
        self.assertEqual(connect[4], 125_000)


class J2534TransportSendRecvTests(unittest.TestCase):
    def _open(self, lib=None):
        lib = lib or FakePassThruLibrary()
        t = J2534Transport(lib)
        t.open()
        return t, lib

    def test_send_before_open_raises(self):
        with self.assertRaises(TransportNotOpen):
            J2534Transport(FakePassThruLibrary()).send(CanFrame(0x7DF))

    def test_recv_before_open_raises(self):
        with self.assertRaises(TransportNotOpen):
            J2534Transport(FakePassThruLibrary()).recv()

    def test_send_marshals_standard_frame(self):
        # CanFrame -> PASSTHRU_MSG: ID 0x7DF as 00 00 07 DF + payload, TxFlags 0.
        t, lib = self._open()
        t.send(CanFrame(0x7DF, bytes([0x02, 0x01, 0x0C])))
        msg = lib.written[-1]
        self.assertEqual(msg.protocol_id, PROTOCOL_CAN)
        self.assertEqual(msg.tx_flags, 0)
        self.assertEqual(msg.data, bytes.fromhex("000007DF02010C"))

    def test_send_marshals_extended_frame_sets_29bit_flag(self):
        # Extended ID => TxFlags carries CAN_29BIT_ID (0x100); Data is the 4-byte ID.
        t, lib = self._open()
        t.send(CanFrame(0x18DAF110, bytes([0x22, 0xF1, 0x90]), is_extended=True))
        msg = lib.written[-1]
        self.assertEqual(msg.tx_flags, CAN_29BIT_ID)
        self.assertEqual(msg.data, bytes.fromhex("18DAF11022F190"))

    def test_recv_parses_a_standard_frame(self):
        t, lib = self._open()
        lib.feed([_rx_msg("000007E8410C0FA0")])  # ID 0x7E8, payload 41 0C 0F A0
        frame = t.recv()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.arbitration_id, 0x7E8)
        self.assertEqual(frame.data, bytes([0x41, 0x0C, 0x0F, 0xA0]))
        self.assertFalse(frame.is_extended)

    def test_recv_takes_extended_from_rx_status(self):
        t, lib = self._open()
        lib.feed([_rx_msg("18DAF11022F190", rx_status=CAN_29BIT_ID)])
        frame = t.recv()
        self.assertEqual(frame.arbitration_id, 0x18DAF110)
        self.assertTrue(frame.is_extended)

    def test_recv_skips_transmit_loopback_then_returns_received(self):
        # A device echoes our transmit back with TX_MSG_TYPE set; recv MUST drop it
        # and return the genuinely-received frame that follows in the same batch —
        # else the stack "hears" its own request as a reply.
        t, lib = self._open()
        lib.feed([
            _rx_msg("000007DF02010C", rx_status=TX_MSG_TYPE),  # our own send, echoed
            _rx_msg("000007E8410C0FA0", rx_status=0),          # the real ECU reply
        ])
        frame = t.recv()
        self.assertEqual(frame.arbitration_id, 0x7E8)   # the reply, not...
        self.assertNotEqual(frame.arbitration_id, 0x7DF)  # ...the loopback of our send

    def test_recv_lone_loopback_yields_none(self):
        # A batch of only a loopback echo (no real frame) must resolve to None, not
        # return our own transmitted frame.
        t, lib = self._open()
        lib.feed([_rx_msg("000007DF02010C", rx_status=TX_MSG_TYPE)])
        self.assertIsNone(t.recv())

    def test_recv_skips_malformed_record_then_returns_next(self):
        # A runt Data (< 4 ID bytes) parses to None; recv must skip it and return the
        # following valid frame, not crash the receive loop.
        t, lib = self._open()
        lib.feed([_rx_msg("000007"), _rx_msg("000007E8410C0FA0")])
        frame = t.recv()
        self.assertEqual(frame.arbitration_id, 0x7E8)

    def test_recv_returns_none_when_no_messages(self):
        t, _ = self._open()
        self.assertIsNone(t.recv())


class J2534TransportCloseTests(unittest.TestCase):
    def test_close_disconnects_channel_and_closes_device(self):
        lib = FakePassThruLibrary()
        t = J2534Transport(lib)
        t.open()
        t.close()
        self.assertTrue(lib.disconnected)
        self.assertTrue(lib.closed)
        self.assertFalse(t.is_open)

    def test_close_closes_device_even_if_disconnect_raises(self):
        # Adapter yanked mid-session: PassThruDisconnect raises. close() must still
        # PassThruClose the device and flip is_open, not propagate and leak it.
        class _DisconnectRaises(FakePassThruLibrary):
            def disconnect(self, channel_id):
                raise OSError("device not connected")

        lib = _DisconnectRaises()
        t = J2534Transport(lib)
        t.open()
        t.close()  # must not propagate
        self.assertTrue(lib.closed)
        self.assertFalse(t.is_open)

    def test_context_manager_opens_then_closes(self):
        lib = FakePassThruLibrary()
        with J2534Transport(lib) as bus:
            self.assertTrue(bus.is_open)
        self.assertTrue(lib.disconnected)
        self.assertTrue(lib.closed)


class J2534EndToEndReadTests(unittest.TestCase):
    """The J2534 path proven as an INTEGRATED read: scripted PASSTHRU_MSG batches ->
    J2534Transport parse -> IsoTpSocket reassembly -> ObdClient decode -> a correct
    value. Mirrors the slcan/elm327 end-to-end tests so all three shipped real
    backends have full-stack composition covered, not just per-layer units."""

    def _obd(self, response_blocks):
        t = J2534Transport(ScriptedPassThruLibrary(response_blocks))
        t.open()
        return ObdClient(IsoTpSocket(t, tx_id=0x7E0, rx_id=0x7E8))

    def test_single_frame_read_rpm_end_to_end(self):
        # SF reply to Mode 01 PID 0C: ID 0x7E8, Data 00 00 07 E8 + 04 41 0C 0F A0 00
        # 00 00 (PCI SF len 4, then 41 0C 0F A0 => (256*0x0F+0xA0)/4 = 1000 rpm).
        obd = self._obd([[_rx_msg("000007E8" + "04410C0FA0000000")]])
        r = obd.current_data(0x0C)
        self.assertEqual((r.name, r.value, r.unit), ("Engine RPM", 1000.0, "rpm"))

    def test_multiframe_vin_read_end_to_end(self):
        # Multiframe VIN: the client's Flow Control goes DOWN through J2534 send and
        # the consecutive frames come UP through recv (with the second batch's two CFs
        # buffered across recv calls). FF (10 14 49 02 01 '1FM') then CF1 + CF2.
        obd = self._obd([
            [_rx_msg("000007E8" + "101449020131464D")],           # FF
            [                                                       # CF1 + CF2 in one read
                _rx_msg("000007E8" + "21484B3844383941"),
                _rx_msg("000007E8" + "2242413132333435"),
            ],
        ])
        self.assertEqual(obd.read_vin(), "1FMHK8D89ABA12345")

    def test_silent_bus_surfaces_clean_error_not_a_hang(self):
        # A module that never answers (silent CAN bus): read_msgs always returns [] ->
        # recv None -> the full stack must surface a clean ObdError, not hang.
        obd = self._obd([])
        with self.assertRaises(ObdError) as ctx:
            obd.current_data(0x0C)
        self.assertIn("no response", str(ctx.exception))


class PassThruMsgCAbiTests(unittest.TestCase):
    """The ctypes image of the J2534-1 ``PASSTHRU_MSG`` C struct — the binary face
    the real vendor ``.dylib`` reads/writes over ctypes. Every expected value is
    hand-derived from SAE J2534-1 (confirmed vs the published spec + v0404 headers):

        unsigned long ProtocolID, RxStatus, TxFlags, Timestamp, DataSize, ExtraDataIndex;
        unsigned char Data[4128];

    ``unsigned long`` is 32-bit in the J2534 (Windows-origin) ABI, so the struct is
    6*4 + 4128 = 4152 bytes with fields at 4-byte offsets. Loading and CALLING the
    real ``.dylib`` remains [NEEDS ON-CAR CHECK]; only this pure marshalling is proven.
    """

    def test_struct_size_is_4152_spec_exact(self):
        # 6 four-byte unsigned longs + Data[4128] = 24 + 4128 = 4152.
        self.assertEqual(ctypes.sizeof(CPassThruMsg), 4152)

    def test_leading_fields_are_4_bytes_not_8(self):
        # STRADDLE: J2534 `unsigned long` is 32-bit. Using c_ulong (8 bytes under LP64
        # on macOS/Linux) would silently double every field's width and mis-align the
        # struct (sizeof 4176) -> pin each leading field to 4 bytes.
        for name in ("ProtocolID", "RxStatus", "TxFlags", "Timestamp",
                     "DataSize", "ExtraDataIndex"):
            self.assertEqual(getattr(CPassThruMsg, name).size, 4, name)

    def test_field_offsets_match_spec_order(self):
        # Spec field order at 4-byte strides, Data immediately after the 6 longs.
        expected = {
            "ProtocolID": 0, "RxStatus": 4, "TxFlags": 8, "Timestamp": 12,
            "DataSize": 16, "ExtraDataIndex": 20, "Data": 24,
        }
        for name, off in expected.items():
            self.assertEqual(getattr(CPassThruMsg, name).offset, off, name)

    def test_data_capacity_is_4128(self):
        self.assertEqual(PASSTHRU_MSG_DATA_LEN, 4128)
        self.assertEqual(getattr(CPassThruMsg, "Data").size, 4128)

    def test_pack_sets_datasize_and_copies_data(self):
        # Raw-CAN PASSTHRU_MSG for ID 0x7DF + payload 02 01 0C: Data = 00 00 07 DF 02
        # 01 0C (7 bytes), DataSize = 7, ProtocolID = CAN(5), trailing array zeroed.
        c = pack_msg(PassThruMsg(PROTOCOL_CAN, bytes.fromhex("000007DF02010C")))
        self.assertEqual(c.ProtocolID, PROTOCOL_CAN)
        self.assertEqual(c.DataSize, 7)
        self.assertEqual(bytes(c.Data[:7]), bytes.fromhex("000007DF02010C"))
        self.assertEqual(c.Data[7], 0)  # remainder of the fixed array stays zero

    def test_pack_carries_flags_and_timestamp(self):
        c = pack_msg(PassThruMsg(PROTOCOL_CAN, b"\x00\x00\x01\x23",
                                 tx_flags=CAN_29BIT_ID, rx_status=TX_MSG_TYPE,
                                 timestamp=1234))
        self.assertEqual(c.TxFlags, CAN_29BIT_ID)
        self.assertEqual(c.RxStatus, TX_MSG_TYPE)
        self.assertEqual(c.Timestamp, 1234)

    def test_unpack_reads_only_datasize_bytes(self):
        # Only the first DataSize bytes of the fixed 4128-byte Data array are valid; a
        # stale byte parked beyond DataSize must NOT leak into the decoded payload.
        c = CPassThruMsg()
        c.ProtocolID = PROTOCOL_CAN
        valid = bytes.fromhex("000007E8410C0FA0")  # ID 0x7E8 + 41 0C 0F A0 (8 bytes)
        for i, b in enumerate(valid):
            c.Data[i] = b
        c.Data[8] = 0xEE                            # stale trailing byte past DataSize
        c.DataSize = 8
        msg = unpack_msg(c)
        self.assertEqual(msg.data, valid)           # exactly 8 bytes, no 0xEE
        self.assertEqual(msg.protocol_id, PROTOCOL_CAN)

    def test_pack_unpack_roundtrip_std_and_ext(self):
        # pack -> unpack restores every dataclass field, for a standard and an
        # extended (29-bit) message.
        for msg in (
            PassThruMsg(PROTOCOL_CAN, bytes.fromhex("000007DF02010C")),
            PassThruMsg(PROTOCOL_CAN, bytes.fromhex("18DAF11022F190"),
                        tx_flags=CAN_29BIT_ID, rx_status=CAN_29BIT_ID),
        ):
            self.assertEqual(unpack_msg(pack_msg(msg)), msg)

    def test_data_capacity_straddle_4128_ok_4129_raises(self):
        # Exactly 4128 fits the fixed array; 4129 overflows -> ValueError, never a
        # silent truncation or buffer overrun.
        ok = pack_msg(PassThruMsg(PROTOCOL_CAN, bytes(PASSTHRU_MSG_DATA_LEN)))
        self.assertEqual(ok.DataSize, PASSTHRU_MSG_DATA_LEN)
        with self.assertRaises(ValueError):
            pack_msg(PassThruMsg(PROTOCOL_CAN, bytes(PASSTHRU_MSG_DATA_LEN + 1)))


if __name__ == "__main__":
    unittest.main()
