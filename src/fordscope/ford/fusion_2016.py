"""2016 Ford Fusion S diagnostic profile — from adversarially-verified research.

Built from a 7-agent research pass with per-claim adversarial verification. Module
addresses carry a confidence tag; As-Built feature locations are COMMUNITY-SOURCED
reference notes (not executable feature maps — we don't have verified byte/nibble
detail, so we don't fabricate it). Backup-before-write applies to any coding.

SCOPE: 2016 pre-facelift Fusion, 2.5L I4, NO secure gateway. Do NOT apply this map
to 2017+ (facelift) or Fusion Hybrid — their topology/addresses differ.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .addressing import AddressPair, eleven_bit_module

SCOPE = "2016 Ford Fusion S (pre-facelift, 2.5L I4, no secure gateway)"

# Confidence tags:
#   confirmed          - well-established (ISO 15765-4 + Ford address, corroborated)
#   confirm-on-vehicle - address known but presence on THIS build unverified
#   plausible          - address plausible, presence unverified
_CONFIDENCE = {"confirmed", "confirm-on-vehicle", "plausible"}


@dataclass(frozen=True)
class ModuleEntry:
    name: str
    address: int          # 11-bit diagnostic request id (response = +8)
    confidence: str
    note: str = ""


FUSION_2016_MODULES: List[ModuleEntry] = [
    ModuleEntry("PCM", 0x7E0, "confirmed", "Powertrain (2.5L I4)"),
    ModuleEntry("ABS", 0x760, "confirmed"),
    ModuleEntry("RCM", 0x737, "confirmed", "Restraints"),
    ModuleEntry("APIM", 0x7D0, "confirmed", "SYNC / infotainment"),
    ModuleEntry("IPC", 0x720, "confirmed", "Instrument cluster"),
    ModuleEntry("BCM", 0x726, "confirmed", "Body Control / Smart Junction Box"),
    ModuleEntry("TCM", 0x7E1, "confirm-on-vehicle", "6F35 is PCM-controlled; may have no separate live node"),
    ModuleEntry("HVAC", 0x733, "confirm-on-vehicle", "base S manual A/C may be BCM-handled"),
    ModuleEntry("PAM", 0x736, "plausible", "presence unverified"),
    ModuleEntry("OCS", 0x765, "plausible", "presence unverified"),
    ModuleEntry("SCCM", 0x724, "plausible", "address confirmed, presence unverified"),
    ModuleEntry("PSCM", 0x730, "plausible", "address confirmed, presence unverified"),
]


def confirmed_modules() -> List[AddressPair]:
    """Address pairs for the CONFIRMED modules only — safe to scan with confidence."""
    return [
        eleven_bit_module(m.address, name=m.name)
        for m in FUSION_2016_MODULES
        if m.confidence == "confirmed"
    ]


def all_modules() -> List[AddressPair]:
    """Address pairs for every listed module (includes lower-confidence entries)."""
    return [eleven_bit_module(m.address, name=m.name) for m in FUSION_2016_MODULES]


@dataclass(frozen=True)
class AsBuiltNote:
    feature: str
    module: str
    block: str          # As-Built block label, e.g. "726-45"
    confidence: str     # "community" | "uncorroborated"
    note: str = ""


# COMMUNITY-SOURCED As-Built pointers — block-level only, NOT verified byte maps.
# Use these as a starting point (e.g. with FORScan, which shows the full block);
# always back up before writing and recompute the block checksum after editing.
# The two attribution corrections from verification are baked in.
FUSION_2016_ASBUILT_NOTES: List[AsBuiltNote] = [
    AsBuiltNote("Fog / DRL configuration", "BCM", "726-45 / 726-50", "community", "Fusion community-confirmed"),
    AsBuiltNote("Approach ('Bambi') lighting", "BCM", "726-27", "community", "Fusion community-confirmed"),
    AsBuiltNote("Walk-away lock honk", "BCM", "726-41-02", "community", "distinct from lock-chirp 726-38"),
    AsBuiltNote("Lock/unlock chirp", "BCM", "726-38", "community", "distinct from walk-away honk 726-41"),
    AsBuiltNote("Autolock speed / behavior", "IPC", "720-01-01", "community", "recompute block checksum after edit"),
    AsBuiltNote("Mirror dip on reverse", "IPC", "720-02-01", "community", "NOT trip-screen config"),
    AsBuiltNote("(uncorroborated)", "BCM", "726-01-02", "uncorroborated", "flagged doubtful; confirm before any use"),
    AsBuiltNote("(uncorroborated)", "BCM", "726-12-01", "uncorroborated", "flagged doubtful; confirm before any use"),
]
