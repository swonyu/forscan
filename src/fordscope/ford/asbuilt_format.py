"""Ford As-Built block format — parse, edit, checksum.

A Ford As-Built block is presented as ``{module}-{block}-{sub}: <data bytes> <cksum>``
e.g. ``726-01-01: 12 34 56 [64]``. This module models one block as (label, data,
checksum) and provides safe editing that recomputes the checksum — so a change to
a feature bit produces a block that will still validate.

CHECKSUM HONESTY: this implements the common **sum-to-zero mod 256** convention
(``(sum(data) + checksum) & 0xFF == 0``). Ford's exact per-block algorithm can
differ; the *editing + re-checksum machinery* is the value here, and the concrete
polynomial is confirm-on-vehicle (NEEDS ON-CAR CHECK). ``compute_checksum`` is
overridable if a module uses a different rule.
"""
from __future__ import annotations

from dataclasses import dataclass


def compute_checksum(data: bytes) -> int:
    """Sum-to-zero mod 256: checksum such that (sum(data) + checksum) & 0xFF == 0."""
    return (-sum(data)) & 0xFF


@dataclass(frozen=True)
class AsBuiltBlock:
    label: str       # e.g. "726-01-01"
    data: bytes      # payload bytes (excluding the checksum byte)
    checksum: int    # the checksum byte as read/stored

    @property
    def is_valid(self) -> bool:
        return (sum(self.data) + self.checksum) & 0xFF == 0

    def with_data(self, new_data: bytes) -> "AsBuiltBlock":
        """A copy with new data and a freshly-computed checksum."""
        d = bytes(new_data)
        return AsBuiltBlock(self.label, d, compute_checksum(d))

    def set_byte(self, index: int, value: int) -> "AsBuiltBlock":
        if not 0 <= index < len(self.data):
            raise IndexError(f"byte index {index} out of range for {len(self.data)}-byte block")
        d = bytearray(self.data)
        d[index] = value & 0xFF
        return self.with_data(bytes(d))

    def set_nibble(self, index: int, high: bool, value: int) -> "AsBuiltBlock":
        """Set the high or low nibble of one byte (value 0..15), re-checksumming."""
        if not 0 <= index < len(self.data):
            raise IndexError(f"byte index {index} out of range for {len(self.data)}-byte block")
        if not 0 <= value <= 0x0F:
            raise ValueError(f"nibble value must be 0..15, got {value}")
        current = self.data[index]
        if high:
            new = (value << 4) | (current & 0x0F)
        else:
            new = (current & 0xF0) | value
        return self.set_byte(index, new)

    def to_bytes(self) -> bytes:
        """The wire form: data followed by the checksum byte."""
        return self.data + bytes([self.checksum])

    def format(self) -> str:
        body = self.data.hex(" ").upper()
        flag = "" if self.is_valid else " (BAD CHECKSUM)"
        return f"{self.label}: {body} [{self.checksum:02X}]{flag}"


def parse_block(label: str, raw: bytes) -> AsBuiltBlock:
    """Parse raw block bytes (data... + 1 trailing checksum byte)."""
    if len(raw) < 1:
        raise ValueError("As-Built block needs at least a checksum byte")
    return AsBuiltBlock(label, bytes(raw[:-1]), raw[-1])
