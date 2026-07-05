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
    PASSTHRU_PROTOTYPES,
    bind_prototypes,
    load_library,
    encode_can_message,
    parse_can_message,
    can_baudrate,
    PROTOCOL_CAN,
    CAN_29BIT_ID,
    TX_MSG_TYPE,
    PASS_FILTER,
    PassThruAdapter,
    J2534Error,
    STATUS_NOERROR,
    ERR_BUFFER_EMPTY,
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


class _FakePassThruLib:
    """Injected stand-in for a loaded ``ctypes.CDLL``: one settable-``restype``/
    ``argtypes`` slot per ``PassThru*`` entry point, mirroring the ``_FuncPtr`` objects
    ctypes exposes. Lets ``bind_prototypes`` be exercised with NO real vendor ``.dylib``
    -- exactly as ``J2534Transport`` is driven by an injected PassThru object. A bogus
    name in the prototype table would raise ``AttributeError`` here, so the fake also
    pins the entry-point NAME set from the test side.
    """

    class _Func:
        __slots__ = ("restype", "argtypes")

        def __init__(self):
            self.restype = None
            self.argtypes = None

    def __init__(self, names):
        for n in names:
            setattr(self, n, self._Func())


class J2534PrototypeBindingTests(unittest.TestCase):
    """The ctypes PROTOTYPES for the J2534-1 ``PassThru*`` C entry points -- the
    ``restype``/``argtypes`` ctypes uses to marshal Python args to the vendor
    ``.dylib``'s C ABI. Every expected signature is hand-derived from the SAE
    J2534-1 v04.04 API (the same standard the ``CPassThruMsg`` struct comes from):

        long PassThruOpen(void *pName, unsigned long *pDeviceID);
        long PassThruConnect(unsigned long DeviceID, unsigned long ProtocolID,
                             unsigned long Flags, unsigned long BaudRate,
                             unsigned long *pChannelID);
        long PassThruReadMsgs(unsigned long ChannelID, PASSTHRU_MSG *pMsg,
                              unsigned long *pNumMsgs, unsigned long Timeout);
        ... (14 entry points total)

    J2534's ``unsigned long`` is the 32-bit Windows-origin type -> ``c_uint32``
    (matching the struct's fields, NOT LP64 ``c_ulong`` which is 8 bytes on macOS/
    Linux); the status return ``long`` -> ``c_int32``; ``PASSTHRU_MSG *`` ->
    ``POINTER(CPassThruMsg)``. LOADING a real vendor ``.dylib`` and CALLING these
    entry points needs the hardware + driver and stays **[NEEDS ON-CAR CHECK]**;
    only the prototype BINDING over an injected fake (and the missing-library error
    path) is proven here, with no hardware attached.
    """

    def _expected(self):
        # Independent hand-derivation from SAE J2534-1 v04.04 -- NOT read from the
        # module's PASSTHRU_PROTOTYPES. U=unsigned long(32b), L=long return(32b),
        # UP=unsigned long*, M=PASSTHRU_MSG*, VP=void*, CP=char*.
        U = ctypes.c_uint32
        L = ctypes.c_int32
        UP = ctypes.POINTER(ctypes.c_uint32)
        M = ctypes.POINTER(CPassThruMsg)
        VP = ctypes.c_void_p
        CP = ctypes.c_char_p
        return {
            "PassThruOpen": (L, [VP, UP]),
            "PassThruClose": (L, [U]),
            "PassThruConnect": (L, [U, U, U, U, UP]),
            "PassThruDisconnect": (L, [U]),
            "PassThruReadMsgs": (L, [U, M, UP, U]),
            "PassThruWriteMsgs": (L, [U, M, UP, U]),
            "PassThruStartPeriodicMsg": (L, [U, M, UP, U]),
            "PassThruStopPeriodicMsg": (L, [U, U]),
            "PassThruStartMsgFilter": (L, [U, U, M, M, M, UP]),
            "PassThruStopMsgFilter": (L, [U, U]),
            "PassThruSetProgrammingVoltage": (L, [U, U, U]),
            "PassThruReadVersion": (L, [U, CP, CP, CP]),
            "PassThruGetLastError": (L, [CP]),
            "PassThruIoctl": (L, [U, U, VP, VP]),
        }

    def test_prototype_table_covers_exactly_the_j2534_v0404_api(self):
        # No missing entry point, no invented extra one -- the exact v04.04 set.
        self.assertEqual(set(PASSTHRU_PROTOTYPES), set(self._expected()))

    def test_bind_prototypes_applies_spec_signatures_to_each_entry_point(self):
        exp = self._expected()
        lib = _FakePassThruLib(exp.keys())
        bind_prototypes(lib)
        for name, (restype, argtypes) in exp.items():
            func = getattr(lib, name)
            self.assertEqual(func.restype, restype, name)
            self.assertEqual(list(func.argtypes), argtypes, name)

    def test_bind_prototypes_returns_the_same_lib_for_chaining(self):
        lib = _FakePassThruLib(self._expected().keys())
        self.assertIs(bind_prototypes(lib), lib)

    def test_readmsgs_takes_the_struct_pointer_and_an_out_count(self):
        # STRADDLE: the message arg must be POINTER(CPassThruMsg) (NOT a bare c_void_p),
        # and the count is an OUT pointer (POINTER(c_uint32)) not a by-value count --
        # else the driver cannot report how many messages it actually read.
        _restype, argtypes = PASSTHRU_PROTOTYPES["PassThruReadMsgs"]
        self.assertEqual(
            list(argtypes),
            [ctypes.c_uint32, ctypes.POINTER(CPassThruMsg),
             ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32],
        )

    def test_startmsgfilter_takes_three_message_pointers(self):
        # STRADDLE: the 6-arg filter is mask, pattern, flow-control (three
        # PASSTHRU_MSG*) + an out filter-id -- dropping one or mistyping the struct
        # pointer would break the pass-all filter the raw-CAN channel needs.
        _restype, argtypes = PASSTHRU_PROTOTYPES["PassThruStartMsgFilter"]
        argtypes = list(argtypes)
        self.assertEqual(len(argtypes), 6)
        self.assertEqual(argtypes[2:5], [ctypes.POINTER(CPassThruMsg)] * 3)
        self.assertEqual(argtypes[5], ctypes.POINTER(ctypes.c_uint32))

    def test_scalar_handle_args_are_32bit_not_lp64(self):
        # STRADDLE: J2534 `unsigned long` is 32-bit; c_ulong is 8 bytes under LP64 on
        # macOS/Linux and would mis-marshal every handle. Pin Connect's four handle
        # args to a 4-byte scalar and its out-channel to a 32-bit pointer.
        _restype, argtypes = PASSTHRU_PROTOTYPES["PassThruConnect"]
        argtypes = list(argtypes)
        self.assertEqual(len(argtypes), 5)
        for a in argtypes[:4]:
            self.assertIs(a, ctypes.c_uint32)
            self.assertEqual(ctypes.sizeof(a), 4)
        self.assertEqual(argtypes[4], ctypes.POINTER(ctypes.c_uint32))

    def test_all_entry_points_return_the_j2534_status_long(self):
        # Every PassThru* function returns the `long` status code -> c_int32 (4 bytes),
        # never the ctypes default int on some other-width platform.
        for name, (restype, _argtypes) in PASSTHRU_PROTOTYPES.items():
            self.assertEqual(restype, ctypes.c_int32, name)
            self.assertEqual(ctypes.sizeof(restype), 4, name)

    def test_load_library_raises_for_missing_dylib(self):
        # Real vendor-.dylib LOAD + CALL is [NEEDS ON-CAR CHECK]; the ERROR path (a
        # missing library) is simulator-testable and must surface, not be swallowed.
        with self.assertRaises(OSError):
            load_library("/nonexistent/fordscope-no-such-j2534.dylib")


