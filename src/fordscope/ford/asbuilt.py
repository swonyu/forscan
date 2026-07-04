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

    def _flush(self) -> None:
        with open(self.path, "w") as fh:
            json.dump({k: v.hex() for k, v in self._data.items()}, fh, indent=2)

    def has(self, key: str) -> bool:
        return key in self._data

    def save(self, key: str, data: bytes) -> None:
        self._data[key] = bytes(data)
        self._flush()

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

    def backup_block(self, did: int) -> bytes:
        """Read the current block and persist it. Returns the backed-up bytes."""
        data = self.read_block(did)
        self.store.save(self._key(did), data)
        return data

    def _prepare_session(self) -> None:
        if self.enter_extended_session:
            self.uds.diagnostic_session_control(SESSION_EXTENDED)

    def write_block(self, did: int, data: bytes, *, require_backup: bool = True) -> None:
        """Write a block. REFUSES unless a backup exists; verifies by read-back."""
        if require_backup and not self.has_backup(did):
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
