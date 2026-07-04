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
- [~] 0.2 Real backends behind the same ABC — TWO built, codecs fully tested over injected ports;
      live serial [NEEDS ON-CAR CHECK]: `SlcanTransport` (CANable-class raw CAN) + `Elm327Transport`
      (OBDLink EX / ELM327 AT-command). Openport (J2534-on-Mac) backend still TODO.
- [x] 1.1a ISO-TP frame codec: SF/FF/CF/FC encode + parse (pure, hand-derived fixtures)
- [x] 1.1b ISO-TP transport layer: `IsoTpSocket` send/recv + flow control; `SimulatedIsoTpEcu`
      (reusable simulated endpoint). BS=0 both ways; client send honours ECU block-size>0.
      Follow-up: ECU-side receive block-size>0 + real STmin timing are [NEEDS ON-CAR CHECK].
- [x] 1.2 UDS client (ISO 14229): request/response, NRC handling, responsePending (0x78) loop,
      session control, ECU reset, tester-present, Read/WriteDataByIdentifier + `SimulatedUdsEcu`
- [x] 1.3 OBD-II (SAE J1979): `ObdClient` — Mode 01 current data, 03/07/0A DTC reads, 04 clear,
      09 VIN; positive/negative handling; `SimulatedObdEcu`
- [x] 1.4 PID decode table: 35 common Mode 01 PIDs with units (RPM/coolant/MAF/MAP/fuel-trims/speed/
      throttle/EGR/catalyst-temp/lambda/oil-temp/run-time/fuel-rate/…), formulas hand-verified vs J1979
- [x] 1.5 DTC read/clear (in 1.3) + DTC-definition database: curated generic table + structural
      fallback that flags uncurated/manufacturer codes instead of inventing a meaning
- [x] 2.1 Ford enhanced addressing: 11-bit (legislated + Ford +8) and 29-bit normal-fixed
      (0x18DA{TA}{SA}/0x18DAF1{TA}, 0x18DB33F1). Math authoritative; module address map caveated.
- [x] 2.2 ReadDataByIdentifier across modules — whole-car walk (`services/module_scan.py`):
      connect per module, read identification DIDs, present/absent detection, text report
- [x] 3.1 Bidirectional: IOControl (0x2F) + RoutineControl (0x31) — start/stop/results, sequence
      checking. SAFETY: actuates real hardware; simulator-tested only, on-car use is NEEDS ON-CAR CHECK
- [x] 3.2 Whole-car DTC report (`services/dtc_scan.py`): UDS ReadDTCInformation (0x19) per module,
      aggregated + described (via DTC DB) + present/absent; `format_dtc_report`, `total_dtc_count`
- [x] 3.3 CLI (`fordscope/cli.py`, `python -m fordscope`): scan / dtc / read <pid> / vin / clear-dtc.
      `--backend simulator|slcan|elm327` + `--port`; live backends construct a real transport
      (LIVE UNVALIDATED banner) via pyserial or an injectable port_factory. (dashboard + logging
      deferred as optional follow-up)

## Phase 2 — As-Built coding (Tier 4)
- [x] 4.1 Backup-before-write engine (`ford/asbuilt.py`): `AsBuiltCoder` refuses writes without a
      captured backup; `InMemoryBackupStore` + durable `FileBackupStore`; one-click `restore_block`
- [x] 4.2 As-Built read + decode (`ford/asbuilt_format.py`): `AsBuiltBlock` (label/data/checksum),
      parse, sum-to-zero checksum compute+validate, byte/nibble edit w/ re-checksum; coder bridge
      (`read_as_built`/`code_as_built`). Checksum convention documented + confirm-on-vehicle.
- [x] 4.3 Guarded write with read-back verify + rollback (in 4.1: `write_block` verifies,
      `restore_block` rolls back; `VerificationError` on mismatch)
- [x] 4.4 Named feature definitions (`ford/features.py`): `FeatureDefinition` (block+byte+nibble+
      options), `FeatureCoder` read/set by name via the safe path. Mechanism authoritative;
      `EXAMPLE_FEATURES` shipped UNVERIFIED (honesty test enforces the flag).

## Phase 3 — Reflashing (Tier 5, gated)
- [x] 5.0 SecurityAccess (0x27) seed/key handshake — `UdsClient.request_seed`/`send_key`/`unlock`
      (key_fn user-supplied; NO real Ford algorithm shipped/cracked) + `SimulatedUdsEcu` security
      (levels, invalid-key/exceed-attempts/sequence-error). Gates As-Built writes + reflashing on-car.
- [x] 5.1 Flashing transfer state machine (0x34/0x36/0x37): `UdsClient.request_download`/
      `transfer_data`/`request_transfer_exit`/`download` (chunks to ECU max-block, block-seq wrap)
      + `SimulatedUdsEcu` transfer (reassembly, wrongBlockSequenceCounter, sequence errors).
      PROTOCOL ONLY — no calibration files, no CLI exposure; real reflash needs FDRS keys/data.

## Phase 4 — Native macOS app (no Windows VM) — owner request
- [x] 4.G Local web app (`fordscope/webapp/`): stdlib `http.server` JSON API + one embedded page,
      `python -m fordscope.webapp`. Testable `FordScopeController` (list ports, connect via
      `open_backend`, scan/dtc/read/vin) + thin server. Connects to a real USB adapter (Vgate
      vLinker FS via the elm327 backend) so diagnostics run native on macOS — no FORScan/Windows VM.
      Demo (simulator) path fully functional + tested; real serial is NEEDS ON-CAR CHECK. Scope: it's
      a native DIAGNOSTICS app, not a full FORScan As-Built replacement (maps unverified).
- [x] 4.1 Live-data dashboard in the web app: `controller.live(pids)` + `GET /api/live?pids=…`
      + a browser view that polls every 1s into a table (Start/Stop). Unsupported PIDs blank, not fail.
