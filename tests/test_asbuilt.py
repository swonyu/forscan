"""As-Built coding tests — the safety invariant is the star here.

The central rule under test: a write is REFUSED unless a backup was captured
first, and every write is read-back-verified. These are the guards that stop a
config write from bricking a module.
"""
import os
import tempfile
import unittest

from fordscope.transport import SimulatorTransport
from fordscope.isotp import IsoTpSocket, SimulatedIsoTpEcu
from fordscope.uds import UdsClient, SimulatedUdsEcu
from fordscope.uds import services as S
from fordscope.ford import (
    AsBuiltCoder,
    InMemoryBackupStore,
    FileBackupStore,
    AsBuiltError,
    BackupRequiredError,
    VerificationError,
    NoBackupError,
    CorruptBackupStoreError,
)

BLOCK_DID = 0x5000
ORIGINAL = bytes([0x01, 0x02, 0x03])
NEW = bytes([0xAA, 0xBB, 0xCC])


def make_coder(ecu=None, **coder_kwargs):
    ecu = ecu or SimulatedUdsEcu(dids={BLOCK_DID: ORIGINAL})
    isotp_ecu = SimulatedIsoTpEcu(ecu, request_id=0x726, response_id=0x72E)
    bus = SimulatorTransport(isotp_ecu)
    bus.open()
    client = UdsClient(IsoTpSocket(bus, tx_id=0x726, rx_id=0x72E))
    return AsBuiltCoder(client, InMemoryBackupStore(), scope="TESTVIN", **coder_kwargs), ecu


class CorruptingUdsEcu(SimulatedUdsEcu):
    """Stores the bitwise-inverted payload so a read-back never matches."""

    def _write_did(self, request):
        did = (request[1] << 8) | request[2]
        self.dids[did] = bytes(b ^ 0xFF for b in request[3:])
        return bytes([0x6E, request[1], request[2]])


class SafetyInvariantTests(unittest.TestCase):
    def test_write_without_backup_is_refused_and_makes_no_change(self):
        coder, ecu = make_coder()
        with self.assertRaises(BackupRequiredError):
            coder.write_block(BLOCK_DID, NEW)
        # The block must be untouched — the refusal happened before any write.
        self.assertEqual(ecu.dids[BLOCK_DID], ORIGINAL)

    def test_backup_then_write_is_allowed(self):
        coder, ecu = make_coder()
        coder.backup_block(BLOCK_DID)
        coder.write_block(BLOCK_DID, NEW)
        self.assertEqual(ecu.dids[BLOCK_DID], NEW)

    def test_write_block_has_no_backup_bypass(self):
        # The backup gate is the tool's non-negotiable rule — there must be NO
        # escape-hatch parameter (e.g. require_backup=False) that skips it.
        coder, _ = make_coder()
        with self.assertRaises(TypeError):
            coder.write_block(BLOCK_DID, NEW, require_backup=False)

    def test_read_back_mismatch_raises_verification_error(self):
        coder, ecu = make_coder(ecu=CorruptingUdsEcu(dids={BLOCK_DID: ORIGINAL}))
        coder.backup_block(BLOCK_DID)
        with self.assertRaises(VerificationError):
            coder.write_block(BLOCK_DID, NEW)


