# FordScope Roadmap — honest, prioritized feature backlog

> This is the brainstorming/design output for the autonomous build loop. The owner
> delegated approval ("do what you think is best") while away, so this doc stands in
> for the per-feature approval gate: nothing gets built that isn't specced here first,
> and every item states **what is testable now** vs **what is `NEEDS ON-CAR CHECK`**.
>
> Guardrails still bind (see `CLAUDE.md`): simulator-first, test-first, spec-derived
> fixtures, and the hard "never build" list. **Padding is the enemy now** — when this
> backlog is exhausted, the honest move is to stop adding features, deepen review/docs,
> and surface the owner-blocked leaps. Do not manufacture iterations.

Legend — **Build-now** = fully specifiable + testable against the simulator today ·
**Risk** = design risk, not effort · every real-car *read/write* is `NEEDS ON-CAR CHECK`
regardless of tier (the decode is what we verify against the spec).

---

## Tier 1 — build-now, high value, low risk

### R1. Mode 09 CALID + CVN readout  ✅ shipped-candidate first
- **What:** SAE J1979 Mode 09 InfoType 0x04 (Calibration ID, ASCII), 0x06 (Calibration
  Verification Number, 4-byte hex per CALID), 0x0A (ECU name). Decode + surface in CLI,
  web report, and health report.
- **Why it matters:** this is exactly what FORScan/dealers read to confirm a module's
  *software level* — the single most-requested "which calibration am I on?" datapoint.
  Directly complements the existing VIN (0x02) read.
- **Build-now:** yes. Extend `SimulatedObdEcu` to answer 0x04/0x06/0x0A (multi-message,
  NODI count), decode ASCII/hex, test against a hand-derived J1979 fixture. Risk: low.
- **Honesty:** the *decode* is spec-verifiable; the real read is `NEEDS ON-CAR CHECK`.

### R2. Session min / max / average per live PID
- **What:** while `live()` streams, track running min/max/mean per PID; expose in the
  web UI and the downloadable report ("Engine RPM: 780–4200, avg 1450 over 62 samples").
- **Why:** catches intermittent/transient faults a single snapshot misses; near-free.
- **Build-now:** yes — pure controller logic over the existing sample stream. Risk: low.

### R3. Readiness / drive-cycle coach
- **What:** turn the existing monitor-status readout into *actionable* guidance — for each
  NOT-READY monitor, the generic OBD drive-cycle conditions that complete it (cold start
  threshold, steady cruise, decel fuel-cut, etc.), plus a plain "you likely need N more
  drive cycles."
- **Why:** the owner explicitly cares about **inspection readiness**. This is the highest
  real-world-utility item in the backlog.
- **Build-now:** yes — a monitor→guidance map + logic over readiness data. Risk: low.
- **Honesty:** label as **generic OBD-II drive-cycle guidance, not a Ford-specific
  procedure or a pass guarantee**. Don't assert Fusion-specific cycle timings we can't verify.

---

## Tier 2 — build-now, medium value or medium risk

### R4. Live PID graphing (inline SVG sparklines) in the web UI
- **What:** render a rolling line chart per selected PID from the `/api/live` poll.
- **Why:** makes it feel like a real scan tool; trends beat single numbers for diagnosis.
- **Build-now:** data path yes (controller feed is unit-tested); SVG render is browser-side
  (assert structure/series, not pixels). Risk: low-medium (keep JS minimal, no deps).

### R5. Mode 06 — on-board monitoring test results
- **What:** generic decode of Mode 06 TID/MID results with min/max limits + pass/fail.
- **Why:** early warning (catalyst/O2/EVAP) *before* a monitor fails to a DTC.
- **Build-now:** yes for the generic decode. Risk: **medium** — TID/MID *meanings* are
  largely OEM-specific. Ship generic structure + value/limit math; label component IDs
  **manufacturer-specific, meaning not asserted** (same honesty pattern as the DTC
  fallback). Do not invent Ford TID names.

### R6. DTC state separation surfacing (confirmed / pending / permanent)
- **What:** clearly split Mode 03 (stored/confirmed) vs 07 (pending) vs 0A (permanent) in
  the UI + report, with a one-line "what this state means."
- **Why:** pending-vs-permanent is the difference between "watch it" and "won't clear until
  the fault is actually fixed" — high diagnostic signal, low effort.
- **Build-now:** yes; the modes exist, this is surfacing + guidance. Risk: low.

---

## Tier 3 — real-world leaps, owner-blocked (prepare, don't fake)

### R7. `.app` packaging (py2app / PyInstaller)
- **Status:** can author the build spec + a one-command script now, but **cannot verify**
  without `pip install pyinstaller` on the owner's Mac. Prepare + document; mark UNVERIFIED;
  do not claim it produces a working `.app`.

### R8. First on-car validation with the Vgate vLinker FS
- **Status:** the eventual point of the whole tool. **Blocked on owner + adapter + car.**
  Until then everything hardware-touching stays `NEEDS ON-CAR CHECK`. This is not padding
  runway — it's the graduation event.

---

## Never build (standing — from CLAUDE.md, restated so the loop can't drift)
- Emissions-defeat / rolling-coal / readiness-spoofing coding (illegal defeat device).
- Anti-theft / immobilizer / PATS bypass.
- Reflashing that cracks SecurityAccess or ships OEM calibration binaries.
- Fabricated As-Built feature maps presented as real for a specific car — the As-Built
  layer stays a *framework*; real maps come from FORScan/the owner, labeled UNVERIFIED.

---

## Build order (as of 2026-07-04, updated)
**Done:** R1 (iters 49–50), R2 (iter 51), R6 (iter 52).
**Blocked on verified research:** R3 (drive-cycle coach) and R5 (Mode 06) — the 2026-07-04
deep-research run did NOT return verified drive-cycle/TID facts (verifiers rate-limited, not
refuted; see `docs/RESEARCH_2026-07-04_ford_diagnostics.md`). **Do not build R3/R5 until those
angles are re-run and verified** — no unverified drive-cycle/Mode-06 claims enter the tool.
**Next buildable:** R4 (live PID graphing) — research-independent; verify by launching the app
(preview tools), since the SVG render is browser-side.
R7 authored-but-UNVERIFIED whenever convenient; R8 waits on the owner.
When R1–R6 are done: **stop feature-manufacturing**, shift to hardening/docs/review, say so in `PROGRESS.md`.

## Research + audit status (2026-07-04)
- **Deep-research (adapter/host layer): DONE + indexed** → `docs/RESEARCH_2026-07-04_ford_diagnostics.md`
  (7 verified claims: MS-CAN switching, no-native-macOS, OBDLink-EX-is-the-FORScan-reference, FORScan
  "All" module). Reinforces the project; adapter guidance for R8.
- **Deep-research (4 diagnostic angles): FAILED to verify (rate-limit) — RE-RUN needed** for R3/R5.
- **Safety/security/honesty/robustness audit: FAILED (all 6 auditors rate-limited) — RE-RUN needed.**
  The workflow script was fixed so a rate-limited run now reports INCOMPLETE, never false-clean.
- **Re-run discipline:** serialize big fan-out workflows — do NOT overlap them (overlap is what
  tripped the shared rate-limit on 2026-07-04).