class _FakeBoundLib:
    """Callable stand-in for a *bound* ctypes ``CDLL``: each ``PassThru*`` entry point
    is a Python callable receiving the SAME marshalled args ``PassThruAdapter`` hands
    the C ABI (out-params as ``ctypes.pointer`` objects, messages as a ``CPassThruMsg``
    array), simulating the C side by filling out-params and returning a status ``int``.
    Records every call so the marshalling can be asserted. No vendor ``.dylib``, no bus
    — this is the injected face the adapter is proven against, exactly as
    ``_FakePassThruLib`` stands in for the CDLL that ``bind_prototypes`` decorates."""

    def __init__(self):
        self.calls = []
        self.device_id = 0xD1
        self.channel_id = 0xC1
        self.filter_id = 0x2A
        self.written = []          # PassThruMsg recovered from PassThruWriteMsgs
        self._read_batches = []    # queued list[PassThruMsg] for PassThruReadMsgs
        self.force_status = {}     # entry-point name -> status to return instead of 0

    def _status(self, name):
        return self.force_status.get(name, STATUS_NOERROR)

    def feed(self, msgs):
        """Queue one PassThruReadMsgs batch (a list of PassThruMsg)."""
        self._read_batches.append(list(msgs))

    def PassThruOpen(self, p_name, p_device_id):
        self.calls.append(("PassThruOpen", p_name))
        p_device_id.contents.value = self.device_id
        return self._status("PassThruOpen")

    def PassThruConnect(self, device_id, protocol_id, flags, baudrate, p_channel_id):
        self.calls.append(("PassThruConnect", device_id, protocol_id, flags, baudrate))
        p_channel_id.contents.value = self.channel_id
        return self._status("PassThruConnect")

    def PassThruStartMsgFilter(self, channel_id, filter_type, p_mask, p_pattern,
                               p_flow, p_filter_id):
        self.calls.append((
            "PassThruStartMsgFilter", channel_id, filter_type,
            unpack_msg(p_mask.contents), unpack_msg(p_pattern.contents), p_flow,
        ))
        p_filter_id.contents.value = self.filter_id
        return self._status("PassThruStartMsgFilter")

    def PassThruWriteMsgs(self, channel_id, arr, p_num, timeout):
        n = p_num.contents.value
        self.written.extend(unpack_msg(arr[i]) for i in range(n))
        self.calls.append(("PassThruWriteMsgs", channel_id, n, timeout))
        return self._status("PassThruWriteMsgs")

    def PassThruReadMsgs(self, channel_id, arr, p_num, timeout):
        forced = self.force_status.get("PassThruReadMsgs")
        if forced is not None:
            p_num.contents.value = 0
            return forced
        if not self._read_batches:
            p_num.contents.value = 0
            return ERR_BUFFER_EMPTY  # spec's "nothing arrived within Timeout"
        batch = self._read_batches.pop(0)
        cap = p_num.contents.value                 # adapter's buffer capacity
        k = min(len(batch), cap)
        for i in range(k):
            arr[i] = pack_msg(batch[i])
        p_num.contents.value = k                   # actual count read back out
        self.calls.append(("PassThruReadMsgs", channel_id, timeout, k))
        return STATUS_NOERROR

    def PassThruDisconnect(self, channel_id):
        self.calls.append(("PassThruDisconnect", channel_id))
        return self._status("PassThruDisconnect")

    def PassThruClose(self, device_id):
        self.calls.append(("PassThruClose", device_id))
        return self._status("PassThruClose")