- [ ] 4.2 (later) package as a double-clickable .app (py2app/pyinstaller) — deferred: needs
      uninstallable tooling + can't be verified here, so not built blind.

## Phase 5 — Roadmap features (honest backlog → `docs/ROADMAP.md`)
Each is buildable + simulator-testable now; every real-car read stays [NEEDS ON-CAR CHECK].
Build order R1→R2→R3→R6→R4→R5, a review pass interleaved. **When these are done, STOP
feature-manufacturing** (per ROADMAP.md) — shift to hardening/docs/review and say so plainly.
- [x] R1 Mode 09 CALID + CVN (+ ECU name) readout — the "which calibration am I on?" datapoint.
      Engine (iter 49): `ObdClient.read_calibration_ids`/`read_cvns`/`read_ecu_names`
      (InfoType 0x04/0x06/0x0A). Surfaced (iter 50): `controller.calibration()`, a Calibration
      line in the health report, `GET /api/calibration`, demo-seeded. Real read [NEEDS ON-CAR CHECK].
- [x] R2 Session min/max/avg per live PID (iter 51): controller accumulates per-PID running
      min/max/sum/count on each `live()` poll (numeric only), reset on (re)connect;
      `live_stats()` + `GET /api/live-stats` + a "Live session" block in the health report.
- [ ] R3 Readiness / drive-cycle coach — generic OBD conditions to complete each not-ready monitor
- [x] R6 DTC state separation (iter 52): `controller.dtc_states()` reads Mode 03/07/0A and
      returns confirmed/pending/permanent groups, each with a plain-language meaning + described
      codes; `GET /api/dtc-states`. The emissions/inspection view (distinct from the UDS per-module
      `dtc()` scan) — surfaces the pending-vs-permanent distinction that explains "why codes come back."
- [ ] R4 Live PID graphing (inline SVG sparklines) in the web UI
- [ ] R5 Mode 06 on-board monitoring test results (generic decode; TID meanings OEM — not invented)

## Tooling
- [x] `fordscope-build` skill (`.claude/skills/`) + project `CLAUDE.md`
- [x] `fordscope-code-review` skill — codifies the adversarial review technique (the bug-class
      checklist that has caught every real bug here: parser bound-checks, exception hierarchy,
      HTTP status ordering, resource leaks, spec-math constants; reproduce-RED-before-fix)
- [x] `ford/fusion_2016.py` — 2016 Fusion S profile from a 7-agent adversarially-verified research
      run: CONFIRMED module addresses (PCM 7E0/ABS 760/RCM 737/APIM 7D0/IPC 720/BCM 726) +
      confirm-on-vehicle/plausible tiers; As-Built pointers COMMUNITY-SOURCED (block-level only,
      no fabricated byte maps), with the verification's attribution corrections. Honesty tests. — the build protocol,
      verify command, layering, and hard legal/safety boundaries. Authored RED→GREEN via the
      writing-skills discipline: RED baselines showed the *honesty* discipline is already
      ambient (so no discipline skill written — it would be redundant); the real gap was the
      repo-specific protocol + automotive boundaries, so it ships as a reference skill,
      GREEN-verified (a skill-equipped agent correctly refused an emissions-defeat feature and
      an untested-hardware "it works" claim).

## Iteration log
- **Iter 1** — Scaffolded repo, spec (`docs/DESIGN.md`), this log. Built Tier 0: `CanFrame`
  (validated, frozen, 11/29-bit) + `Transport` ABC (context-manager) + `SimulatorTransport`
  with swappable responders (`null`/`echo`/`canned_obd`). 19 unit tests, all passing on the
  simulator (`./run_tests.sh` → `Ran 19 tests … OK`). No hardware touched.
- **Iter 2** — ISO-TP frame codec (`isotp/frames.py`): the four PCI types (SF/FF/CF/FC)
  encode + `parse_isotp`/`pci_type`, classic-CAN 8-byte "normal" addressing, 12-bit FF
  length, CAN-FD/32-bit escapes explicitly rejected. +21 tests (40 total,
  `Ran 40 tests … OK`). Reordered plan: real hardware backends (0.2) deferred as
  on-car-only; building the fully-simulatable protocol stack (ISO-TP → UDS → OBD-II) first.
- **Iter 3** — ISO-TP transport layer. `IsoTpSocket` (`isotp/socket.py`): SF + multi-frame
  send with FF→FC→CF streaming honouring block-size/STmin; recv with FC(CTS) + in-sequence
  reassembly; `stmin_to_seconds`; typed errors (Timeout/Overflow/Sequence).
  `SimulatedIsoTpEcu` (`isotp/simulated_ecu.py`): reusable stateful endpoint for UDS/OBD
  tests later. +13 tests incl. 4 client↔ECU round-trips (short/long × req/resp), a
  block-size-2 send, and an out-of-sequence rejection (53 total, `Ran 53 tests … OK`).
  One test-fixture bug self-caught: an 8-byte CF (impossible on classic CAN) — the codec's
  validation rejected it; fixed the fixture, not the assertion.
- **Tooling** — `fordscope-build` reference skill + project `CLAUDE.md` (authored RED→GREEN via
  writing-skills; honesty discipline found already-ambient so not re-encoded; protocol +
  automotive boundaries shipped as reference; GREEN-verified). Docs only; suite unchanged.
- **Iter 4** — UDS client (`uds/`). `services.py`: SIDs + NRC table + `nrc_name`. `client.py`:
  `UdsClient.request` (positive / negative→`NegativeResponseError` / 0x78 responsePending loop
  with bound) + wrappers (read/write DID, session control, ECU reset, tester-present w/ suppress).
  `simulated_ecu.py`: `SimulatedUdsEcu` (DID store, sessions) as a `SimulatedIsoTpEcu` handler.
  +17 tests incl. multi-frame VIN read, multi-frame write round-trip, NRC paths, and both
  responsePending outcomes (70 total, `Ran 70 tests … OK`).
