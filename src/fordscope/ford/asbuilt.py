"""Ford As-Built coding — configuration read/write with backup-before-write.

As-Built data is module configuration stored in blocks (addressed by DID). Coding
a feature = read a block, change bytes, write it back. The one non-negotiable
safety rule of this whole tool lives here:

    **No write is permitted unless the block's ORIGINAL value was read and
    persisted first**, and every write is confirmed by reading it back. That is
    the difference between "customised my cluster" and "bricked my module".

SAFETY / on-car reality: a real Ford As-Built write also requires an extended
diagnostic session and SecurityAccess (0x27, not built yet). This coder enters
the extended session; SecurityAccess unlocking is a prerequisite the real
hardware path must satisfy — NEEDS ON-CAR CHECK. Simulator-tested only here.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from ..uds.services import SESSION_EXTENDED
from .asbuilt_format import AsBuiltBlock, parse_block


class AsBuiltError(Exception):
    """Base class for As-Built coding failures."""


class BackupRequiredError(AsBuiltError):
    """A write was attempted without first capturing a backup of the block."""


class VerificationError(AsBuiltError):
    """A read-back after a write did not match what was written."""


class NoBackupError(AsBuiltError):
    """A restore was requested but no backup exists for that block."""


# --- backup stores -----------------------------------------------------
class InMemoryBackupStore:
    def __init__(self) -> None:
        self._data: Dict[str, bytes] = {}

    def has(self, key: str) -> bool:
        return key in self._data

    def save(self, key: str, data: bytes) -> None:
        self._data[key] = bytes(data)

    def load(self, key: str) -> Optional[bytes]:
        return self._data.get(key)

    def keys(self) -> List[str]:
        return list(self._data)


class FileBackupStore:
    """Durable JSON-backed store so backups survive across sessions."""

    def __init__(self, path: str) -> None:
        self.path = str(path)
        self._data: Dict[str, bytes] = {}
        if os.path.exists(self.path):
            with open(self.path, "r") as fh:
                raw = json.load(fh)
            self._data = {k: bytes.fromhex(v) for k, v in raw.items()}

    def _flush(self, data: Dict[str, bytes]) -> None:
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # ATOMIC write: serialize to a temp file in the SAME directory, fsync, then
        # os.replace() (atomic). An interrupted/failed write can then never truncate
        # or corrupt the existing backup file — which holds every module's
        # factory-original bytes, the one durable recovery path for an As-Built write.
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({k: v.hex() for k, v in data.items()}, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def has(self, key: str) -> bool:
        return key in self._data

    def save(self, key: str, data: bytes) -> None:
        # Persist FIRST, commit in-memory only after a durable write — so a failed
        # flush never leaves has()==True for a backup that isn't actually on disk
        # (which would let write_block proceed with no real recovery path).
        candidate = dict(self._data)
        candidate[key] = bytes(data)
        self._flush(candidate)
        self._data = candidate

    def load(self, key: str) -> Optional[bytes]:
        return self._data.get(key)

    def keys(self) -> List[str]:
        return list(self._data)


# --- the coder ---------------------------------------------------------
class AsBuiltCoder:
    def __init__(
        self,
        uds_client,
        store,
        *,
        scope: str = "",
        enter_extended_session: bool = True,
    ) -> None:
        self.uds = uds_client
        self.store = store
        self.scope = scope  # e.g. a VIN or module name — namespaces the backups
        self.enter_extended_session = enter_extended_session

    def _key(self, did: int) -> str:
        return f"{self.scope}:{did:04X}"

    def read_block(self, did: int) -> bytes:
        return self.uds.read_data_by_identifier(did)

    def has_backup(self, did: int) -> bool:
        return self.store.has(self._key(did))

    def backup_block(self, did: int, *, force: bool = False) -> bytes:
        """Persist the current block as the restore-to-original baseline and return it.

        The FIRST captured value is IMMUTABLE: if a backup already exists this returns
        it unchanged rather than re-reading the (possibly already-modified) block and
        clobbering the factory original — otherwise coding a shared block a second time
        would destroy the only recovery data (restore would return a modified state,
        not factory). Pass ``force=True`` only to deliberately re-baseline.
        """
        key = self._key(did)
        if not force and self.store.has(key):
            return self.store.load(key)
        data = self.read_block(did)
        self.store.save(key, data)
        return data

    def _prepare_session(self) -> None:
        if self.enter_extended_session:
            self.uds.diagnostic_session_control(SESSION_EXTENDED)

    def write_block(self, did: int, data: bytes) -> None:
        """Write a block. REFUSES unless a backup exists; verifies by read-back. The
        backup gate is UNCONDITIONAL — there is deliberately no bypass parameter, so
        the tool's non-negotiable backup-before-write rule can't be silently disabled."""
        if not self.has_backup(did):
            raise BackupRequiredError(
                f"refusing to write DID 0x{did:04X}: capture a backup first "
                f"(backup_block or code_block)"
            )
        self._prepare_session()
        self.uds.write_data_by_identifier(did, data)
        readback = self.read_block(did)
        if readback != bytes(data):
            raise VerificationError(
                f"read-back mismatch on DID 0x{did:04X}: wrote {bytes(data).hex()}, "
                f"read {readback.hex()}"
            )

    def code_block(self, did: int, new_data: bytes) -> bytes:
        """The safe path: backup original -> write -> verify. Returns the backup."""
        original = self.backup_block(did)
        self.write_block(did, new_data)
        return original

    def restore_block(self, did: int) -> None:
        """Write the saved backup back and verify."""
        backup = self.store.load(self._key(did))
        if backup is None:
            raise NoBackupError(f"no backup on file for DID 0x{did:04X}")
        self._prepare_session()
        self.uds.write_data_by_identifier(did, backup)
        readback = self.read_block(did)
        if readback != backup:
            raise VerificationError(f"restore verify failed on DID 0x{did:04X}")

    # --- structured As-Built ------------------------------------------
    def read_as_built(self, did: int, label: str) -> AsBuiltBlock:
        """Read a DID and parse it as a Ford As-Built block (data + checksum)."""
        return parse_block(label, self.read_block(did))

    def code_as_built(self, did: int, block: AsBuiltBlock) -> bytes:
        """Safely write an edited As-Built block (backup -> write -> verify)."""
        return self.code_block(did, block.to_bytes())
