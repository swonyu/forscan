"""Read-only query + format layer over the community As-Built catalog
(``fusion_2016_asbuilt.FUSION_2016_ASBUILT``).

HONESTY: this module is DISPLAY ONLY. It filters and formats the existing, static
``AsBuiltFeatureRef`` tuple — it never reads/writes a live vehicle, never invents a UDS
DID, and never computes anything that gets sent to a car. Every render includes the
UNVERIFIED / NEEDS-ON-CAR-CHECK caveat, the ``SOURCE`` provenance string, and each
feature's own ``module_confidence`` — no code path in here may omit them, including the
empty/no-match case, so a filtered view can never be mistaken for verified data.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Union

from .fusion_2016_asbuilt import AsBuiltFeatureRef, SOURCE

_HEADER = "COMMUNITY-SOURCED · UNVERIFIED · NEEDS ON-CAR CHECK"
# Public alias so other layers (e.g. the webapp JSON API) can carry the identical
# caveat text without duplicating the literal or reaching into a private name.
CATALOG_CAVEAT = _HEADER


def _module_matches(feature: AsBuiltFeatureRef, module: Union[str, int]) -> bool:
    """True if ``module`` (a name like "BCM"/"IPC", or a numeric/hex address) identifies
    this feature's module. Name matching is case-insensitive; address matching accepts an
    int or a hex string (with or without a leading "0x")."""
    if isinstance(module, int):
        return feature.module_addr == module
    text = module.strip()
    if not text:
        return True
    # Try it as a hex address first ("726" or "0x726"); a module NAME like "BCM" is not
    # valid hex-with-0x but plain "ABС"-style letters could theoretically parse as hex
    # digits (e.g. "ACE"), so only take the numeric branch for an explicit "0x" prefix or
    # a string that is ENTIRELY hex digits AND long enough to plausibly be an 11-bit
    # address (module names in this catalog are 2-5 letters, not hex-digit-only strings
    # like "726"); to keep this unambiguous we require the string to parse as hex AND be
    # numeric-looking (starts with a digit or "0x").
    lowered = text.lower()
    if lowered.startswith("0x") or (text[0].isdigit()):
        try:
            return feature.module_addr == int(text, 16)
        except ValueError:
            return False
    return feature.module.lower() == lowered


def _search_matches(feature: AsBuiltFeatureRef, search: str) -> bool:
    needle = search.strip().lower()
    if not needle:
        return True
    return needle in feature.name.lower() or needle in feature.key.lower()


def filter_features(
    catalog: Sequence[AsBuiltFeatureRef] = (),
    *,
    module: Optional[Union[str, int]] = None,
    search: Optional[str] = None,
) -> List[AsBuiltFeatureRef]:
    """Filter ``catalog`` by module (name or numeric address) AND/OR a case-insensitive
    substring search over name+key. Both filters are ANDed. No match -> ``[]`` (never
    raises). Pure: does not read or modify the catalog or any vehicle."""
    out = list(catalog)
    if module is not None:
        out = [f for f in out if _module_matches(f, module)]
    if search is not None:
        out = [f for f in out if _search_matches(f, search)]
    return out


def _group_by_module(features: Iterable[AsBuiltFeatureRef]):
    """Group features by (module_addr, module) preserving first-seen order — does not
    sort or otherwise reorder the underlying catalog."""
    order: List[tuple] = []
    groups: dict = {}
    for f in features:
        gk = (f.module_addr, f.module)
        if gk not in groups:
            groups[gk] = []
            order.append(gk)
        groups[gk].append(f)
    return [(gk, groups[gk]) for gk in order]


def format_catalog(
    catalog: Sequence[AsBuiltFeatureRef] = (),
    *,
    module: Optional[Union[str, int]] = None,
    search: Optional[str] = None,
) -> str:
    """Render a human-readable listing of the (optionally filtered) catalog.

    Every render — including a narrow filter or an empty/no-match result — begins with the
    prominent honesty header and the ``SOURCE`` provenance line, so no path can present
    community data as verified. Grouped by module; each feature line shows its name,
    block_line, "<module> (<module_confidence>)", its bits mask, then each option as
    "value = meaning".
    """
    features = filter_features(catalog, module=module, search=search)
    lines = [_HEADER, SOURCE, ""]

    if not features:
        lines.append("No matching As-Built features.")
        return "\n".join(lines)

    for (addr, mod_name), group in _group_by_module(features):
        lines.append(f"[{mod_name} 0x{addr:X}]")
        for f in group:
            lines.append(
                f"  {f.name}  ({f.block_line})  {f.module} ({f.module_confidence})  "
                f"bits={f.bits}"
            )
            for value, meaning in f.options:
                lines.append(f"    {value} = {meaning}")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def format_block_line_lookup(
    block_line: str, features: Sequence[AsBuiltFeatureRef],
) -> str:
    """Render the reverse-lookup answer for a block-line label a user read off a
    FORScan screen: "what catalog feature(s) live at THIS specific line?"

    ``features`` is the caller's own ``features_at_block_line(block_line)`` result (kept
    as a parameter, not recomputed here, so this stays a pure formatter over data the
    caller already has -- consistent with ``format_catalog``'s filter/format split).

    Every render — including the no-match case — begins with the same honesty header +
    ``SOURCE`` provenance line as ``format_catalog``, so a reverse lookup can never be
    mistaken for verified/live data either. A block_line with no catalog entry renders a
    clean "reference only" message (still under the honesty header) rather than silently
    printing nothing, so the absence itself is communicated, not just implied.
    """
    lines = [_HEADER, SOURCE, "", f"Block line: {block_line.strip()}", ""]

    if not features:
        lines.append(
            "No catalog feature recorded at this line — reference only "
            "(absence from this community catalog is not evidence the line is unused)."
        )
        return "\n".join(lines).rstrip("\n") + "\n"

    for f in features:
        lines.append(f"  {f.name}  ({f.key})")
        lines.append(f"  module: {f.module} 0x{f.module_addr:X} ({f.module_confidence})")
        lines.append(f"  bits: {f.bits}   kind: {f.kind}")
        for value, meaning in f.options:
            lines.append(f"    {value} = {meaning}")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"
