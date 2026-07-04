"""Named As-Built features — map a human feature to a block + byte/nibble + value.

A ``FeatureDefinition`` says: feature "fog lights as DRL" lives in As-Built block
``726-01-01`` (a DID), byte 2, high nibble, where 0x0 = off and 0x4 = on. With
that, a ``FeatureCoder`` can read the current setting and apply a named option
through the safe backup→write→verify path.

⚠️ AUTHORITATIVE: the *mechanism* below (locate/read/apply a value in a block).
NOT AUTHORITATIVE: the concrete ``EXAMPLE_FEATURES`` mappings — real As-Built
feature locations are proprietary, differ by model/year, and are community
reverse-engineered. They ship here ONLY as illustrative examples, each flagged
unverified. Confirm any mapping against your own vehicle before applying it
(NEEDS ON-CAR CHECK). Supply your own verified definitions for real use.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from .asbuilt_format import AsBuiltBlock


@dataclass(frozen=True)
class FeatureDefinition:
    key: str                 # stable id, e.g. "fog_drl"
    name: str                # human name
    module: str              # e.g. "BCM"
    did: int                 # As-Built block DID
    label: str               # human block label, e.g. "726-01-01"
    byte_index: int          # which byte within the block data
    nibble: Optional[str]    # "high" | "low" | None (whole byte)
    options: Dict[str, int]  # option name -> value
    note: str = ""           # provenance / caveat

    def _read_value(self, block: AsBuiltBlock) -> int:
        b = block.data[self.byte_index]
        if self.nibble == "high":
            return (b >> 4) & 0x0F
        if self.nibble == "low":
            return b & 0x0F
        return b

    def current_option(self, block: AsBuiltBlock) -> Optional[str]:
        """Name of the option matching the block's current value, or None."""
        value = self._read_value(block)
        for name, v in self.options.items():
            if v == value:
                return name
        return None

    def apply(self, block: AsBuiltBlock, option_name: str) -> AsBuiltBlock:
        """Return a new block with this feature set to ``option_name`` (re-checksummed)."""
        if option_name not in self.options:
            raise KeyError(
                f"feature {self.key!r} has no option {option_name!r} "
                f"(choices: {sorted(self.options)})"
            )
        value = self.options[option_name]
        if self.nibble == "high":
            return block.set_nibble(self.byte_index, True, value)
        if self.nibble == "low":
            return block.set_nibble(self.byte_index, False, value)
        return block.set_byte(self.byte_index, value)


class FeatureCoder:
    """Read/apply named features against a module via an ``AsBuiltCoder``."""

    def __init__(self, coder, features: Dict[str, FeatureDefinition]) -> None:
        self.coder = coder
        self.features = features

    def _definition(self, key: str) -> FeatureDefinition:
        if key not in self.features:
            raise KeyError(f"unknown feature {key!r}")
        return self.features[key]

    def read_feature(self, key: str):
        """Return (definition, current_option_name) for a feature."""
        d = self._definition(key)
        block = self.coder.read_as_built(d.did, d.label)
        return d, d.current_option(block)

    def set_feature(self, key: str, option_name: str) -> bytes:
        """Apply an option through the safe backup→write→verify path. Returns the backup."""
        d = self._definition(key)
        block = self.coder.read_as_built(d.did, d.label)
        new_block = d.apply(block, option_name)
        return self.coder.code_as_built(d.did, new_block)

    def restore_feature(self, key: str) -> None:
        """Undo: write the feature block's saved backup back and verify."""
        d = self._definition(key)
        self.coder.restore_block(d.did)


# --- EXAMPLE feature map — UNVERIFIED, confirm on-vehicle before use ------
_UNVERIFIED = "EXAMPLE mapping — UNVERIFIED. Byte/nibble locations vary by model/year; confirm on your vehicle."

EXAMPLE_FEATURES: Dict[str, FeatureDefinition] = {
    "fog_drl": FeatureDefinition(
        key="fog_drl", name="Fog lights as daytime running lights", module="BCM",
        did=0xDE01, label="726-01-01", byte_index=2, nibble="high",
        options={"off": 0x0, "on": 0x4}, note=_UNVERIFIED,
    ),
    "gauge_sweep": FeatureDefinition(
        key="gauge_sweep", name="Instrument-cluster gauge sweep on start", module="IPC",
        did=0xDE10, label="720-02-01", byte_index=1, nibble="low",
        options={"off": 0x0, "on": 0x1}, note=_UNVERIFIED,
    ),
    "double_honk": FeatureDefinition(
        key="double_honk", name="Double-honk lock confirmation", module="BCM",
        did=0xDE02, label="726-03-01", byte_index=0, nibble="low",
        options={"off": 0x0, "on": 0x2}, note=_UNVERIFIED,
    ),
}