class PassThruAdapterTests(unittest.TestCase):
    """``PassThruAdapter`` turns a bound ctypes CDLL (the callable ``.dylib`` face)
    into the high-level ``pt`` duck-type ``J2534Transport`` drives. Proven over
    ``_FakeBoundLib`` with no hardware; the status codes asserted are hand-derived
    from the SAE J2534-1 return-value table, not read from the adapter."""

    def test_status_codes_are_spec_values(self):
        # SAE J2534-1 return-value table: success == 0x00; ReadMsgs' empty-buffer
        # signal == 0x10. These drive the adapter's raise-vs-empty-list decision.
        self.assertEqual(STATUS_NOERROR, 0x00)
        self.assertEqual(ERR_BUFFER_EMPTY, 0x10)

    def test_open_returns_device_id_and_passes_null_name(self):
        lib = _FakeBoundLib()
        self.assertEqual(PassThruAdapter(lib).open(), 0xD1)
        self.assertEqual(lib.calls[0], ("PassThruOpen", None))

    def test_connect_marshals_scalars_and_returns_channel_id(self):
        lib = _FakeBoundLib()
        chan = PassThruAdapter(lib).connect(0xD1, PROTOCOL_CAN, 0, 500000)
        self.assertEqual(chan, 0xC1)
        self.assertEqual(
            lib.calls[-1], ("PassThruConnect", 0xD1, PROTOCOL_CAN, 0, 500000)
        )

    def test_start_msg_filter_sends_mask_pattern_null_flow_returns_id(self):
        lib = _FakeBoundLib()
        zero = b"\x00\x00\x00\x00"
        fid = PassThruAdapter(lib).start_msg_filter(
            0xC1, PASS_FILTER,
            PassThruMsg(PROTOCOL_CAN, zero), PassThruMsg(PROTOCOL_CAN, zero),
        )
        self.assertEqual(fid, 0x2A)
        name, chan, ftype, mask, pattern, flow = lib.calls[-1]
        self.assertEqual((name, chan, ftype),
                         ("PassThruStartMsgFilter", 0xC1, PASS_FILTER))
        self.assertEqual(mask.data, zero)
        self.assertEqual(pattern.data, zero)
        self.assertIsNone(flow)  # a PASS filter has a NULL flow-control message ptr

    def test_write_msgs_packs_every_frame_and_passes_timeout(self):
        lib = _FakeBoundLib()
        m1 = PassThruMsg(PROTOCOL_CAN, bytes.fromhex("000007E0AABB"))
        m2 = PassThruMsg(PROTOCOL_CAN, bytes.fromhex("000007E00201"),
                         tx_flags=CAN_29BIT_ID)
        PassThruAdapter(lib).write_msgs(0xC1, [m1, m2], 100)
        self.assertEqual(len(lib.written), 2)
        self.assertEqual(lib.written[0].data.hex(), "000007e0aabb")
        self.assertEqual(lib.written[1].data.hex(), "000007e00201")
        self.assertEqual(lib.written[1].tx_flags, CAN_29BIT_ID)
        self.assertEqual(lib.calls[-1], ("PassThruWriteMsgs", 0xC1, 2, 100))

    def test_read_msgs_unpacks_returned_batch_with_status(self):
        lib = _FakeBoundLib()
        lib.feed([
            PassThruMsg(PROTOCOL_CAN, bytes.fromhex("000007E80341")),
            PassThruMsg(PROTOCOL_CAN, bytes.fromhex("18DAF11022"),
                        rx_status=CAN_29BIT_ID),
        ])
        got = PassThruAdapter(lib).read_msgs(0xC1, 1000)
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0].data.hex(), "000007e80341")
        self.assertEqual(got[1].data.hex(), "18daf11022")
        self.assertEqual(got[1].rx_status, CAN_29BIT_ID)

    def test_read_msgs_empty_buffer_is_empty_list_not_error(self):
        lib = _FakeBoundLib()  # nothing fed => fake returns ERR_BUFFER_EMPTY
        self.assertEqual(PassThruAdapter(lib).read_msgs(0xC1, 5), [])

    def test_nonzero_status_raises_j2534error_with_function_and_code(self):
        lib = _FakeBoundLib()
        lib.force_status["PassThruOpen"] = 0x07  # ERR_FAILED per SAE J2534-1
        with self.assertRaises(J2534Error) as ctx:
            PassThruAdapter(lib).open()
        self.assertEqual(ctx.exception.function, "PassThruOpen")
        self.assertEqual(ctx.exception.status, 0x07)

    def test_read_msgs_hard_error_still_raises_not_swallowed(self):
        # A read failure that is NOT buffer-empty must surface, not become [].
        lib = _FakeBoundLib()
        lib.force_status["PassThruReadMsgs"] = 0x02  # ERR_INVALID_CHANNEL_ID
        with self.assertRaises(J2534Error):
            PassThruAdapter(lib).read_msgs(0xC1, 5)

    def test_disconnect_and_close_hit_their_entry_points(self):
        lib = _FakeBoundLib()
        adapter = PassThruAdapter(lib)
        adapter.disconnect(0xC1)
        adapter.close(0xD1)
        self.assertIn(("PassThruDisconnect", 0xC1), lib.calls)
        self.assertIn(("PassThruClose", 0xD1), lib.calls)

    def test_adapter_drives_j2534transport_open_send_recv_end_to_end(self):
        # The payoff: the adapter satisfies J2534Transport's `pt` contract, so the
        # full transport lifecycle round-trips a CAN frame through the bound-.dylib
        # face with NO hardware — exactly as iter 140 proved over a scripted duck-type.
        lib = _FakeBoundLib()
        t = J2534Transport(PassThruAdapter(lib), baudrate_kbps=500)
        t.open()
        self.assertEqual(lib.calls[0], ("PassThruOpen", None))
        self.assertEqual(lib.calls[1],
                         ("PassThruConnect", 0xD1, PROTOCOL_CAN, 0, 500000))
        self.assertEqual(lib.calls[2][:3],
                         ("PassThruStartMsgFilter", 0xC1, PASS_FILTER))
        # send marshals a standard frame through PassThruWriteMsgs (4-byte BE id)
        t.send(CanFrame(0x7E0, bytes.fromhex("02010C")))
        self.assertEqual(len(lib.written), 1)
        self.assertEqual(lib.written[0].data.hex(), "000007e002010c")
        # a frame waiting on the bus comes back through PassThruReadMsgs
        lib.feed([PassThruMsg(PROTOCOL_CAN, bytes.fromhex("000007E8030C1234"))])
        frame = t.recv(timeout=1.0)
        self.assertIsInstance(frame, CanFrame)
        self.assertEqual(frame.arbitration_id, 0x7E8)
        self.assertEqual(frame.data.hex(), "030c1234")
        t.close()
        self.assertIn(("PassThruDisconnect", 0xC1), lib.calls)
        self.assertIn(("PassThruClose", 0xD1), lib.calls)


if __name__ == "__main__":
    unittest.main()