- **Iter 5** — OBD-II (SAE J1979) layer (`obd/`). `pids.py`: 16-PID decode table with units +
  `decode_dtc`/`encode_dtc`/`decode_dtcs` (2-byte ↔ "P0143"), all pure/hand-derived. `client.py`:
  `ObdClient` — Mode 01 current data (decoded), 03/07/0A DTC reads, 04 clear, 09 multi-frame VIN,
  positive/negative handling. `simulated_ecu.py`: `SimulatedObdEcu`. +24 tests incl. PID scaling,
  DTC round-trips, clear, multi-frame VIN (94 total, `Ran 94 tests … OK`). Next: DTC-definition DB.
- **Iter 6** — DTC-definition database (`obd/dtc_database.py`): 35-code curated generic (SAE J2012)
  table + `describe_dtc` structural fallback (system/subsystem/manufacturer-specific) that returns
  "no specific definition on file" for uncurated codes instead of fabricating one. `ObdClient
  .read_dtcs_described`. +8 tests incl. the honesty case (uncurated P0199/manufacturer P1234 get
  no invented meaning) (102 total, `Ran 102 tests … OK`). Phase 1 generic surface complete; next:
  Ford enhanced module addressing (Phase 1 §2.1).
- **Iter 7** — Ford enhanced addressing (`ford/addressing.py`): 11-bit (`legislated_obd_pair`,
  `eleven_bit_module` +8, `ford_module`) and 29-bit normal-fixed (`extended_module`
  0x18DA{TA}{SA}/0x18DAF1{TA}, `extended_functional_request_id` 0x18DB33F1). `TYPICAL_FORD_MODULES`
  map is explicitly non-authoritative (confirm on-vehicle). +12 tests incl. a 29-bit UDS
  end-to-end (transport→ISO-TP→UDS on 0x18DA72F1). Two fixture bugs self-caught: passed the
  11-bit id 0x720 where a 29-bit target *byte* was required — the byte-range validation rejected
  it; fixed the fixtures, not the assertions (114 total, `Ran 114 tests … OK`).
- **Iter 8** — Whole-car module scan (`services/module_scan.py`, first `services/` layer).
  `scan_vehicle` connects a `UdsClient` per module, reads the 6 standard identification DIDs,
  and classifies present (answered positive OR negative) vs absent (silence); `format_scan_report`
  renders it. Added reusable `isotp.multiplex` to host many ECUs on one simulated bus. +4 tests:
  present w/ identifiers, absent detection, present-but-no-DIDs, report format (118 total,
  `Ran 118 tests … OK`). Next: bidirectional actuator tests (3.1).
- **Iter 9** — Bidirectional controls on `UdsClient` + `SimulatedUdsEcu`: `io_control` (0x2F,
  return-control / short-term-adjustment) and `routine_control`/`start`/`stop`/`request_results`
  (0x31, with requestSequenceError when results requested before start). SAFETY caveat in
  docstrings — these actuate hardware; simulator-tested only, on-car use is NEEDS ON-CAR CHECK.
  +7 tests (125 total, `Ran 125 tests … OK`). Next: whole-car DTC report (3.2), then CLI (3.3).
- **Iter 10** — Whole-car DTC report. UDS ReadDTCInformation 0x19/reportDTCByStatusMask on
  `UdsClient` + `SimulatedUdsEcu` with the 3-byte-DTC+status format (`uds/dtc.py`: `UdsDtc`,
  `decode_dtc_records`, status bits, mask filtering). `services/dtc_scan.py`: `scan_vehicle_dtcs`
  aggregates across modules, pairs codes with DTC-DB descriptions, flags confirmed/pending,
  present/absent. +7 tests (132 total, `Ran 132 tests … OK`). One self-caught test bug: imported
  `IsoTpSocket` from the wrong module; removed it. Next: CLI (3.3).
- **Iter 11** — CLI (`cli.py` + `__main__.py`): `python -m fordscope {scan,dtc,read,vin,clear-dtc}`
  against a simulated demo Ford (PCM+BCM+ABS present, APIM absent); every command prints a
  SIMULATED banner; `--backend slcan/openport` refuses honestly (exit 2) instead of faking a
  connection. +9 tests AND a live run (scan/dtc/read/vin/backend-guard all verified by execution).
  **Phase 1 (Tiers 0–3) core complete.** 141 total, `Ran 141 tests … OK`. Next: **Phase 2 —
  As-Built coding** (4.1 backup-before-write engine).
- **Iter 12** — Phase 2 As-Built coding engine (`ford/asbuilt.py`). `AsBuiltCoder` enforces the
  safety invariant: `write_block` raises `BackupRequiredError` (and makes NO change) unless a
  backup exists; `code_block` = backup→write→read-back-verify; `restore_block` rolls back;
  `VerificationError` on read-back mismatch. `InMemoryBackupStore` + durable `FileBackupStore`
  (survives sessions). Enters extended session before writes; SecurityAccess still NEEDS ON-CAR
  CHECK. +10 tests incl. adversarial: refusal-makes-no-change + a CorruptingUdsEcu proving
  read-back verify fires (151 total, `Ran 151 tests … OK`). Next: 4.2 As-Built block decode.
- **Iter 13** — As-Built block format (`ford/asbuilt_format.py`): `AsBuiltBlock`
  (label/data/checksum), `parse_block`, `compute_checksum` (sum-to-zero mod 256, documented +
  confirm-on-vehicle), safe `set_byte`/`set_nibble`/`with_data` that re-checksum, `to_bytes`,
  `format`. Coder bridge `read_as_built`/`code_as_built` (parse → edit → safe write → restore).
  +14 tests incl. checksum validity, nibble edits, round-trip, and a full read→edit→code→restore
  through the coder (165 total, `Ran 165 tests … OK`). Next: 4.4 named feature definitions.
