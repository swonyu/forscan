# Research — Ford / OBD-II diagnostics reference (2016 Fusion)  ·  2026-07-04

Deep-research run (fan-out web search → fetch → 3-vote adversarial verification → synthesis),
scoped to the FordScope charter. **Read the honesty note before using any of this.**

## ⚠️ Honesty note — what is verified vs still open
The run was **partially rate-limited**. Only **7 claims survived 3-vote verification**, and they are
**confined to the adapter / host-platform layer**. The four *core diagnostic* angles this research
most wanted —
1. Ford enhanced PIDs & module diagnostic addresses,
2. As-Built data block format & safe re-coding,
3. per-monitor drive-cycle completion conditions,
4. Mode 06 TID/MID interpretation —
**produced ZERO surviving verified claims.** Their verifiers **failed on infrastructure
rate-limiting, NOT on refutation**, so those topics remain **genuinely OPEN**. Do **not** build
R3 (drive-cycle coach) or R5 (Mode 06 decode) on this run — re-run those angles when rate-limits
clear (serialized, not overlapping another big workflow).

## ✅ Verified findings (survived 3-vote adversarial verification)

### V1 — MS-CAN switching is required for Ford comfort modules  · HIGH
Ford comfort/convenience modules (BCM/SJB, HVAC, ACM/DSP, DSM, DDM, RFA, FCIM, FDIM) sit on
**MS-CAN** (DLC pins 3/11), unreachable by a generic HS-CAN OBD-II adapter. Both the **OBDLink EX**
and the **Vgate vLinker FS** provide **electronic HS-CAN/MS-CAN switching**, which is what FORScan
needs to reach those modules. The **2016 non-hybrid Fusion (2.5L "S", in scope)** retains MS-CAN on
the DLC — the HS2-CAN-replaces-MS-CAN change hit the *hybrid* Fusion/C-Max first, not the gasoline
car. **Nuances flagged by verifiers:** "access all buses simultaneously" is vendor marketing — the
switch electronically *selects* one bus under rapid software control (single CAN transceiver), not
literal concurrent reads; and **J1850 is a distinct pre-CAN protocol, NOT a CAN bus.**
Sources: obdlink.com/products/obdlink-ex, vgatemall vLinker FS, forum.forscan.org t=4, t=970.

### V2 — No native macOS support anywhere in this stack  · HIGH
Neither FORScan nor the USB Ford adapters offer **native macOS** support. OBDLink EX lists
"Android, Windows Vista or newer"; vLinker FS lists "Windows 2000/Vista/7/8/8.1/10". The real
blocker is that **FORScan itself is Windows-only** — every documented Mac path is a Windows-on-Mac
workaround (Boot Camp, Parallels/VMware/VirtualBox, or CrossOver/Wine). "Not listed" ≠ "cannot
function via virtualization." **This directly validates FordScope's reason to exist**: a native-
macOS diagnostics path that talks to the vLinker FS over the ELM327 backend, avoiding the Windows VM.
Sources: obdlink.com/products/obdlink-ex, vgatemall vLinker FS, OBDLink support KB 43000754740.

### V3 — OBDLink EX is the FORScan-endorsed reference; vLinker FS is not (and was pulled Feb 2025)  · HIGH
OBDLink EX is USB-only (no BT/WiFi) and is **the adapter FORScan's own site lists as the
"recommended USB adapter for Windows version of FORScan."** The **Vgate vLinker FS is NOT on
FORScan's official recommended list** (surfaces only in forum threads), and FORScan admins
**temporarily removed vLinker USB adapters from recommended status in Feb 2025 over a confirmed
compatibility issue.** Practical read for the owner: the vLinker FS *works* for Ford MS-CAN, but the
EX is the safer reference; watch for vLinker firmware/compat caveats.
Sources: forscan.org/home.html, obdlink.com/products/obdlink-ex, scantool.net.

### V4 — FORScan can aggregate PIDs across modules ("All" virtual module)  · HIGH
FORScan (v2.3.8+, Mar 2017) reads PIDs from multiple modules at once via a synthetic **"All"
virtual module** that aggregates parameters across PCM/ABS/BCM/FIP/ICU, each prefixed with its
owning module's abbreviation (type the abbreviation to filter). Directly relevant to a multi-module
live-data view. Source: forum.forscan.org t=3334 (tool developer's own announcement).

*(7 claims survived total; the 3 not detailed here reinforce the same adapter/host conclusions —
full run output in the workflow task record.)*

## Implications for FordScope
- **Reinforces the whole project** (V2): FORScan is Windows-only; a native-macOS diagnostic path is
  a real gap FordScope fills. Keep the ELM327/vLinker-FS backend as the on-car path (R8).
- **Adapter guidance** (V1/V3): the vLinker FS reaches Ford MS-CAN modules, but the OBDLink EX is the
  FORScan-endorsed reference; note the Feb-2025 vLinker compatibility caveat honestly to the owner.
- **R3 & R5 stay BLOCKED** — the drive-cycle and Mode 06 facts did NOT verify (rate-limit). Re-run
  those angles alone before building either. No unverified drive-cycle/Mode-06 claims enter the tool.
