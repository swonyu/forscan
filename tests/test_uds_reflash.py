"""UDS reflash transfer (0x34/0x36/0x37) — RequestDownload/TransferData/exit.

Transfer PROTOCOL only. No real calibration data or security is involved here;
the DANGER note lives on UdsClient.download. Tests use a tiny max block to force
multi-block transfers.
"""
import unittest

from fordscope.transport import SimulatorTransport
from fordscope.isotp import IsoTpSocket, SimulatedIsoTpEcu
from fordscope.uds import UdsClient, SimulatedUdsEcu, NegativeResponseError, UnexpectedResponseError
from fordscope.uds import services as S


def make_uds(**kw):
    ecu = SimulatedUdsEcu(**kw)
    isotp_ecu = SimulatedIsoTpEcu(ecu, request_id=0x7E0, response_id=0x7E8)
    bus = SimulatorTransport(isotp_ecu)
    bus.open()
    return UdsClient(IsoTpSocket(bus, tx_id=0x7E0, rx_id=0x7E8)), ecu


class RequestDownloadTests(unittest.TestCase):
    def test_returns_max_block_length(self):
        client, _ = make_uds(download_max_block=6)
        self.assertEqual(client.request_download(0x00801000, 100), 6)

    def test_rejects_short_max_block_length(self):
        # ECU declares a 2-byte maxNumberOfBlockLength but sends only 1 byte — must
        # raise, not silently return the truncated (wrong) value.
        class _Scripted:
            def send(self, payload):
                pass

            def recv(self, timeout=1.0):
                return bytes([0x74, 0x20, 0xFF])  # lengthFormatId high-nibble=2, 1 byte

        with self.assertRaises(UnexpectedResponseError):
            UdsClient(_Scripted()).request_download(0x1000, 0x100)


class TransferTests(unittest.TestCase):
    def test_full_transfer_reassembles_all_bytes(self):
        data = bytes(range(10))
        client, ecu = make_uds(download_max_block=6)  # chunk = 4 -> 4 + 4 + 2
        blocks = client.download(0x00801000, data)
        self.assertEqual(blocks, 3)
        self.assertEqual(ecu.last_download, (0x00801000, data))

    def test_single_block_transfer(self):
        data = bytes([0xAA, 0xBB])
        client, ecu = make_uds()  # large default max block
        blocks = client.download(0x2000, data)
        self.assertEqual(blocks, 1)
        self.assertEqual(ecu.last_download[1], data)

    def test_block_sequence_wraps_past_255(self):
        # ISO 14229: the TransferData blockSequenceCounter starts at 0x01 and wraps
        # 0xFF -> 0x00. A real module reflash is hundreds of KB, so ANY real transfer
        # crosses that boundary -- yet nothing else here exceeds a few blocks. Force
        # >255 one-byte blocks (max_block=3 -> chunk=max(1,3-2)=1) and require every
        # byte to land in order across the wrap. Teeth: if the client's
        # `seq = (seq+1) & 0xFF` OR the ECU's own wrap were wrong, block 256's counter
        # mismatches and the ECU returns NRC_WRONG_BLOCK_SEQUENCE_COUNTER -> raises.
        data = bytes((i * 37) & 0xFF for i in range(300))  # 300 blocks, distinctive
        client, ecu = make_uds(download_max_block=3)
        blocks = client.download(0x00801000, data)
        self.assertEqual(blocks, 300)                       # 300 > 255 -> wrapped once
        self.assertEqual(ecu.last_download, (0x00801000, data))  # byte-exact across wrap


class TransferFailureTests(unittest.TestCase):
    def test_wrong_block_sequence(self):
        client, _ = make_uds(download_max_block=6)
        client.request_download(0x1000, 10)
        client.transfer_data(1, b"\x00\x00")  # ok; next expected is 2
        with self.assertRaises(NegativeResponseError) as ctx:
            client.transfer_data(5, b"\x00")
        self.assertEqual(ctx.exception.nrc, S.NRC_WRONG_BLOCK_SEQUENCE_COUNTER)

    def test_transfer_before_request_download(self):
        client, _ = make_uds(download_max_block=6)
        with self.assertRaises(NegativeResponseError) as ctx:
            client.transfer_data(1, b"\x00")
        self.assertEqual(ctx.exception.nrc, S.NRC_REQUEST_SEQUENCE_ERROR)

    def test_exit_before_request_download(self):
        client, _ = make_uds(download_max_block=6)
        with self.assertRaises(NegativeResponseError) as ctx:
            client.request_transfer_exit()
        self.assertEqual(ctx.exception.nrc, S.NRC_REQUEST_SEQUENCE_ERROR)


if __name__ == "__main__":
    unittest.main()