- **Iter 14** — Named As-Built features (`ford/features.py`). `FeatureDefinition` (key/name/module/
  did/label/byte/nibble/options) with `current_option` + `apply`; `FeatureCoder.read_feature`/
  `set_feature` (read→apply→safe backup/write/verify→restorable). Mechanism authoritative;
  `EXAMPLE_FEATURES` (fog-DRL / gauge-sweep / double-honk) shipped explicitly UNVERIFIED. +8 tests
  incl. a full set→verify→restore and an honesty test that FAILS if any example lacks the
  UNVERIFIED flag (173 total, `Ran 173 tests … OK`). **Phase 2 As-Built core complete.**
- **Iter 15** — slcan hardware backend (`transport/slcan.py`, deferred 0.2). Pure wire codec:
  `encode_frame`/`parse_frame` (standard `t...` + extended `T...` lines), `bitrate_command`
  (Ford HS-CAN 500k=S6 / MS-CAN 125k=S4). `SlcanTransport` over a duck-typed serial port —
  open sends `S6\rO\r`, send/recv encode/parse, skips status/ack lines. +17 tests over a
  FakeSerial (codec round-trip, command sequencing, status-line skipping). Real serial timing
  still NEEDS ON-CAR CHECK. This is the bridge to a real ~$30 CANable adapter. (190 total,
  `Ran 190 tests … OK`). Next: wire `--backend slcan` in the CLI (still refusing until on-car).
- **Iter 16** — ELM327/STN backend (`transport/elm327.py`) so the OBDLink EX (the recommended
  adapter) works with FordScope, not just FORScan. Pure: `parse_response_line` (headers-on
  11-bit/29-bit lines, status/prompt filtering), `header_command`/`payload_line`/`protocol_command`.
  `Elm327Transport` over a duck-typed port: ATZ/ATE0/ATH1/ATCAF0/ATSP init, ATSH-on-header-change,
  read-until-`>` recv. +14 tests over a FakeSerial. Live device timing / 29-bit / multi-frame FC
  in raw mode = NEEDS ON-CAR CHECK. One fixture bug self-caught: a 7-byte "8-byte" frame line —
  fixed the fixture, not the assertion (204 total, `Ran 204 tests … OK`).
- **Iter 17** — Wired backends into the CLI. `--backend simulator|slcan|elm327` + `--port`;
  `open_backend` factory builds the demo (SIMULATED banner) or a live `SlcanTransport`/
  `Elm327Transport` (LIVE UNVALIDATED / NEEDS ON-CAR CHECK banner) via pyserial or an injectable
  `port_factory`. Live modules = `TYPICAL_FORD_MODULES` (non-authoritative). +5 net tests (injected
  fake-port live run, factory construction, missing-port + missing-pyserial error paths). Verified
  by running: simulator works, both live error paths clean (209 total, `Ran 209 tests … OK`).
  Software is now plug-in-ready; the only gap to a real truck is validating the serial path on-car.
- **Iter 18** — Wired the 2016 Fusion profile into the CLI. `--profile generic|fusion2016`;
  `modules_for_profile` + `open_backend(profile=...)` swap the scan/dtc module list to the verified
  `fusion_2016.confirmed_modules()` (PCM/ABS/RCM/APIM/IPC/BCM). +4 tests; verified by running
  (`--profile fusion2016 scan` walks the real Fusion addresses). So on your car:
  `python -m fordscope --backend elm327 --port … --profile fusion2016 scan` (223 total,
  `Ran 223 tests … OK`).
- **Iter 19** — As-Built CLI (read side). `features` lists the EXAMPLE features (loudly labeled
  UNVERIFIED/demo); `read-feature <key>` reads a feature's current setting via a `FeatureCoder`
  bound to the module, with an UNVERIFIED warning line. Demo BCM/IPC seeded with the example
  As-Built blocks (+ an IPC module) so it runs end-to-end. +4 tests; verified by running.
  Next (iter 20): `set-feature` with backup-file + `--confirm` + simulator-only guard (won't
  write unverified maps to a live car). 227 total, `Ran 227 tests … OK`.
