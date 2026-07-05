"""2016 Fusion (2.5L S, 2014+ MY) As-Built feature catalog — COMMUNITY-SOURCED, UNVERIFIED.

Transcribed from the 2GFusions "Ford As-Built Data Mods" sheet by DanMc85
(https://docs.google.com/spreadsheets/d/1yax6zfhZYj2joBczEeruqKh9X5Qhee3C0ngilqwTA7E/pubhtml,
forum thread tid=4573), retrieved 2026-07-05. The full transcription lives in
``docs/reference/asbuilt_2gfusions_fusion_2gen.md``.

⚠️ HONESTY: every entry here is **UNVERIFIED / NEEDS ON-CAR CHECK**. Block/line numbers, bit
positions, and option values are community reverse-engineered and differ by model year and by
model. This is a **reference catalog** (where a feature lives + its option values), NOT a live
executable feature map: the block→UDS-DID mapping is not on file, so these are deliberately not
wired to live read/write (see ``features.py`` for the live-coding mechanism). Any write still goes
through the backup-before-write path in ``ford/asbuilt.py``.

SCOPE: 2016 pre-facelift Fusion 2.5L S. Every entry carries a ``module_confidence`` mirroring
``fusion_2016.py``: features on the **confirmed** modules (BCM 0x726, IPC 0x720, APIM 0x7D0) are
tagged ``confirmed``; features on **plausible** modules (DDM 0x740, PDM 0x741, ACM 0x727, SCCM
0x724, FCIM 0x7A7, HSWM 0x714, FCDIM 0x7A5) are tagged ``plausible`` — their addresses are
community-standard but presence on the base 2.5L S is unverified and several are trim-dependent
(no premium/Sony audio, no heated steering wheel on a base S). The sheet's 2013-MY-*only* variants
use different block numbers and are intentionally excluded (they don't apply to a 2016).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

SOURCE = (
    "2GFusions 'Ford As-Built Data Mods' (DanMc85), "
    "https://docs.google.com/spreadsheets/d/1yax6zfhZYj2joBczEeruqKh9X5Qhee3C0ngilqwTA7E/pubhtml "
    "(tid=4573), retrieved 2026-07-05 — COMMUNITY-SOURCED, UNVERIFIED, NEEDS ON-CAR CHECK"
)

# All entries carry this caveat so nothing here is ever mistaken for verified data.
_CAVEAT = "community-sourced (2GFusions/DanMc85), UNVERIFIED — confirm on-vehicle before applying"


@dataclass(frozen=True)
class AsBuiltFeatureRef:
    """A single community As-Built feature pointer. Reference data, not a live coder input."""

    key: str                              # stable id, e.g. "global_windows_close"
    name: str                             # human name
    module: str                           # sheet module tag ("BCM"/"IPC"/"APIM"); BdyCM == BCM
    module_addr: int                      # 11-bit diagnostic request id, e.g. 0x726
    block_line: str                       # As-Built line label, e.g. "726-17-01"
    bits: str                             # sheet bit mask (x = ignore, X = change)
    kind: str                             # "nibble" | "byte" | "full_line"
    options: Tuple[Tuple[str, str], ...]  # (value_hex, meaning) pairs, faithful to the sheet
    my: str = "2014+"                     # model-year applicability (must cover 2016)
    verified: bool = False                # NEVER True for community data
    note: str = _CAVEAT
    module_confidence: str = "confirmed"  # mirrors fusion_2016's tag for this module_addr

    def address_bytes(self) -> Tuple[int, int, int, int]:
        """(addr_hi, addr_lo, block, line) parsed from ``block_line`` (all hex)."""
        mod, block, line = self.block_line.split("-")
        a = int(mod, 16)
        return (a >> 8) & 0xFF, a & 0xFF, int(block, 16), int(line, 16)


def additive_checksum(block_line: str, data: bytes) -> int:
    """The Ford As-Built per-line additive checksum = (sum of the four label bytes + the data
    bytes) mod 256.

    Hand-derived from the documented worked example (report §5): ``760-01-04 3733`` →
    07+60+01+04+37+33 = 0xD6. This is the community sheet's *full-line* convention (label bytes
    included); it is intentionally independent of ``asbuilt_format.compute_checksum`` so a test can
    cross-check the transcribed full-line values against the spec, not against other repo code.
    """
    mod, block, line = block_line.split("-")
    a = int(mod, 16)
    label = ((a >> 8) & 0xFF, a & 0xFF, int(block, 16), int(line, 16))
    return (sum(label) + sum(data)) & 0xFF


def parse_hex_bytes(text: str) -> bytes:
    """Parse a hex-bytes string flexibly: accepts a bare run of hex digits
    ("0101010101") or space-separated byte pairs ("01 01 01 01 01") -- both forms a
    user might paste from a forum post or FORScan export. Raises ``ValueError`` (never
    crashes with something less clear) on odd-length hex, non-hex characters, or empty
    input; never silently truncates or guesses.
    """
    compact = text.replace(" ", "")
    if not compact:
        raise ValueError("no hex digits given")
    return bytes.fromhex(compact)


@dataclass(frozen=True)
class AsBuiltLineCheck:
    """Result of checking a full As-Built line value's trailing checksum byte."""

    valid: bool               # True if the stored trailing byte matches the recomputed one
    expected_checksum: int    # what the checksum SHOULD be, per additive_checksum()
    actual_checksum: int      # the trailing byte as given in the line value


