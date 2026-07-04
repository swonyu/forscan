"""UDS reflash transfer (0x34/0x36/0x37) — RequestDownload/TransferData/exit.

Transfer PROTOCOL only. No real calibration data or security is involved here;
the DANGER note lives on UdsClient.download. Tests use a tiny max block to force
multi-block transfers.
"""
import unittest

from fordscope.transport import SimulatorTransport
from fordscope.isotp import IsoTpSocket, SimulatedIsoTpEcu
from fordscope.uds import UdsClient, SimulatedUdsEcu, NegativeResponseError
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