class BackupAndRestoreTests(unittest.TestCase):
    def test_backup_captures_current_value(self):
        coder, _ = make_coder()
        data = coder.backup_block(BLOCK_DID)
        self.assertEqual(data, ORIGINAL)
        self.assertTrue(coder.has_backup(BLOCK_DID))

    def test_code_block_backs_up_writes_and_returns_original(self):
        coder, ecu = make_coder()
        original = coder.code_block(BLOCK_DID, NEW)
        self.assertEqual(original, ORIGINAL)
        self.assertEqual(ecu.dids[BLOCK_DID], NEW)

    def test_code_block_enters_extended_session(self):
        coder, ecu = make_coder()
        coder.code_block(BLOCK_DID, NEW)
        self.assertEqual(ecu.session, S.SESSION_EXTENDED)

    def test_restore_puts_the_original_back(self):
        coder, ecu = make_coder()
        coder.code_block(BLOCK_DID, NEW)
        self.assertEqual(ecu.dids[BLOCK_DID], NEW)
        coder.restore_block(BLOCK_DID)
        self.assertEqual(ecu.dids[BLOCK_DID], ORIGINAL)

    def test_second_code_block_preserves_the_first_captured_original(self):
        # The factory-original backup is IMMUTABLE. Coding a block a SECOND time
        # must not re-capture the already-modified value and clobber the original —
        # else restore returns a modified state, not factory. (Normal Ford case:
        # one block holds several feature nibbles, so a block is coded >1 time.)
        coder, ecu = make_coder()
        coder.code_block(BLOCK_DID, NEW)                        # backup=ORIGINAL, block=NEW
        coder.code_block(BLOCK_DID, bytes([0xDE, 0xAD, 0xBE]))  # must NOT clobber backup
        coder.restore_block(BLOCK_DID)
        self.assertEqual(ecu.dids[BLOCK_DID], ORIGINAL)        # factory, not NEW/DEADBE

    def test_restore_without_backup_raises(self):
        coder, _ = make_coder()
        with self.assertRaises(NoBackupError):
            coder.restore_block(BLOCK_DID)


class FileBackupStoreTests(unittest.TestCase):
    def test_persists_across_instances(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backups.json")
            store = FileBackupStore(path)
            store.save("TESTVIN:5000", ORIGINAL)
            # A fresh instance from the same file must see the backup.
            reopened = FileBackupStore(path)
            self.assertTrue(reopened.has("TESTVIN:5000"))
            self.assertEqual(reopened.load("TESTVIN:5000"), ORIGINAL)

    def test_coder_with_file_store_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backups.json")
            coder, ecu = make_coder()
            coder.store = FileBackupStore(path)
            coder.code_block(BLOCK_DID, NEW)
            # Backup is on disk; a new coder over the same file can restore it.
            coder.restore_block(BLOCK_DID)
            self.assertEqual(ecu.dids[BLOCK_DID], ORIGINAL)

    def test_failed_flush_does_not_destroy_existing_backups(self):
        # A write interrupted mid-flush (disk full, crash, ^C) must NOT truncate the
        # file and destroy every previously-saved factory-original backup — the
        # existing file must survive intact (atomic write).
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backups.json")
            store = FileBackupStore(path)
            store.save("TESTVIN:5000", ORIGINAL)  # one real backup on disk
            with mock.patch("json.dump", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    store.save("TESTVIN:6000", NEW)  # flush fails mid-write
            # The original backup must still be intact and reloadable.
            reopened = FileBackupStore(path)
            self.assertEqual(reopened.load("TESTVIN:5000"), ORIGINAL)
            self.assertIsNone(reopened.load("TESTVIN:6000"))

    def test_failed_flush_does_not_poison_in_memory_state(self):
        # save() must persist BEFORE committing in-memory, so a failed flush never
        # leaves has()==True for a backup that was never durably written — otherwise
        # a later write_block() in the same process would be wrongly permitted.
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backups.json")
            store = FileBackupStore(path)
            with mock.patch("json.dump", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    store.save("TESTVIN:5000", ORIGINAL)
            self.assertFalse(store.has("TESTVIN:5000"))  # not persisted -> not "backed up"

    def test_corrupt_backup_file_fails_loud_as_typed_error(self):
        # The durable backup file is the ONE recovery path. If it is unreadable we must
        # FAIL LOUD (never silently start empty -> a later backup_block would capture
        # already-modified bytes as the "factory original"), but as a typed AsBuiltError
        # so callers catching AsBuiltError get an actionable message, not a raw traceback.
        for label, contents in [
            ("invalid-json", "{not valid json"),
            ("bad-hex", '{"TESTVIN:5000": "ZZZZ"}'),      # valid JSON, un-hex value
            ("non-dict-top", '["not", "a", "dict"]'),      # .items() would AttributeError
        ]:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as d:
                    path = os.path.join(d, "backups.json")
                    with open(path, "w") as fh:
                        fh.write(contents)
                    with self.assertRaises(CorruptBackupStoreError) as ctx:
                        FileBackupStore(path)
                    self.assertIsInstance(ctx.exception, AsBuiltError)  # catchable as AsBuiltError
                    self.assertIn(path, str(ctx.exception))             # actionable: names the file


if __name__ == "__main__":
    unittest.main()