def verify_full_line(block_line: str, full_line_hex: str) -> AsBuiltLineCheck:
    """Validate a full As-Built line value: label ``block_line`` (e.g. "726-17-01") +
    a hex string of data bytes followed by one trailing checksum byte (e.g.
    "01010101014A", or the same with spaces). Recomputes the additive checksum over the
    label + data bytes and compares it to the trailing byte.

    HONESTY: this only re-derives the Ford As-Built per-line additive checksum (the one
    spec-derivable fact about a line). A VALID result means the trailing byte is
    internally consistent with the label+data -- it does NOT mean the data bytes
    themselves are the correct/safe values for any given vehicle (NEEDS ON-CAR CHECK).

    Raises ``ValueError`` on a malformed label (no "mod-block-line" dashes) or hex that
    doesn't parse (odd length, non-hex characters, or fewer than one byte total i.e. no
    room for a checksum byte) -- never crashes uninformatively or fabricates a result.
    """
    raw = parse_hex_bytes(full_line_hex)
    if len(raw) < 1:
        raise ValueError("full line value needs at least a trailing checksum byte")
    data, actual = raw[:-1], raw[-1]
    expected = additive_checksum(block_line, data)
    return AsBuiltLineCheck(valid=expected == actual, expected_checksum=expected, actual_checksum=actual)


