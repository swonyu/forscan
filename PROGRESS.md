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
- [x] 1.4 PID decode table: 16 common PIDs (RPM/coolant/MAF/MAP/fuel-trims/speed/throttle/…) with units
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
- [ ] 5.1 Flashing state machine (0x27/0x34/0x36/0x37), stubbed — needs FDRS keys/calibrations

## Tooling
- [x] `fordscope-build` skill (`.claude/skills/`) + project `CLAUDE.md`
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
