---
name: fordscope-build
description: Use when working on the FordScope project (the Python Ford OBD-II diagnostic + As-Built coding tool in this repo) — resuming or continuing the build, running or verifying its test suite, onboarding to it cold, or deciding whether a feature is in-bounds to build. Not for the Salehman/StockSage markets app.
---

# FordScope Build

## Overview
FordScope is a hardware-abstracted Ford OBD-II diagnostic + As-Built coding tool.
Core principle: **simulator-first, test-driven, resumable** — every layer is built and
proven against an in-memory CAN simulator, so there is no car in the loop and nothing is
claimed to work on a vehicle until it has been checked on one.

**REQUIRED BACKGROUND:** superpowers:test-driven-development and
superpowers:verification-before-completion.

## When to use
- Continuing/resuming the build (including each autonomous loop iteration or after a context reset).
- Verifying the suite is green.
- Judging whether a proposed feature is legal/safe to build (see boundaries).
- Onboarding to the repo cold — start here, then read `PROGRESS.md`.

## The iteration loop (in order)
1. Read `PROGRESS.md` — the resumable state. `git log --oneline` is the source of truth for what actually landed.
2. Pick the first unchecked box in the phased plan.
3. **Test first** — write/extend a test that fails, then implement the minimum to pass.
4. **Verify by running:** `./run_tests.sh` → must print `Ran N tests … OK`. This is the ONLY green check.
5. Update `PROGRESS.md` (tick the box, append a one-line iteration log with the measured test count).
6. Commit. One green suite + one commit per iteration, so a session death loses at most one step.

## Verify — the only green check
```bash
./run_tests.sh          # stdlib unittest, no pip deps; exit 0 == green
```
Never tick a box, write an iteration log, or report progress without a passing run. Paste the
verdict line, don't claim it.

## Where things live (layered; each testable in isolation)
`transport/` (CanFrame + Transport ABC + SimulatorTransport) → `isotp/` (ISO 15765-2 codec +
socket + simulated ECU) → `uds/`, `obd/` → services (whole-car scan, DTC, As-Built) → app/CLI.
Nothing above `transport` knows which backend is attached; the simulator is a first-class
backend, not a test mock.

## Honesty boundaries (non-negotiable)
- **No live-vehicle validation exists in the build environment.** Simulation passing ≠ works on a car.
- Label any behavior that can only be confirmed on hardware **`NEEDS ON-CAR CHECK`**; never call it "working."
- Fixtures are hand-derived from the SAE/ISO byte formats, never from the code under test. A failing
  contract test is fixed in the code or the fixture — never by weakening the assertion.

## Hard legal/safety lines — never build these
| Forbidden | Why |
|-----------|-----|
| Emissions-defeat coding (readiness spoof, EGR/DPF delete) | Illegal defeat device (US Clean Air Act), even on an owned car |
| Anti-theft / immobilizer (PATS) bypass | Theft-enabling |
| Reflashing that cracks SecurityAccess or ships OEM calibrations | Ford IP; legit path is an FDRS subscription — build the state machine, not the key-crack |

As-Built (Tier 4) config writes are allowed **only** with backup-before-write + read-back verify.

## Common mistakes
- Building a hardware backend and calling it done — device I/O is `NEEDS ON-CAR CHECK`; only its codec is unit-testable.
- Writes before reads — implement/verify read paths before any config write.
- Skipping `PROGRESS.md` update — the next iteration (or a resuming session) then can't find the edge of the work.