# --- The catalog (2014+ MY, confirmed modules only) --------------------------
# Full-line values include the trailing additive-checksum byte; the checksum of every full_line
# option is verified against additive_checksum() in the test suite.
FUSION_2016_ASBUILT: Tuple[AsBuiltFeatureRef, ...] = (
    # --- Full-line entries (whole 6-byte block value incl. checksum) ---
    AsBuiltFeatureRef(
        "auto_relock_45s", "Auto relock doors if unlocked & not opened within 45 s",
        "BCM", 0x726, "726-15-02", "xXxX xXxX xXxx", "full_line",
        (("000000000044", "disabled"), ("010101010149", "enabled"),
         ("02020202024E", "locked out of IPC")),
    ),
    AsBuiltFeatureRef(
        "drl_ipc_control", "Allow DRL control from the instrument cluster",
        "BCM", 0x726, "726-16-02", "xXxX xXxX xXxx", "full_line",
        (("02020202024F", "IPC control locked out (2014 default)"),
         ("010101010049", "enabled — IPC control allowed")),
    ),
    AsBuiltFeatureRef(
        "global_windows_close", "Global windows remote close (fob)",
        "BCM", 0x726, "726-17-01", "xXxX xXxX xXxx", "full_line",
        (("01010101014A", "enabled (default)"), ("000000000045", "disabled")),
    ),
    AsBuiltFeatureRef(
        "global_windows_open", "Global windows remote open (fob)",
        "BCM", 0x726, "726-17-02", "xXxX xXxX xXxx", "full_line",
        (("01010101014B", "enabled (default)"), ("000000000046", "disabled")),
    ),
    # --- Nibble / byte entries (only the changed field's value) ---
    AsBuiltFeatureRef(
        "door_close_double_honk", "Door-close double horn honk (engine running, no fob / PTS)",
        "BCM", 0x726, "726-41-02", "xxxX xxxx xxxx", "nibble",
        (("1", "enabled (default)"), ("0", "disabled")),
    ),
    AsBuiltFeatureRef(
        "lock_honk_2x_fob", "Door-lock horn honk on 2× fob press",
        "BCM", 0x726, "726-38-02", "xxxX xxxx xxxx", "nibble",
        (("1", "enabled (default)"), ("0", "disabled")),
    ),
    AsBuiltFeatureRef(
        "bambi_mode", "Simultaneous high beams + fog lights (\"Bambi mode\")",
        "BCM", 0x726, "726-27-01", "xxxx xxxX xxxx", "nibble",
        (("1", "normal / disabled"), ("0", "simultaneous HB + fogs")),
    ),
    AsBuiltFeatureRef(
        "drl_mode", "Daytime running lights — mode",
        "BCM", 0x726, "726-50-01", "xXxx", "byte",
        (("01", "disabled / USA default"), ("02", "low beams"), ("04", "front fog"),
         ("08", "front turn"), ("10", "dedicated (BCM outputs)"), ("20", "high beams"),
         ("40", "low beams + dedicated")),
    ),
    AsBuiltFeatureRef(
        "drl_unlock_options", "Daytime running lights — unlock all option choices",
        "BCM", 0x726, "726-45-01", "xxxx XXxx xxxx", "byte",
        (("7F", "unlock all DRL options"),),
    ),
    AsBuiltFeatureRef(
        "oem_foglights_bcm", "Enable OEM fog lights (BCM half; also set IPC 720-01-02)",
        "BCM", 0x726, "726-45-02", "xxxx xXxx xxxx", "nibble",
        (("1", "present / enabled"), ("0", "disabled")),
    ),
    AsBuiltFeatureRef(
        "remote_start_system", "Factory remote start (system enable)",
        "BCM", 0x726, "726-22-02", "xxxX xxxx xxxx", "nibble",
        (("1", "enabled"), ("0", "disabled")),
    ),
    AsBuiltFeatureRef(
        "panic_alarm", "Panic alarm activation (key fob)",
        "BCM", 0x726, "726-37-01", "xxxx xxxX xxxx", "nibble",
        (("2", "one-press (default)"), ("1", "two consecutive presses"), ("0", "disabled")),
    ),
    AsBuiltFeatureRef(
        "battery_monitoring_system", "Battery Monitoring System (BMS)",
        "BCM", 0x726, "726-04-01", "xxxX xxxx xxxx", "nibble",
        (("2", "enabled (default)"), ("0", "disabled (may lower MPG)")),
    ),
    AsBuiltFeatureRef(
        "awd_gauge", "All-wheel-drive gauge in cluster",
        "IPC", 0x720, "720-01-01", "xxxx xXxx xxxx", "nibble",
        (("0", "disabled (default)"), ("2", "enabled")),
    ),
    AsBuiltFeatureRef(
        "tpms_gauge", "Tire-pressure (TPMS) gauge in cluster",
        "IPC", 0x720, "720-04-01", "xXxx xxxx xxxx", "nibble",
        (("0", "disabled"), ("4", "enabled")), my="2015+",
    ),
    AsBuiltFeatureRef(
        "digital_speedometer", "Digital speedometer gauge",
        "IPC", 0x720, "720-07-01", "xxxX xxxx xxxx", "nibble",
        (("0", "disabled"), ("1", "enabled")), my="2015+",
    ),
    AsBuiltFeatureRef(
        "disable_welcome_screen", "Disable IPC welcome (blue-sky) screen",
        "IPC", 0x720, "720-03-02", "xxxX xxxx", "nibble",
        (("C", "enabled (default)"), ("4", "disabled")),
    ),
    AsBuiltFeatureRef(
        "reverse_camera", "Enable reverse camera (Sync 2/3, 8\" display)",
        "APIM", 0x7D0, "7D0-01-01", "xXxx xxxx xxxx", "nibble",
        (("0", "disabled"), ("2", "enabled"), ("A", "enabled w/ side obstacle (2017 only)")),
    ),
    # --- Plausible modules: addresses community-standard, presence on a base 2.5L S UNVERIFIED ---
    AsBuiltFeatureRef(
        "sunroof_comfort_vent", "Sunroof comfort (one-touch) vent closure",
        "DDM", 0x740, "740-05-01", "xxXx xx", "nibble",
        (("0", "disabled (default)"), ("4", "enabled")),
        my="2013-2016", module_confidence="plausible",
        note="community-sourced, UNVERIFIED; also mirrored at PDM 741-05-01",
    ),
    AsBuiltFeatureRef(
        "reverse_mirror_tilt_ddm", "Reverse side-mirror tilt — driver mirror",
        "DDM", 0x740, "740-03-01", "Xxxx xx", "nibble",
        (("6", "disabled (default)"), ("7", "enabled")),
        my="2013+", module_confidence="plausible",
        note="community-sourced, UNVERIFIED; pair with 740-13-01 + passenger 741-03/13-01",
    ),
    AsBuiltFeatureRef(
        "reverse_mirror_tilt_ddm_enable", "Reverse side-mirror tilt — driver enable byte",
        "DDM", 0x740, "740-13-01", "XXxx", "byte",
        (("00", "disabled (default)"), ("FC", "enabled")),
        my="2013+", module_confidence="plausible", note="community-sourced, UNVERIFIED",
    ),
    AsBuiltFeatureRef(
        "reverse_mirror_tilt_pdm", "Reverse side-mirror tilt — passenger mirror",
        "PDM", 0x741, "741-03-01", "Xxxx xx", "nibble",
        (("6", "disabled (default)"), ("7", "enabled")),
        my="2013+", module_confidence="plausible", note="community-sourced, UNVERIFIED",
    ),
    AsBuiltFeatureRef(
        "reverse_mirror_tilt_pdm_enable", "Reverse side-mirror tilt — passenger enable byte",
        "PDM", 0x741, "741-13-01", "XXxx", "byte",
        (("00", "disabled (default)"), ("FC", "enabled")),
        my="2013+", module_confidence="plausible", note="community-sourced, UNVERIFIED",
    ),
    AsBuiltFeatureRef(
        "audio_line_level_output", "Audio output type / variable line-level preamp",
        "ACM", 0x727, "727-01-01", "xxXX xxxx xxxx", "byte",
        (("00", "regular speakers (default)"), ("A0", "Sony DSP (factory)"),
         ("59", "variable line-level w/ subwoofer aux")),
        my="2013+", module_confidence="plausible",
        note="community-sourced, UNVERIFIED; premium/Sony audio likely absent on base S",
    ),
    AsBuiltFeatureRef(
        "turn_signal_flash_count", "Automatic (one-touch) turn-signal flash count",
        "SCCM", 0x724, "724-01-01", "xxxx xXxx xx", "nibble",
        (("0", "1 flash"), ("4", "2"), ("6", "3 (default)"), ("8", "4"),
         ("A", "5"), ("C", "6"), ("E", "7")),
        module_confidence="plausible", note="community-sourced, UNVERIFIED",
    ),
    AsBuiltFeatureRef(
        "heated_wheel_support", "Heated steering wheel — vehicle support",
        "FCIM", 0x7A7, "7A7-01-02", "xxxX xxxx xxxx", "nibble",
        (("0", "disabled"), ("8", "enabled")),
        my="2013+", module_confidence="plausible",
        note="community-sourced, UNVERIFIED; requires HSW hardware + HSWM (absent on base S)",
    ),
    AsBuiltFeatureRef(
        "heated_wheel_temp", "Heated steering wheel — temperature",
        "HSWM", 0x714, "714-02-01", "xxXX XXXX xx", "bytes",
        (("444444", "68°F (2013–2015 default)"), ("4C4C4C", "76°F"), ("545454", "84°F"),
         ("585858", "88°F"), ("5A5A5A", "90°F"), ("5C5C5C", "92°F (2016/2017 Fusion default)"),
         ("5E5A5E", "94°F"), ("646464", "100°F (MKZ default)")),
        my="2013+", module_confidence="plausible",
        note="community-sourced, UNVERIFIED; HSWM likely absent on base 2.5L S",
    ),
    AsBuiltFeatureRef(
        "reverse_camera_basic_display", "Enable reverse camera — basic Sync (4\" display)",
        "FCDIM", 0x7A5, "7A5-01-01", "xXxx xxxx xxxx", "nibble",
        (("0", "disabled"), ("2", "enabled")),
        my="2013+", module_confidence="plausible",
        note="community-sourced, UNVERIFIED; 4\" display has no side-obstacle 'A' option",
    ),
)


def features_at_block_line(
    block_line: str, catalog: Sequence[AsBuiltFeatureRef] = FUSION_2016_ASBUILT,
) -> List[AsBuiltFeatureRef]:
    """Reverse lookup: every catalog feature whose ``block_line`` matches the given label
    (e.g. "726-17-01", as read off a FORScan screen or a forum post).

    Matching is case-insensitive (block labels use uppercase hex for multi-digit module
    addresses, e.g. "7D0-01-01") and tolerant of leading/trailing whitespace a user might
    paste in. No match, an empty/whitespace-only input, or a garbage string all degrade
    cleanly to ``[]`` -- this NEVER raises, so a lookup UI never crashes on a bad paste.
    Pure: does not read/write a live vehicle or mutate the catalog.
    """
    needle = block_line.strip().lower()
    if not needle:
        return []
    return [f for f in catalog if f.block_line.lower() == needle]