- **Iter 20** — `set-feature <key> <option>` — the As-Built write side, three safety gates:
  (1) dry-run by default (shows `current -> option`), (2) `--confirm` required to write, (3)
  refuses on a live backend (won't write EXAMPLE/UNVERIFIED maps to a real car). On the simulator
  the `--confirm` path runs the full `FeatureCoder.set_feature` (backup → write → read-back verify)
  and reports `off -> on (written, read-back verified) · Original block backed up`. +5 tests
  (dry-run, confirm-write, live-refusal, unknown feature/option); verified by running.
  **Phase 2 As-Built is now drivable end-to-end from the CLI.** 232 total, `Ran 232 tests … OK`.
- **Iter 21** — `restore-feature <key>` (one-click undo) + `--backup-file` for durable backups.
  `FeatureCoder.restore_feature`; CLI `_store_for` (FileBackupStore when `--backup-file` given, else
  in-session). `set-feature --backup-file X` persists the original block; `restore-feature
  --backup-file X` writes it back + verifies (simulator-only, like set). `FileBackupStore._flush`
  now creates parent dirs. +3 tests incl. a full durable set→restore across two invocations;
  verified by running. **As-Built safety loop (backup→write→verify→restore) complete in the CLI.**
  235 total, `Ran 235 tests … OK`.
- **Iter 22** — Live-data logging (`services/datalog.py`, optional-tier). `DataLogger` polls Mode 01
  PIDs with an INJECTABLE clock/sleep (deterministic tests, no real waiting); unsupported/undecodable
  PIDs log as blank cells, not aborts. `rows_to_csv`/`write_csv_file` with named+unit column headers.
  CLI `log --pids 0C,05,0D --samples N --interval S [--out file.csv]`. +11 tests; verified by running
  (CSV with `Engine RPM (rpm)`,`…coolant…(degC)` columns). 246 total, `Ran 246 tests … OK`.
- **Iter 23** — UDS SecurityAccess (0x27), Phase 3 groundwork. `UdsClient.request_seed`/`send_key`/
  `unlock(key_fn, level)` — seed→key handshake; all-zero seed = already-unlocked. HONESTY: `key_fn`
  is user-supplied (FDRS/own analysis); FordScope ships NO real Ford key algorithm and cracks none.
  `SimulatedUdsEcu` security (configurable key/seed/levels/attempts) with invalidKey (0x35),
  exceedAttempts (0x36), requestSequenceError (0x24), subFunctionNotSupported (unconfigured/level).
  +8 tests (demo XOR-0x5A key). This is what gates real As-Built writes + reflashing on-car.
  254 total, `Ran 254 tests … OK`.
- **Iter 24** — Reflash transfer state machine (0x34/0x36/0x37), Phase 3 §5.1 — the LAST planned
  item. `UdsClient.request_download` (returns ECU max block) / `transfer_data` (per-block seq) /
  `request_transfer_exit` / `download` (chunks data, block-seq wrap). `SimulatedUdsEcu` reassembles
  the transfer and enforces wrongBlockSequenceCounter (0x73) + sequence errors. PROTOCOL ONLY —
  no calibration data, deliberately NOT wired to the CLI (bricking risk); real reflash needs a
  programming session + security unlock + genuine FDRS calibration. +6 tests. 260 total,
  `Ran 260 tests … OK`. **The entire phased plan (Phases 1–3 + tooling) is now complete.**

## Post-plan polish
- **Iter 28** — Phase 4: native macOS web app (`fordscope/webapp/`) so the owner drives the
  Vgate vLinker FS directly, no Windows VM. `FordScopeController` (reuses `open_backend`) +
  stdlib `http.server` JSON API + embedded page; `python -m fordscope.webapp`. +8 tests
  (controller + HTTP-over-real-sockets: connect→scan→read→vin, 409-before-connect). **Gotcha
  found & fixed:** `import webbrowser` at module top hung ~35s/test under the `-m unittest` runner
  on macOS — made it lazy (only in `run()`); suite back to 2.0s. Tkinter unavailable here, so a
  browser UI was the right, portable, testable choice. 276 total, `Ran 276 tests … OK`.
- **Iter 29** — Phase 4.1: live-data dashboard in the Mac app. `controller.live(pids)` (blank for
  unsupported PIDs, never fails the sample) + `GET /api/live?pids=…` + a browser view that polls
  every 1s into a table (Start/Stop). +3 tests; verified by running end-to-end over HTTP (RPM 1000
  / coolant 50 / speed 64 streaming). Deliberately did NOT attempt `.app` packaging (untestable
  here, and the owner asked me not to make mistakes). 279 total, `Ran 279 tests … OK` (2.5s).
- **Iter 30** — Phase 4: Clear-codes button in the Mac app. `controller.clear_dtcs` (Mode 04) +
  `POST /api/clear-dtc` (mutating → POST, `NotConnectedError`→409) + a UI button gated behind a
  browser confirm ("also resets emissions readiness"). +4 tests. Also sped the server tests:
  `serve_forever(poll_interval=0.02)` so shutdown returns fast — suite 3.5s → **0.195s**. 283 green.
- **Iter 31** — Supported-PIDs engine (Mode 01 PID 0x00). `decode_supported_pids(base, mask)` (pure,
  32-bit mask → PID list) + `SimulatedObdEcu` auto-computes the 0x00/0x20/… masks from its PID set
  (incl. the continuation bit) + `ObdClient.supported_pids()` follows PID 0x00→0x20→… while the
  continuation bit is set. +5 tests incl. the range-follow (a 0x2F PID pulls in range 0x20). Engine
  layer only; wires into the Mac app next. 288 total, `Ran 288 tests … OK` (0.19s).
- **Iter 32** — Wired supported-PIDs into the Mac app. `controller.supported_pids()` (named via
  PID_TABLE, `decodable` flag, meta range-marker PIDs filtered) + `GET /api/supported` + a
  "Supported PIDs" button that lists them as clickable chips; a click adds the PID to the live
  dashboard input (point-and-click, no hex typing). +3 tests; verified by running (endpoint returns
  05/0C/0D named). 291 total, `Ran 291 tests … OK`.
- **Iter 33** — CSV export from the Mac app. `controller.log_csv(pids, samples)` (reuses the
  `DataLogger` engine) + `GET /api/log?pids=…&samples=N` serving `text/csv` with a download
  disposition (samples capped at 1000) + a "Download log (CSV)" button (`window.location` →
  browser download). +3 tests; verified by running (200, `text/csv`, attachment, real rows).
  294 total, `Ran 294 tests … OK`.
- **Iter 34** — Widened PID coverage 16 → **35** Mode 01 decoders (fuel-trim bank 2, run time,
  distance-with-MIL, commanded/error EGR, evap purge, warm-ups, catalyst temp, absolute load,
  equivalence ratio/lambda, throttle variants, MIL time, oil temp, fuel rate, …). Every formula
  hand-verified vs SAE J1979; +10 tests with hand-derived values (the scaling is exactly where a
  wrong reading would hide). 304 total, `Ran 304 tests … OK`. The Mac app's "Supported PIDs" now
  names far more of what a car reports.
- **Iter 35** — Freeze-frame (Mode 02) engine. `ObdClient.freeze_frame(pid, frame)` (frozen PID
  value via the same decoders) + `freeze_frame_dtc()` (the DTC that triggered it, or None);
  `SimulatedObdEcu` freeze_frame/freeze_dtc seed + `_mode02` ([0x02,pid,frame]→[0x42,pid,frame,data]).
  +4 tests. Engine layer; wires into the Mac app next. 308 total, `Ran 308 tests … OK`.
- **Iter 36** — Freeze-frame in the Mac app. `controller.freeze_frame()` (triggering DTC + frozen
  PID rows, unsupported PIDs omitted) + `GET /api/freeze` + a "Freeze frame" button showing the
  DTC and the frozen snapshot. Demo PCM seeded with a P0143 freeze frame (idling/warm/stopped).
  +3 tests; verified by running (dtc P0143, coolant 45 / RPM 1000 / speed 0). 311 total,
  `Ran 311 tests … OK`.
- **Iter 37** — I/M readiness / monitor status (Mode 01 PID 0x01). `decode_monitor_status` →
  `MonitorStatus` (mil_on, dtc_count, compression_ignition, per-monitor supported/complete, plus
  `.ready`/`.not_ready`); spark vs compression monitor name sets; complete == supported and not
  the *incomplete* bit (the inversion, tested). `ObdClient.monitor_status()`. +5 tests hand-derived.
  Engine layer; wires into the Mac app next ("will it pass inspection?"). 316 total, `Ran 316 … OK`.
- **Iter 38** — Readiness in the Mac app. `controller.readiness()` + `GET /api/readiness` + a
  "Readiness" button with a plain PASS / NOT-READY verdict (ready AND MIL-off), MIL, DTC count,
  and which monitors aren't complete. Demo PCM seeded with a coherent status (MIL on, 1 DTC,
  O2-sensor monitor incomplete → NOT READY). Filtered status PIDs (0x01/0x02) out of the live-
  dashboard picker (not gauges). +3 tests; verified by running. 319 total, `Ran 319 tests … OK`.
