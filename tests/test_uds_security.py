"""UDS SecurityAccess (0x27) — seed/key handshake + failure modes.

The key algorithm is a trivial demo (XOR 0x5A) so the PROTOCOL is testable. This
is NOT a real Ford algorithm — FordScope never ships or cracks one.
"""
import unittest

from fordscope.transport import SimulatorTransport
from fordscope.isotp import IsoTpSocket, SimulatedIsoTpEcu
from fordscope.uds import UdsClient, SimulatedUdsEcu, NegativeResponseError
from fordscope.uds import services as S

SEED = b"\x11\x22\x33\x44"


def xor5a(seed):
    return bytes(b ^ 0x5A for b in seed)


def identity(seed):  # deliberately wrong key function
    return bytes(seed)


def make_uds(**kw):
    ecu = SimulatedUdsEcu(**kw)
    isotp_ecu = SimulatedIsoTpEcu(ecu, request_id=0x7E0, response_id=0x7E8)
    bus = SimulatorTransport(isotp_ecu)
    bus.open()
    return UdsClient(IsoTpSocket(bus, tx_id=0x7E0, rx_id=0x7E8)), ecu


class HandshakeTests(unittest.TestCase):
    def test_request_seed_returns_the_seed(self):
        client, _ = make_uds(security_key=xor5a, security_seed=SEED)
        self.assertEqual(client.request_seed(0x01), SEED)

    def test_unlock_with_correct_key(self):
        client, ecu = make_uds(security_key=xor5a, security_seed=SEED)
        client.unlock(xor5a, 0x01)
        self.assertIn(0x01, ecu.unlocked_levels)

    def test_unlock_with_wrong_key_raises_invalid_key(self):
        client, ecu = make_uds(security_key=xor5a, security_seed=SEED)
        with self.assertRaises(NegativeResponseError) as ctx:
            client.unlock(identity, 0x01)
        self.assertEqual(ctx.exception.nrc, S.NRC_INVALID_KEY)
        self.assertNotIn(0x01, ecu.unlocked_levels)

    def test_already_unlocked_returns_zero_seed(self):
        client, _ = make_uds(security_key=xor5a, security_seed=SEED)
        client.unlock(xor5a, 0x01)
        self.assertFalse(any(client.request_seed(0x01)))  # zero seed
        client.unlock(xor5a, 0x01)  # no key sent, no exception


class FailureModeTests(unittest.TestCase):
    def test_key_before_seed_is_sequence_error(self):
        client, _ = make_uds(security_key=xor5a, security_seed=SEED)
        with self.assertRaises(NegativeResponseError) as ctx:
            client.send_key(0x02, b"\x00\x00\x00\x00")
        self.assertEqual(ctx.exception.nrc, S.NRC_REQUEST_SEQUENCE_ERROR)

    def test_exceed_attempts(self):
        client, _ = make_uds(security_key=xor5a, security_seed=SEED, security_max_attempts=3)
        client.request_seed(0x01)
        for _ in range(2):
            with self.assertRaises(NegativeResponseError) as ctx:
                client.send_key(0x02, b"\xFF\xFF\xFF\xFF")
            self.assertEqual(ctx.exception.nrc, S.NRC_INVALID_KEY)
        with self.assertRaises(NegativeResponseError) as ctx:
            client.send_key(0x02, b"\xFF\xFF\xFF\xFF")
        self.assertEqual(ctx.exception.nrc, S.NRC_EXCEED_NUMBER_OF_ATTEMPTS)

    def test_no_security_configured(self):
        client, _ = make_uds()  # security_key defaults to None
        with self.assertRaises(NegativeResponseError) as ctx:
            client.request_seed(0x01)
        self.assertEqual(ctx.exception.nrc, S.NRC_SUBFUNCTION_NOT_SUPPORTED)

    def test_unsupported_level(self):
        client, _ = make_uds(security_key=xor5a, security_levels=(0x01,))
        with self.assertRaises(NegativeResponseError) as ctx:
            client.request_seed(0x03)  # level not offered
        self.assertEqual(ctx.exception.nrc, S.NRC_SUBFUNCTION_NOT_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
