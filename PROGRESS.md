# FordScope — Build Progress (resumable)

**If a session died and you're resuming:** read `docs/DESIGN.md`, run `./run_tests.sh`
(must be green), then pick up the first unchecked box below. Every iteration ends with a
green suite and a commit, so `git log` is the source of truth for what actually landed.

## How I work each iteration
TDD: write/extend a test → implement → `./run_tests.sh` green → commit → tick a box here.
Never mark a box or claim behavior without a passing test. Hardware-only behavior is
labelled **[NEEDS ON-CAR CHECK]** and never counted as "working."

## Phase 1 — Diagnostics foundation (Tiers 0–3)
- [x] 0.1 Transport abstraction: `CanFrame` + `Transport` ABC + `SimulatorTransport`
- [ ] 0.2 Real backends behind the same ABC: slcan/CANable, then Openport [NEEDS ON-CAR CHECK]
- [ ] 1.1 ISO-TP (ISO 15765-2): single-frame + multi-frame segmentation/reassembly
- [ ] 1.2 UDS client (ISO 14229): request/response, negative-response codes, session control
- [ ] 1.3 OBD-II (SAE J1979) modes 01–0A on top of ISO-TP
- [ ] 1.4 PID decode table (RPM, coolant, MAF, MAP, fuel trims, speed, …) with units
- [ ] 1.5 DTC read/clear + DTC-definition database (generic + Ford)
- [ ] 2.1 Ford enhanced module map + 29-bit addressing (PCM/TCM/ABS/BCM/IPC/APIM/RCM…)
- [ ] 2.2 ReadDataByIdentifier (0x22) across modules
- [ ] 3.1 Bidirectional: IOControl (0x2F) + RoutineControl (0x31) scaffolding
- [ ] 3.2 Whole-car scan → health report
- [ ] 3.3 CLI + live dashboard + CSV/SQLite logging

## Phase 2 — As-Built coding (Tier 4)
- [ ] 4.1 Backup-before-write engine (persist original block, one-click restore)
- [ ] 4.2 As-Built read + decode
- [ ] 4.3 Guarded write with read-back verify + rollback

## Phase 3 — Reflashing (Tier 5, gated)
- [ ] 5.1 Flashing state machine (0x27/0x34/0x36/0x37), stubbed — needs FDRS keys/calibrations

## Iteration log
- **Iter 1** — Scaffolded repo, spec (`docs/DESIGN.md`), this log. Built Tier 0: `CanFrame`
  (validated, frozen, 11/29-bit) + `Transport` ABC (context-manager) + `SimulatorTransport`
  with swappable responders (`null`/`echo`/`canned_obd`). 19 unit tests, all passing on the
  simulator (`./run_tests.sh` → `Ran 19 tests … OK`). No hardware touched.