- **Iter 39** — Combined Health Report in the Mac app. `controller.health_report()` composes VIN +
  inspection-readiness verdict + whole-car DTCs (with descriptions) + freeze frame into one
  shareable text snapshot; each section independently tolerant (a failing section is noted, not
  fatal). `GET /api/report` + a "Health report" button. +3 tests; verified by running (full report
  renders). One self-caught test bug: referenced `DEMO_VIN` without importing it — fixed the import,
  not the assertion. 322 total, `Ran 322 tests … OK`.
- **Iter 40** — Adversarial review of the web layer (grown ~12 iters unreviewed) → **2 real bugs
  found & fixed test-first** (324 green): (1) bad hex query params (`/api/read?pid=zz`, live, log)
  returned 500 instead of 400 — added a `ValueError→400` clause in `do_GET`. (2) `open_backend`
  leaked the serial fd when the transport handshake failed after the port opened (each failed retry
  → another leaked handle → "device busy") — wrapped construction+open in try/except that closes
  the port before re-raising. Reviewer verified the rest sound: no handler-hang paths, 409 mapping
  correct, all responses JSON-safe. Running tally: **6 real bugs found+fixed across 3 review rounds.**
- **Iter 41** — First-run support. `fordscope ports` command + `list_serial_ports()` (globs
  /dev/cu.* minus noise) so the owner can discover the vLinker FS device; webapp `list_ports`
  DRY'd to reuse it. `FIRST_RUN.md`: accurate on-car first-connection guide (find port → elm327
  scan/vin → the Mac app), commands verified vs `--help`, with the LIVE-UNVALIDATED framing and
  troubleshooting. +2 tests. 326 total, `Ran 326 tests … OK`.
- **Iter 42** — Downloadable health report. Generalized the CSV helper into `_download(text,
  filename, content_type)`; `GET /api/report.txt` serves the health report as a `text/plain`
  attachment + a "Download report" button — save a dated diagnostic record / send to a mechanic.
  +2 tests; verified by running (200, text/plain, attachment filename). 328 total, `Ran 328 … OK`.
- **Iter 43** — Vehicle-profile selection in the Mac app. Added a Vehicle dropdown (Auto / 2016
  Ford Fusion / Generic) whose value flows through `connect` → `open_backend(profile=…)`, so a live
  scan walks the VERIFIED Fusion module map instead of the generic guess. Backend already supported
  it; this exposes it in the UI. +2 tests (controller + endpoint: fusion profile → scan shows the
  Fusion-specific RCM module). 330 total, `Ran 330 tests … OK`.
- **Iter 44** — Adversarial review of the post-first-review engine additions (the 19 newer Mode 01
  PID scaling formulas, `decode_supported_pids`/`_supported_mask`, the supported-PIDs follow loop,
  the `decode_monitor_status` supported-vs-incomplete inversion + spark/compression monitor tables,
  Mode 02 freeze-frame framing). **NO bugs found** — every formula verified vs SAE J1979, the
  monitor bit-tables cross-checked against primary sources by the reviewer. Clean; no code change.
  Reviews now cover the whole codebase across 4 rounds (6 real bugs total, all in earlier code).
- **Iter 45** — Widened the DTC-definition database 36 → **90** well-established SAE J2012 generic
  codes (MAP/IAT/ECT/TPS circuits, O2 sensors bank1/2, injectors, misfire 5/6, cam/crank timing,
  ignition coils, EGR/secondary-air/EVAP leaks, catalyst, idle/voltage/module, transmission
  range/speed/TCC/shift solenoids, U-network TCM/BCM/IPC). Only confident code→meaning mappings
  added; +2 tests (sample lookups + coverage). More of a real car's codes come back named instead
  of the structural fallback. 332 total, `Ran 332 tests … OK`.
- **Iter 27** — Completed adversarial review coverage (CLI + scan services, the last un-reviewed
  logic). **1 more real bug found & fixed test-first** (268 total green): `scan_module` /
  `scan_module_dtcs` only caught `UdsError`, but `IsoTpSocket` raises a separate `IsoTpError`
  hierarchy — so a module that answered then dropped a frame mid-multi-frame (real bus noise on a
  VIN read) aborted the WHOLE scan (exit 3) instead of being marked present-and-continuing. Fixed:
  catch `IsoTpError` in both walkers. Reviewer verified the As-Built safety gates are sound (live
  write can't escape to a real car; dry-run never writes; backup-before-write holds; exit codes
  correct). **Entire codebase now adversarially reviewed; 4 real bugs found+fixed across 2 rounds.**
- **Iter 26** — Adversarial code review (2 independent reviewers over the logic-heavy files) →
  **3 real correctness bugs found & fixed test-first** (each: failing test reproduced the crash,
  then fixed, 266 total green):
  1. `slcan.parse_frame` raised an uncaught `ValueError` on a DLC>8 line (docstring promises
     `None`) → crashed the recv loop on one corrupt serial line. Fixed: bound-check DLC.
  2. `elm327.parse_response_line` — identical crash on >8 data bytes. Fixed: bound-check length.
  3. `parse_isotp` accepted a malformed First Frame with total 1-7 (must be a Single Frame per
     ISO 15765-2); silently returned bogus data AND emitted a spurious Flow Control. Fixed: reject
     `total < SF_MAX_DATA+1` in the parser (mirrors the encoder). Reviewers verified the
     safety-critical paths (backup-before-write invariant, checksum, addressing, DTC/PID math,
     flow-control state machine, sequence wrap) are all correct.
- **Iter 25** — README rewrite. Replaced the stale iteration-1 README ("early… transport layer")
  with an accurate one: real command list (verified against `--help`), quick-start, the two
  live backends (marked UNVALIDATED), and a prominent honesty-boundaries section (no on-car
  validation, no emissions/immobilizer, SecurityAccess key not shipped, reflash protocol-only /
  not CLI-exposed, As-Built examples UNVERIFIED). Docs only; suite unchanged at 260 green.
- **Iter 46** — Adversarial review pass (4 auditors, one per subsystem) → **1 real bug family
  found & fixed test-first** (336 total green). The `slcan` and `elm327` ASCII parsers
  range-checked DLC but **not the arbitration ID**, so a lexically-valid-but-out-of-range ID
  (11-bit >0x7FF, 29-bit >0x1FFFFFFF) made the frozen `CanFrame` raise `ValueError` that
  escaped `recv()` and killed the receive loop — violating the parsers' documented
  skip-not-crash contract (same bug *class* as the iter-26 DLC crashes, a different unchecked
  field). Fixed: explicit ID-range guard mirroring the DLC guard in both parsers; +4 tests
  (11-/29-bit, both parsers), each reproduced RED first. The other two auditor-clean subsystems
  (UDS/OBD clients; PID/DTC/checksum/addressing math) verified by independent spec
  re-derivation — no bugs. Also: authored `docs/ROADMAP.md` (honest feature backlog) and the
  `fordscope-code-review` skill (codifies this review technique). Web-layer findings (read-PID
  500, connect empty-body message, log negative-samples, live-poll transport concurrency)
  queued for iter 47.
- **Iter 47** — Web-layer robustness (3 auditor findings fixed test-first; 342 green).
  (B) `read_pid` now catches `ObdError`/`KeyError`/`ValueError` and returns a blank result
  (`value=None`, `supported=False`, note) exactly like `live()`/`log()` — a valid-hex but
  unsupported PID used to surface as an HTTP **500**; now a clean 200 blank. (D) `connect("")`
  raises a clear `ValueError("select a port first")` instead of falling into the live-serial
  branch and leaking a pyserial-dependency message (POST /api/connect with no body → clean 400).
  (E) `log_csv` clamps `samples` to ≥1, so a negative count yields one row, not a silent
  header-only file. +6 tests (controller + HTTP for each), all RED-first. Concurrency finding
  (shared transport across `ThreadingHTTPServer` threads) still queued for iter 48.
- **Iter 48** — Concurrency fix (the last iter-46 auditor finding; 343 green). One
  `FordScopeController` (one shared transport) serves every `ThreadingHTTPServer` worker,
  and the dashboard polls `/api/live` every second while the user can click scan/read — so
  two threads interleaved `send`/`recv` on the one serial line (frame cross-talk / corrupt
  reads on real hardware; masked on the in-process simulator). Fix: every public controller
  method serialized on a single **reentrant** `RLock` via a `_synchronized` decorator
  (reentrant is required — `health_report` calls `vin`/`dtc`/`freeze_frame`, `connect` calls
  `disconnect`). Test-first with a deterministic (non-flaky, verified 5×) gated-controller
  probe that parks one thread mid-critical-section and proves a second can't enter
  (`max_active == 1`). **All four iter-46 auditor findings now closed.** [The corruption
  itself is NEEDS ON-CAR CHECK — only real hardware exhibits it; the lock is the correct
  guard and is proven to serialize.]
- **Iter 49** — R1 engine: Mode 09 calibration readout. `ObdClient.read_calibration_ids`
  (InfoType 0x04, 16-byte ASCII items), `read_cvns` (0x06, 4-byte → hex), `read_ecu_names`
  (0x0A, 20-byte ASCII) — the "which calibration/firmware am I on?" datapoint FORScan/dealers
  use to confirm module software level. Fixed-width item decode (split on null padding, drop
  empties); `SimulatedObdEcu` seeded via `calibration_ids`/`cvns`/`ecu_names` + a `_info_items`
  helper. +5 tests (single + multi CALID, CVN-as-hex, ECU name, unsupported→raises), RED-first.
  348 green. Decode is spec-verified; the real read is [NEEDS ON-CAR CHECK]. Surfacing = R1b.
- **Iter 50** — R1b: surfaced the calibration readout. `FordScopeController.calibration()`
  (returns `{calids, cvns}`, empty-not-raising when an ECU doesn't report Mode 09 — safe under
  the RLock), a "Calibration: … (CVN …)" line in the shareable health report, and
  `GET /api/calibration`. Demo PCM seeded with an obviously-fake `DEMO-PCM-CAL-01` / CVN
  1A2B3C4D so it's demonstrable end-to-end. +4 tests (controller, health-report, endpoint,
  before-connect 409), RED-first. 352 green. **R1 complete** (engine + all surfaces).
- **Iter 51** — R2: session min/max/avg per live PID. The controller folds each `live()` poll
  into a per-PID running {min,max,sum,count} (numeric values only — bool excluded despite being
  an int subclass), reset on (re)connect so each session is clean. `live_stats()` returns
  min/max/avg/count; `GET /api/live-stats`; the health report gains a "Live session (min/max/avg)"
  block when a session has been polled. Catches intermittent faults a single snapshot misses.
  +6 tests (aggregation math over a varying sequence, live-updates-count, reset-on-reconnect,
  report block, endpoint, before-connect 409), RED-first. 358 green.
- **Iter 52** — R6: DTC state separation. `controller.dtc_states()` reads generic OBD Mode 03
  (confirmed), 07 (pending), 0A (permanent) and returns three groups, each with a plain-language
  meaning + described codes (via the DTC DB); `GET /api/dtc-states`. This is the emissions/
  inspection lens — distinct from the UDS per-module `dtc()` scan — and surfaces the
  pending-vs-permanent distinction (why a permanent code won't clear on a scan-tool wipe). Demo
  PCM seeded with pending P0113 + permanent P0420 for end-to-end demonstration. +4 tests
  (split-by-state + meaning, before-connect raise, endpoint, 409), RED-first. 362 green.
- **Iter 53** — Sim fixed-width consistency (from an adversarial audit of the iter 49–52 code,
  which was otherwise clean): `_info_items` truncated CVN but not CALID/ECU-name, so an over-long
  fixture would emit >16/>20 bytes and mis-split on decode. All three item types now truncate to
  wire width. +1 test. 363 green.
- **Iter 54** (docs/research) — Indexed the 2026-07-04 deep-research →
  `docs/RESEARCH_2026-07-04_ford_diagnostics.md`. **Honest split:** 7 claims verified, all
  adapter/host-layer (MS-CAN switching for Ford comfort modules; FORScan/adapters have NO native
  macOS → FordScope's raison d'être; OBDLink EX is the FORScan-endorsed reference, vLinker FS pulled
  Feb-2025 over a compat issue; FORScan "All" virtual module). The **four core diagnostic angles
  (enhanced PIDs, As-Built format, drive-cycle conditions, Mode 06) returned ZERO verified claims —
  verifiers rate-limited, not refuted → R3/R5 STAY BLOCKED.** Also: the safety/honesty/robustness
  audit workflow FAILED (all 6 auditors rate-limited) and its script had a **false-clean bug**
  (null auditor → "no findings"); fixed to report INCOMPLETE. Both failed workflows need
  **serialized** re-runs (overlap tripped the shared rate-limit). No code/behavior change.
- **Iter 55** — Safety-audit re-run **completed clean** (all 6 dimensions ran; the fixed script
  confirms it's genuine, not a rate-limited false-clean) and found **real 2/3-verified bugs**.
  Fixed the two HONESTY findings (365 green): (#1, HIGH) `_text_items` decoded a truncated
  trailing chunk into a fabricated extra CALID/ECU-name item presented as a real firmware level —
  now modulo-guarded to whole items only (consistent with `read_cvns`); (#4, MED) `read_vin`
  returned a short/truncated VIN as if complete — now null-stripped and validated to exactly 17
  chars, raising `ObdError` otherwise. +2 tests (truncated-CALID-tail, 9-char VIN), RED-first.
  Remaining audit findings queued: #2 UDS P2* timeout, #3 serial-fd leak, #5 As-Built bounds.
- **Iter 56** — Audit finding #2 (HIGH, spec): `UdsClient.request` reused the short P2 timeout
  after responsePending (0x78), aborting legit long ops. Added `p2_star_timeout` (default 5.0s,
  ISO 14229 P2*server_max) and switch to it after the first 0x78. +1 test (recording socket
  asserts recv timeouts [1.0, 5.0]). 366 green.
- **Iter 57** — Audit finding #3 (HIGH, resource): `Elm327Transport.close()`/`SlcanTransport.close()`
  never closed the underlying serial fd (leaked one per connect/disconnect on the success path).
  Added `base.close_port()` (guarded, error-swallowing) called from both. +2 tests. 368 green.
- **Iter 58** — Audit finding #5 (MED, verified before acting): `_read_value` with a negative
  `byte_index` silently returned the WRONG byte as the feature value — now bounds-guarded (raises).
  The finding's `set_nibble` "silent corruption" claim did NOT reproduce (it already raised
  IndexError); added a validate-before-read guard for write-path defense-in-depth + clearer message,
  honestly logged as hardening not a corruption fix. +2 tests. 370 green. **All 5 seen findings
  closed; re-running the audit to confirm + catch anything past the truncated #5.**
- **Iter 59** — Audit re-run **completed clean** (all 6 dims ran; my 5 fixes held) and found
  **4 NEW** findings. Fixed the HIGH safety one: `backup_block` unconditionally overwrote the
  stored backup, and `code_block` calls it every write — so coding a SHARED block a second time
  (normal Ford case: many feature-nibbles per block) re-read the already-modified value and
  clobbered the factory-original; `restore` then returned a MODIFIED state, not factory, with the
  recovery data destroyed. Now the first-captured backup is IMMUTABLE (returns existing; opt-in
  `force=True`). +1 test. 371 green.
- **Iter 60** — Audit finding (honesty): `describe_dtc` asserted the SAE P0-family third-digit
  subsystem for ALL P-codes, fabricating a category for manufacturer (P1/P3) and P2 codes
  (P1250 → "injector circuit", but it's a pressure-regulator solenoid). Now set only for P0xxx.
  +1 test. 372 green.
- **Iter 61** — Audit finding (resource, gap in iter 57): `slcan.close()` wrote CLOSE_COMMAND
  before `close_port` with no guard → a write failure (adapter yanked) skipped the fd release and
  left `is_open` True. Wrapped the write in try/except. +1 test. 373 green.
- **Iter 62** — Audit finding (spec, LOW): ISO-TP `_await_cts` treated a reserved FC FlowStatus
  (0x3-0xF) as WAIT and looped to a misleading timeout; ISO 15765-2 requires N_INVALID_FS abort.
  Now only WAIT (0x1) loops; reserved raises `IsoTpError`. +1 test. 374 green. **All 4 second-audit
  findings closed (9 real bugs total across 2 audits); re-running a third time to converge.**
