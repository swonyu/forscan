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
- [~] 0.2 Real backends behind the same ABC — TWO full transports built, codecs fully tested over
      injected ports; live serial [NEEDS ON-CAR CHECK]: `SlcanTransport` (CANable-class raw CAN) +
      `Elm327Transport` (OBDLink EX / ELM327 AT-command). Openport (J2534-on-Mac): raw-CAN WIRE CODEC
      landed (iter 131, `transport/j2534.py`: `encode_can_message`/`parse_can_message`/`can_baudrate`
      + `PROTOCOL_CAN`/`CAN_29BIT_ID`) — 4-byte big-endian ID + payload and the CAN_29BIT_ID flag,
      hand-derived from SAE J2534-1, tested over fixtures. `J2534Transport` class over an INJECTED
      PassThru library landed (iter 140, `transport/j2534.py`): open→connect(raw CAN)→pass-all filter,
      send/recv marshalling CanFrame<->PASSTHRU_MSG, transmit-loopback (TX_MSG_TYPE) + malformed-record
      skip, disconnect-then-close with fd-release-on-error; proven full-stack (J2534→ISO-TP→OBD: SF RPM
      + multiframe VIN) over a scripted fake, exactly as slcan/elm327. The C ABI struct landed too
      (iter 141, `transport/j2534.py`): `CPassThruMsg` (`ctypes.Structure`, 6×`c_uint32` + `Data[4128]`,
      spec `sizeof`=4152) + `pack_msg`/`unpack_msg` marshalling to the dataclass — layout hand-derived
      from SAE J2534-1 (offsets 0/4/8/12/16/20, Data@24), the size test straddles the `c_ulong`=8-byte
      LP64 trap (4176). Still TODO: LOADING + CALLING the vendor `.dylib` over ctypes (`cdll`, the
      `PassThru*` function prototypes), which is [NEEDS ON-CAR CHECK].
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
- [~] 4.2 / R7 package as a double-clickable .app (pyinstaller) — SCAFFOLDED, UNVERIFIED (iter 87):
      `tools/fordscope_launcher.py` (entry: `run()`), `tools/build_macos_app.sh` (one-command
      pyinstaller build), `docs/PACKAGING.md` (approach + likely iterations + the works-today
      `python -m fordscope.webapp` fallback). Launcher entry validated (imports cleanly); the BUILD
      itself needs `pip install pyinstaller` on the owner's Mac — honestly marked UNVERIFIED, not
      claimed working.

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
- [x] R3 Readiness / drive-cycle coach (iter 86, research-partial): `obd/drive_cycle.py` maps each
      NOT-READY monitor to a tip — **EVAP carries the Ford-verified condition** (45–65 mph, 10 min,
      tank ½–¾), every other monitor carries clearly-labeled GENERIC guidance (the Ford-specific
      catalyst/HEGO cycles were REFUTED, so `ford_verified=False`). `controller.drive_cycle_coach`
      + `GET /api/drive-cycle`.
- [x] R6 DTC state separation (iter 52): `controller.dtc_states()` reads Mode 03/07/0A and
      returns confirmed/pending/permanent groups, each with a plain-language meaning + described
      codes; `GET /api/dtc-states`. The emissions/inspection view (distinct from the UDS per-module
      `dtc()` scan) — surfaces the pending-vs-permanent distinction that explains "why codes come back."
- [x] R4 Live PID graphing (iter 83): per-PID rolling history (last 40 samples) + an inline SVG
      polyline sparkline column in the live dashboard, reset on Start. Verified by RUNNING: the
      sparkline math in node (rising orients correctly, empty/single→no line, flat→div-0-safe,
      null→baseline), a live end-to-end smoke test (connect→poll→rows carry pid+value), and a
      structural test that the served page wires it. Visual pixels are well-formed SVG (node-
      confirmed); a literal browser eyeball is the one un-automated sliver [owner/preview].
- [x] R5 Mode 06 on-board monitoring test results (iters 84–85, research-unblocked): `obd/mode06.py`
      standardized MID→category table + `MonitorTest` (value/limits + pass/fail from the ECU's own
      limits; TID raw/OEM-specific, not invented); `ObdClient.monitor_tests` + `controller.monitor_tests`
      + `GET /api/monitor-tests`; demo seeds catalyst/O2 pass + EGR fail.

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
- **Iter 63** (docs) — Applied the owner's cross-project standing directives to FordScope's
  `CLAUDE.md` (distilled from the Salehman `opus-operating` skill + `owner-decision-style` /
  `fordscope-work-expectations` / `workflow-model-config` memories). New "Standing owner directives"
  section: **no `AskUserQuestion` tool** (pick the best option + proceed; one-line prose if a steer
  is truly needed); conservative/reversible defaults, BLOCK only for irreversible/safety-critical;
  proof discipline (done = pasted output + positive path fired; the diff is the fact; spec/standalone
  hand-derived fixtures that genuinely straddle; logs describe the final tree; nil = unknown never
  fabricated); ultracode bar (exhaustive + adversarial + verify-by-measurement; Workflows with Opus
  orchestrator + Sonnet-max subagents, serialized; token discipline; research-memory). Also wrote
  two durable memory files (fordscope-project-map, workspace-and-skills-map) + workflow-model-config.
  Docs only; no code change; 374 green.
- **Iter 64** — 3rd audit (first on the Sonnet-5/max subagent config) **completed clean**; iters
  59–62 held; **4 NEW findings**. Fixed the HIGH: both UDS and OBD clients checked the echoed SID on
  the POSITIVE path but not the NEGATIVE path, so a crossed-wire `[0x7F, 0x27, 0x31]` (SecurityAccess
  error) to a `0x22` (RDBI) request was misattributed to the caller's own request. Both now validate
  the echoed SID/mode (ISO 14229 §7.5). +2 tests. 376 green.
- **Iter 65** — Audit finding (MED, safety): `io_control` (0x2F) checked the DID echo but not the
  control-option echo (`resp[3]`), unlike `routine_control`; a response confirming a DIFFERENT
  actuator mode was accepted. Now rejected. +1 test. 377 green.
- **Iter 66** — Audit finding (MED, concurrency): every read endpoint built `{data, banner}` from two
  separately-locked reads → under concurrent disconnect a **LIVE/UNVALIDATED banner could silently
  vanish** (live data shown without the red warning). Added `controller.snapshot(read)` capturing
  `(result, banner)` under the one reentrant lock; all banner-paired endpoints use it. +1 deterministic
  (non-flaky) concurrency test. 378 green.
- **Iter 67** — Audit finding (LOW): `describe_dtc` malformed-guard didn't validate digit-2 (0-3) or
  that digits 3-5 are hex, so `P4143`/`P0G43` masqueraded as well-formed. Now validated. +2 cases. 378
  green. **13 real bugs fixed across 3 audit runs; severity trending down (HIGH→MED→LOW); 4th run to
  check the fixpoint.**
- **Iter 68** — 4th audit (Sonnet-max) found **4 more** (iters 59-67 held). Fixed the HIGH, a gap in
  my own iter-55 VIN fix: `read_vin` decoded `errors="replace"`, so a same-length VIN with one corrupt
  non-ASCII byte became 17 chars with a `�` silently substituted and passed the length guard; `_text_items`
  (CALID/ECU) had the same gap. Both now decode STRICT — VIN raises + requires 17 alphanumerics; corrupt
  CALID items are dropped, not fabricated. +2 tests. 380 green.
- **Iter 69** — Audit (2 LOW): `freeze_frame` now checks the frame-number echo (resp[2]), not just the
  PID; CLI help + README relabel the fusion2016 profile "confirmed-tier" (was flatly "verified" though
  the data is 3-tier graded and the profile uses only the confirmed tier). +1 test. 380 green.
- **Iter 70** — Audit (MED): suppressed `tester_present` set `expect_response=False` and never recv'd,
  so a conformant ECU's NEGATIVE response (suppress bit suppresses only the POSITIVE) was invisible — a
  rejected session keep-alive looked alive. Now briefly probes for an NRC (50ms default, documented
  residual). +1 test. 382 green.
- **Audit-script hardening** (the tool, not the app): the 4th run exposed a SECOND false-completeness
  bug — a dying *verifier* (StructuredOutput cap) dropped its whole dimension while `complete` stayed
  true (the first bug was auditor-nulls, fixed earlier). Script now catches verifier deaths as null
  votes (dimension survives), buckets under-quorum findings as `unverified`, and reports INCOMPLETE on
  any errored/dropped dimension or unverified finding. **17 real app bugs fixed across 4 runs; 5th run
  (honest script) to catch the 2 dims whose verifiers failed + check the fixpoint.**
- **Iters 71–74** — 5th audit (Sonnet-max) **correctly reported `complete:false`** (honesty dim dropped
  — the hardened script working) and found **4 more real bugs**, TWO of them gaps in my OWN recent
  fixes: (71, HIGH) the iter-70 tester-present probe raised on `0x78` responsePending (busy≠rejected) →
  would tear down a healthy session; now `0x78`→alive. (72, HIGH) `FileBackupStore._flush` truncated
  then wrote (no atomic replace) → an interrupted write destroyed EVERY backup + corrupted the file
  unreadable; now temp-file + `os.replace` atomic. (73, HIGH) backup key was scope+DID only and the CLI
  hardcoded `scope="cli"` → two features on different modules sharing a DID collided → restore wrote the
  WRONG module's bytes; now scoped `cli:<module>`. (74, MED) `request_download` returned a truncated
  value when the ECU declared more length bytes than it sent; now validated. +4 tests, RED-first. 386
  green. **21 real app bugs across 5 runs; 2 were gaps in my own fixes (the audit earns its keep); 6th
  run to re-audit the dropped honesty dimension + check convergence.**
- **Iters 75–77** — 6th audit was **genuinely COMPLETE** (all 6 dims, 0 dropped — the honest script
  verified) and still found **2 HIGH + 1 MED**: (75, HIGH) `FileBackupStore.save` mutated in-memory
  BEFORE persisting, so a failed flush left `has_backup()==True` for a backup never written → write
  wrongly permitted; now persists-before-commits. (76, HIGH) SecurityAccess treated an EMPTY seed
  (`any(b'')==False`) as already-unlocked, skipping the key exchange; now an empty seed is rejected.
  (77, MED) `dtc_states` collapsed a comms failure into an affirmative empty "all-clear"; now each
  bucket carries `available` (negative response = real empty; comms failure = unavailable). +3 tests.
  389 green. **24 real app bugs across 6 runs. STOPPING RULE: run 7 is the last general sweep — if it's
  complete and returns only LOW/none, the safety cycle is converged; if it still throws HIGHs, STOP
  general simulator-audits (diminishing returns; the HIGHs cluster in backup/SecurityAccess, some are
  gaps in my own fixes) and pivot — the real remaining risk-reduction is the on-car run (R8), not round 8.**
- **Iters 78–80** — 7th audit was **COMPLETE** and — importantly — the **safety-critical dims came
  back CLEAN** (safety-gates: "backup-before-write enforced, no bypass, 74/74 pass"; never-build:
  "SecurityAccess caller-supplied, reflash unreachable, no readiness-mask"). My iters 59/72/73/75/76
  closed those. The 3 findings were now OUTSIDE the core: (78, HIGH) `ObdClient._request` never handled
  NRC 0x78 responsePending — a busy ECU (Mode 09 VIN/CALID) got its read aborted; ported the UDS 0x78
  loop. (79, MED) webapp `run()` leaked the listening socket on Ctrl-C (`shutdown` without
  `server_close`); fixed + testable via a mocked server. (80, LOW) `parse_isotp` FF path lacked SF's
  truncation guard; added. +5 tests. 393 green. **CONVERGENCE CALL: safety-critical subsystems are
  verified clean; the tail is now spec/robustness edges. Running ONE confirmation audit (the OBD
  `_request` change is high-blast-radius) then STOPPING general audits regardless of any LOW tail —
  the owed work is the R3/R5 research re-run (blocked features) and R4, which the audit rabbit-hole has
  crowded out since iter 52. 26 real bugs fixed across 7 runs.**
- **Iters 81–82** — 8th (final) audit: honest script reported `complete:false` (2 dims dropped —
  honesty + resource-concurrency verifiers died; both were fully audited & fixed in runs 6/7 so not a
  real gap). never-build verified CLEAN again. **2 MED, no HIGH:** (81) removed `write_block`'s dead
  `require_backup=False` bypass — the backup gate is now structurally un-bypassable, not a scattered
  guard. (82) a malformed ISO-TP frame raised a bare `ValueError` the whole-car scan didn't catch → one
  garbage frame aborted the ENTIRE scan; the socket now wraps it as `IsoTpError` (the layer boundary),
  so the scan skips-and-continues per its own contract. +2 tests. 395 green.

## 🏁 SAFETY-AUDIT CYCLE CLOSED (2026-07-04, after 8 runs)
**28 real app bugs found & fixed test-first across 8 adversarial-audit runs** (Opus orchestrator +
Sonnet-max subagents), incl. ~9 HIGH (backup-clobber, backup-atomicity, backup-key-collision, SID
misattribution, VIN corruption, SecurityAccess empty-seed, OBD 0x78, vanishing LIVE banner). The
safety-critical subsystems (backup-before-write, never-build boundaries, SecurityAccess) are now
verified CLEAN by dedicated dimensions across the last 3 runs. The audit script itself was hardened
TWICE against false-completeness (auditor-null; verifier-drop). **STOPPING general audits** — a
Sonnet-max reviewer keeps finding real-but-edge issues indefinitely; severity has settled to MED/LOW
and the dangerous parts are clean. **The real remaining risk-reduction is the on-car run (R8), owner-
gated — not audit round 9.** Residual (honest): the 8th run's 2 dropped dims were audited clean/fixed
in runs 6/7; a future maintainer wanting a fully-complete final pass can re-run the saved workflow.
NEXT: the owed R3/R5 research re-run (blocked features) + R4 — feature work, neglected since iter 52.

## Back to features
- **Iter 83** — **R4 shipped** (first feature since iter 52): live PID graphing. Per-PID rolling
  history (40 samples) + an inline SVG sparkline column in the live dashboard, reset on Start;
  numeric values orient correctly (max→top), flat/empty/null handled. Verified by RUNNING (node
  logic across 5 cases + a live end-to-end smoke test + a structural page test), not by claim. +1
  test. 396 green. Meanwhile the R3/R5 diagnostic-research re-run (Sonnet-max, 4 angles) is in flight
  to unblock those features.
- **Research re-run SUCCEEDED** (Sonnet-max, 97 agents, 18 claims 3-vote-verified → 6 findings; no
  rate-limit this time). Indexed → `docs/RESEARCH_2026-07-04_ford_diagnostics.md`. R5 UNBLOCKED (MID
  standardized, TID/limits OEM); R3 PARTIAL (only EVAP drive cycle verified; Ford catalyst/HEGO
  claims REFUTED); As-Built checksum mechanism confirmed (maps stay UNVERIFIED — verify on-car).
- **Iters 84–85** — **R5 SHIPPED** (Mode 06). Engine (`obd/mode06.py`): standardized MID→category
  table, `MonitorTest` with pass/fail from the ECU's own returned min/max (raw units, no OEM scaling
  needed), TID kept raw/OEM-specific. Client `monitor_tests(mid)` + sim + `controller.monitor_tests`
  sweep + `GET /api/monitor-tests`, demo catalyst/O2 pass + EGR fail. Honesty line straight from the
  verified research: name the category, show value/limits/pass-fail, never fabricate a TID name or
  verdict. +10 tests. 406 green.
- **Iter 86** — **R3 SHIPPED** (drive-cycle coach). `obd/drive_cycle.py` maps each NOT-READY I/M
  monitor to a tip: EVAP = the Ford-verified condition (cited); all others = clearly-labeled generic
  OBD-II guidance with `ford_verified=False` (the Ford catalyst/HEGO cycles were REFUTED in
  verification — so they're honestly NOT claimed as Ford-specific). `controller.drive_cycle_coach` +
  `GET /api/drive-cycle`. +6 tests. 412 green. **The entire buildable roadmap R1–R6 is now DONE.**
  Remaining: R7 (.app packaging) + R8 (on-car) — owner-gated. Per the roadmap rule, feature-
  manufacturing STOPS here; further work is hardening/docs/the on-car graduation (R8).
- **Iter 87** — R7 .app packaging SCAFFOLDED, UNVERIFIED (launcher + build script + docs/PACKAGING.md).
- **Iter 88** (docs, maintenance — NOT a manufactured feature) — refreshed a materially stale README
  (last rewritten iter 25): it claimed "260 tests" (now **412**) and "16 PIDs" (now **35**), and never
  mentioned the **web app** (the whole Phase-4 native-macOS GUI) or the ~10 features shipped since
  (calibration, Mode 06, drive-cycle coach, live graphing, DTC states, readiness, health report,
  session stats). Now accurate + a Mac-app quick-start + the `ports` command + the packaging pointer.
  Every claim VERIFIED against the code (PID count, endpoints, subcommands, test count), not memory.
  412 green. **The tool is complete; the loop is now in maintenance mode — no features to manufacture.**
- **Iter 92** — Expose the newer features in the browser UI (Calibration / DTC states / Monitor
  tests / Drive cycle buttons + render fns) — AND caught a **latent COMPLETE dashboard-JS failure**
  while verifying the new JS with `node --check`: `INDEX_HTML` was a NON-raw Python string, so every
  JS `\n` became a REAL newline inside JS string literals → a hard SyntaxError that broke the ENTIRE
  dashboard in any browser. **All page-is-served tests passed for dozens of iterations because none
  execute the JS** — so the browser UI (connect/scan/live/sparkline/everything) never actually ran.
  Fixed by making `INDEX_HTML` raw; verified the served `<script>` now parses via `node --check`.
  **Honesty correction:** earlier "R4 graphing verified / UI shipped" claims were about the DATA/API
  layers (which were always tested-green) — the *integrated browser rendering* was broken until now.
  Lesson recorded: verify the integrated artifact (parse/launch the actual page), not just the pieces.
  +2 tests incl. a raw-string regression guard. 416 green.
- **Iter 93** — **Browser end-to-end verification** (the integrated-artifact check I owed after the
  iter-92 JS fix). Launched the real webapp via the Claude Preview tools (`.claude/launch.json`,
  headless) and drove the actual DOM: page renders with ALL buttons (incl. the iter-92 additions),
  **zero console errors** (the `<script>` now parses AND runs), Connect→**Monitor tests** ran the
  click handler and rendered the exact demo data (catalyst PASS, EGR FAIL), and **Start live →
  pollLive built history → the R4 sparklines rendered** (`<svg class="spark"><polyline …>`, 3 rows).
  So the browser dashboard — dead since it was written until iter 92 — is now VERIFIED working by
  running the actual page, not by claim. Added `.claude/launch.json` for repeatable preview runs.
  Lesson closed: the integrated artifact is verified only by launching it. No code change; 416 green.
- **Iter 94** — **Thorough** browser verification (iter 93 checked a sample; this checks the whole
  UI). Re-launched the real webapp via Preview and exercised EVERY render function in-browser
  (connect → scan/dtc/vin/calibration/dtc-states/drive-cycle/readiness/freeze/health-report), each
  rendering correct demo data with **zero console errors**. The 3 render functions I HAND-WROTE this
  session (`showCalibration`/`showDtcStates`/`showDriveCycle`) — previously only structural+endpoint
  tested — are now confirmed to actually render (e.g. "Calibration IDs: DEMO-PCM-CAL-01 / CVN
  1A2B3C4D"; "• Oxygen sensor (generic): …"; "CONFIRMED — …MIL is on"). The browser dashboard is now
  end-to-end verified in full, not by claim. No code change; 416 green.
- **Iter 95** — Wired a genuine LOOSE END: `read_ecu_names` (Mode 09 InfoType 0x0A, ECU name/acronym)
  was built + tested in iter 49 but never surfaced (grep confirmed zero callers in src/). Added it to
  `controller.calibration()` (now `{calids, cvns, ecu_names}`), the demo seed, and the UI
  `showCalibration()` render — completing the Mode-09 vehicle-info readout. Verified BY RUNNING: suite
  green + `node --check` (JS still parses) + browser render confirmed ("ECU names: DEMO-ECM-EngineCtl").
  +1 assertion. 416 green. (Completion of a built-but-unwired method, not a manufactured feature.)
- **Iter 96** — **CLI end-to-end verification by running** (the terminal analog of the iters 92–94
  browser verification — the one integrated artifact I'd tested via `main()` but never actually run
  this session). Ran the real `python -m fordscope` commands against the demo: `scan` (PCM/BCM with
  VIN + part numbers), `dtc` (P0143 [confirmed]), `vin`, `read 0C` (RPM 1000), `ports` (honest
  "no adapters found… Vgate vLinker FS"), `features` (loud EXAMPLE/UNVERIFIED label) — all correct,
  exit 0 on success, every honesty label present in the REAL output. No bugs. **Both integrated
  artifacts (browser UI + CLI) are now verified by running, not by claim.** No code change; 416 green.
- **Iter 97** — **Test-hygiene fix caught by actually reading the suite output** (not just the
  pass/fail line): `test_run_closes_socket_on_keyboard_interrupt` invoked the real `run()` (with
  `create_server` mocked, so no socket binds) but let `run()`'s user-facing `print()` banner leak
  into the suite's stdout — a stray "FordScope web app running at…" line that masks real warnings in
  CI. Fixed by capturing that stdout with `redirect_stdout` and asserting on it
  (`assertIn "http://127.0.0.1:8737/"`), which BOTH silences the leak AND strengthens the test: the
  entry point must now be proven to announce its listening URL/port. Verified by running — suite
  output ends cleanly at `OK`, no banner; +1 assertion. No production code change; 416 green.
  (Genuine hygiene/coverage fix, not a manufactured feature.)
- **Iter 98** (docs-accuracy sweep) — Killed the **phantom "Tactrix Openport" backend** still cited
  in the *canonical source* an external reader hits first — the same drift I fixed in `docs/DESIGN.md`
  at iter 89, still lurking in code docstrings. `transport/base.py` (module + `Transport` class
  docstrings) named a non-existent Openport and OMITTED the two real backends; fixed to the shipped
  reality (`SlcanTransport` CANable-class + `Elm327Transport` ELM327/OBDLink/Vgate vLinker FS), and
  dropped the stale "and later" (both ship now). `cli.py` module docstring referenced a `--backend
  openport` that argparse doesn't even accept (real choices: simulator/slcan/elm327) AND mis-described
  the live backends as "placeholders that refuse" when `open_backend()` actually builds real
  unit-tested transports flagged with the `NEEDS ON-CAR CHECK` banner — corrected to match verified
  source behavior. Repo-wide grep now CLEAN of Openport/Tactrix. No behavior change; 416 green.
- **Iter 99** (invariant guard — root cause of the iter-98 drift) — The `openport` doc drift had a
  real *root cause*: the CLI's argparse `--backend` **choices** and the set of backends
  `open_backend()` actually **handles** can silently diverge — add a choice without wiring the handler
  and a user picking a valid-per-argparse backend crashes on the "unknown backend" branch. Audited the
  two live parsers first (`elm327` two fires ago, `slcan` this fire — both genuinely robust: trailing
  slcan-timestamp bytes sliced via `rest[:2*dlc]`, truncated/BELL/out-of-range → `None`, no crash
  paths; no bug, did NOT manufacture one). Then added `test_every_backend_choice_is_handled`, which
  **introspects the real argparse choices** (a hardcoded list would drift identically) and asserts
  each is handled. Proved the guard's teeth first: `open_backend('openport', …)` raises `unknown
  backend 'openport'`, so an unhandled choice fails the test. +1 test → **417 green**.
- **Iter 100** (ISO-TP wraparound coverage — a real untested correctness property) — Audited the
  ISO-TP layer (`frames.py` codec + `socket.py` reassembly/streaming): both solid — SN starts at 1,
  wraps `& 0x0F` on send AND recv, padding trimmed via `[:total-len]`, WAIT bounded, reserved
  FlowStatus aborts. BUT the whole suite's largest message was 30 bytes (4 CFs); **nothing crossed
  the 4-bit SN wrap at 15→0** (needs >111 bytes = FF's 6 + 15×7), even though real Ford As-Built
  `ReadDataByIdentifier` blocks and long DTC lists routinely exceed it. Added
  `test_sequence_number_wraps_past_15_both_directions`: round-trips a 163-byte request (send-side
  wrap in `_stream_cfs`) AND a 183-byte response (recv-side wrap in `_reassemble`), asserting the
  response reassembles byte-exact, the emitted CF sequence numbers are exactly `1,2,…,15,0,1,…`, and
  the request frames reassemble to the exact bytes sent. Proved teeth BY MEASUREMENT (not argument):
  neutralized the mask in a throwaway process — send-side raises `CF sequence number must be 0..15,
  got 16`, recv-side raises `IsoTpSequenceError` (expected_sn 16 vs on-wire 0). +1 test → **418 green**.
- **Iter 101** (UDS reflash block-sequence wrap — untested safety-path boundary) — Audited the UDS
  client (`uds/client.py`): well-hardened (negative-response SID echo, responsePending 0x78 bound +
  P2* escalation, empty-seed rejection, DID/control-option echo checks all present & tested). Found
  the same untested-boundary class as iter 100 in the reflash path: `download()` wraps the TransferData
  blockSequenceCounter `seq = (seq+1) & 0xFF` (0xFF→0x00 per ISO 14229) and the ECU sim validates
  against its OWN `& 0xFF`-wrapped `_dl_seq` — but every reflash test topped out at 3 blocks, so
  **nothing crossed 255**, even though ANY real module reflash (hundreds of KB) does. Added
  `test_block_sequence_wraps_past_255`: forces 300 one-byte blocks (`download_max_block=3` → chunk 1)
  and requires byte-exact landing across the wrap. Ran it (PASS → wrap correct end-to-end, now guarded)
  and proved teeth BY MEASUREMENT: neutralizing the ECU-side `& 0xFF` makes block 256 fail with
  `0x73 wrongBlockSequenceCounter`. +1 test → **419 green**. (Reflash stays protocol-only / not
  CLI-exposed — this hardens correctness of code that already exists, no new surface.)
- **Iter 102** (DTC-scan resilience to a glitching ECU — untested corruption boundary) — Audited the
  DTC decode path (`obd/pids.py`): `decode_dtc`/`encode_dtc` are correct AND well-covered (all four
  P/C/B/U letters, C/B/U roundtrips, malformed rejection — no gap); the caller correctly strips the
  SID (`decode_dtcs(resp[1:])`). But `decode_dtcs` only tested a clean block + empty. The real
  untested boundary is a **lying/oversized count byte** or a truncated multi-frame body — where the
  `min(len(pairs)−odd, count*2)` cap is the ONLY thing stopping an `IndexError` that would crash the
  *whole-car* scan on one bad module (the skip-and-continue contract). Confirmed the robust behavior
  empirically, proved the cap's teeth BY MEASUREMENT (an uncapped `range(0,count*2,2)` IndexErrors on
  a lying count), then added `test_decode_dtcs_survives_lying_count_and_ragged_data` pinning four
  cases: over-claiming count, odd trailing byte dropped, `0000` pad skipped, count-0-wins. +1 test →
  **420 green**.
- **Iter 103** (PID scaling-formula coverage — untested distinct formulas) — Audited `decode_pid`'s
  whole `PID_TABLE`: every formula checks out vs SAE J1979, AND mapped each decode FUNCTION to its
  tests — 12 of the ~15 families already have known-value tests. Three had NONE, two of them distinct
  non-trivial scalings where a wrong factor is directly visible: `_module_voltage` (0x42, ÷1000 — a
  bad divisor reads 1.4 V for a healthy 14 V charging system) and fuel pressure (0x0A, ×3 kPa); plus
  vehicle speed (0x0D, identity — the single most-displayed live PID). Confirmed the expected values
  empirically (12.0 V / 300.0 kPa / 100.0 km/h) and added `test_control_module_voltage`,
  `test_fuel_pressure`, `test_vehicle_speed`. +3 tests → **423 green**. The Mode-06 decode, monitor
  readiness (`ready`/`not_ready`, incl. the fully-inspection-ready positive path), and supported-PIDs
  bit-ordering were all AUDITED this fire and found already solid + covered — no change made there.
- **Iter 104** (VIN corruption-rejection trio completed — one missing distinct branch) — Swept the
  OBD client's Mode-09 decode (`read_vin`, `_text_items`, `read_cvns`, `read_ecu_names`): found it
  comprehensively covered (multiframe VIN, truncated VIN, non-ASCII byte, multiple CALIDs, over-long
  seed, truncated-partial-dropped, corrupt-item-dropped, CVN hex, ECU names, unsupported-raises). ONE
  distinct branch of `read_vin`'s guard `if len(vin) != 17 or not vin.isalnum()` was untested: the
  `not vin.isalnum()` leg — 17 clean-ASCII bytes with an embedded punctuation char (e.g. `*`) decodes
  WITHOUT a UnicodeDecodeError, so the length guard and decode guard both pass, and only `isalnum()`
  stops a garbage VIN from being surfaced as the vehicle's identity. Confirmed empirically that
  without the guard the bogus `'1FMHK8D89*BA12345'` is returned, then added
  `test_read_vin_rejects_nonalphanumeric_ascii_same_length` — the third sibling of the truncated /
  non-ASCII rejection tests. +1 test → **424 green**.
- **Iter 105** (SAFETY — typed error on a corrupt backup store; PRODUCTION-code hardening) — Final
  safety re-read of `ford/asbuilt.py` (the highest-stakes surface — it writes a real car's config).
  The invariants are solid on re-read: unconditional backup gate with no bypass param, immutable
  first-capture, persist-before-commit, atomic temp+fsync+replace flush. Found ONE genuine gap by
  measurement: `FileBackupStore.__init__` loads the durable backup file with raw `json.load` +
  `bytes.fromhex`, so a CORRUPT file (disk fault, manual edit, old pre-atomic partial write) raised a
  raw `JSONDecodeError`/`ValueError` — bypassing the module's typed-error contract, so callers catching
  `AsBuiltError` (CLI restore, webapp) would crash with a traceback instead of an actionable message.
  This is the RECOVERY store — the one path back to factory bytes. Fix (production code): added
  `CorruptBackupStoreError(AsBuiltError)`, exported it, and wrapped the load to raise it — PRESERVING
  the safe fail-loud (never silently start empty, which would let a later `backup_block` capture
  modified bytes as the 'factory original'), only making the failure typed + actionable (names the
  file, says to move it aside). RED measured first (raw exceptions ≠ AsBuiltError); +1 test (3 subcases:
  invalid JSON / bad hex / non-dict top) → **425 green**. Happy-path persistence/round-trip unbroken.
- **Iter 106** (verify iter-105's claim end-to-end + HONEST correction of the record) — I put a claim
  in the iter-105 commit ("callers catching AsBuiltError (CLI restore, webapp) would crash with a
  traceback") and then verified it instead of trusting it. **The claim was imprecise on two counts:**
  (1) the CLI's command block catches `except Exception` broadly (cli.py:404) — so a corrupt backup
  file was NEVER a raw traceback; it already exited 3 with a *cryptic* json message. (2) The webapp
  does NOT construct `FileBackupStore` at all (only cli.py:221 does) — so naming it was wrong. **The
  fix's REAL, measured value:** the CLI error goes from cryptic `error: Expecting property name
  enclosed in double quotes…` to actionable `error: As-Built backup store at '…' is
  unreadable/corrupt (JSONDecodeError). Move it aside…` — same clean exit 3. Locked that real
  user-facing behavior with a CLI-level test `test_corrupt_backup_file_gives_actionable_cli_error`
  (asserts exit 3 + `unreadable/corrupt` + the file path in stderr). +1 test → **426 green**. Lesson
  re-affirmed: verify a claim before it ships, and correct the record openly when it was overstated.
- **Iter 107** (docs-currency — stale test counts) — With the code backlog exhausted, checked doc
  accuracy against reality: three current-state docs claimed a STALE test count while the suite is now
  426. `README.md` said "**412 tests, all green**" (line 9) and "`./run_tests.sh` # 260 tests"
  (line 89); `docs/PACKAGING.md` said "— 412 green —". Fixed all three DRIFT-RESISTANT rather than
  re-pinning a number that goes stale every time I add a test: "**400+ tests, all green**", "the full
  stdlib-unittest suite (no third-party deps); exit 0 == green", "full stdlib-unittest suite green".
  Left PROGRESS.md's per-iteration historical counts (102/114/…/254) UNTOUCHED — those are the frozen
  log of what was true at each iteration, correct as history. Repo-wide re-grep clean of stale hard
  counts. Docs-only; 426 green.
- **Iter 108** (Phase-4 gap found by pushing past a hold — GUI real-adapter connect untested) —
  Pressed harder on the recurring "native macOS GUI for the Vgate vLinker FS" instead of holding a
  third time. The `.app` launcher is a 12-line trampoline (logic tested via `run()`), so nothing there.
  But it pointed at a REAL gap: the controller's `connect()` has two branches — DEMO→simulator (well
  tested) and non-DEMO→`open_backend("elm327")` (the vLinker-FS path, the whole point of the GUI) —
  and EVERY webapp test used `connect(DEMO_PORT)`. The real-adapter branch was untested at the webapp
  layer. Verified the behavior empirically (fake silent serial → `connected=True`, banner
  `-- LIVE VEHICLE via elm327 :: UNVALIDATED backend (NEEDS ON-CAR CHECK) --`), then added
  `test_connect_real_port_uses_elm327_and_shows_unvalidated_banner`: locks that a non-demo connect
  builds the real `Elm327Transport` AND surfaces the honest UNVALIDATED/NEEDS-ON-CAR banner, never
  `SIMULATED` — the safety property that a user on a real adapter is not misled into trusting an
  unvalidated live path. No hardware needed. +1 test → **427 green**.
- **Iter 109** (real-adapter path proven as an INTEGRATED read — "verify the integrated artifact"
  applied to elm327) — The elm327 codec was unit-tested (line parse, send/recv over an injected port)
  and ISO-TP/OBD were tested over the SIMULATOR transport, but NOTHING exercised their COMPOSITION
  through the real wire codec — the exact class of gap that hid the dashboard-JS bug for ~60 iters
  ("each layer works" ≠ "the stack works"). Added `Elm327EndToEndReadTests` with a `ScriptedElmPort`
  fake vLinker-FS (`>` to AT cmds; emits queued ELM327 response blocks after each OBD payload) driving
  a real `Elm327Transport → IsoTpSocket → ObdClient` stack: (1) single-frame Mode-01 PID 0C read →
  decodes RPM 1000.0; (2) MULTIFRAME VIN read → `1FMHK8D89ABA12345`, which exercises the harder
  integration — the client's flow-control frame goes DOWN through elm327 send and the consecutive
  frames come UP through elm327 recv. Both verified empirically first. No hardware. +2 tests →
  **429 green**. (The elm327 *live timing/handshake* is still NEEDS ON-CAR CHECK; this proves the
  codec composition, not the physical device.)
- **Iter 110** (slcan real-adapter composition — coverage parity with elm327) — Completed the
  integration-coverage sweep: the OTHER shipped real backend, `SlcanTransport` (CANable, `--backend
  slcan`), had the same untested-composition gap iter 109 closed for elm327. Added
  `SlcanEndToEndReadTests` (mirror of the elm327 pair) with a `ScriptedSlcanPort` fake CANable driving
  a real `SlcanTransport → IsoTpSocket → ObdClient` stack: SF Mode-01 PID 0C → RPM 1000.0, and the
  MULTIFRAME VIN → `1FMHK8D89ABA12345` (flow-control down + consecutive frames up through slcan). Both
  verified empirically first — which CAUGHT MY OWN FIXTURE BUG: I'd hand-written the multiframe slcan
  lines with the wrong DLC nibble (`t7E81…` dlc 1 vs `t7E88…` dlc 8; slcan concatenates id+dlc with no
  separator), and the empirical run surfaced it as an ISO-TP "SF truncated" before any test was
  written. Fixed the fixtures, re-verified, then committed. +2 tests → **431 green**. Both real
  backends now have full-stack composition coverage; slcan live timing remains NEEDS ON-CAR CHECK.
- **Iter 111** (real-adapter ERROR path end-to-end — the #1 first-drive event) — iters 109/110 proved
  the SUCCESS path; but on a real car the most COMMON event is an unsupported PID or a module that
  never answers. Added the error-path composition tests both backends were missing: elm327 `NO DATA`
  (the adapter's status line for "nothing answered") and slcan silent-bus (no CR-terminated frame
  arrives — the raw-CAN equivalent). Verified empirically first: both surface a clean
  `ObdError('no response to mode 0x01')` through the full stack (transport → ISO-TP None → ObdClient),
  no hang, no crash. Locked as `test_no_data_surfaces_clean_error_not_a_hang` (elm327) +
  `test_silent_bus_surfaces_clean_error_not_a_hang` (slcan). This is the robustness that decides
  whether the GUI cleanly says "no response" or freezes on the first real query. +2 tests →
  **433 green**.
- **Iter 112** (29-bit extended addressing proven end-to-end — the As-Built path) — A genuinely
  DIFFERENT code path from the 11-bit thread: Ford ENHANCED diagnostics (the As-Built coding half of
  the tool's name) use 29-bit addressing `0x18DA{TA}{SA}`, which is a distinct elm327 branch (the
  4-token extended header parse) + extended ISO-TP framing. Confirmed it's a REAL used path
  (`ford/addressing.py extended_module()` returns `is_extended=True` pairs, exported/public) that was
  unit-tested in isolation but NEVER composed end-to-end — every prior integration test was 11-bit.
  Verified empirically, then added `test_extended_29bit_uds_read_end_to_end`: a UDS
  `ReadDataByIdentifier(0xF190)` over the REAL `extended_module(0x10)` pair (0x18DA10F1/0x18DAF110)
  decodes `b"123"` through the whole extended stack (elm327 4-token parse → extended ISO-TP → UDS).
  elm327 only — it's the owner's vLinker FS and carries the trickier multi-token parse; slcan's
  extended form is a simpler single 8-hex token already unit-tested (replicating there = padding).
  +1 test → **434 green**. (Live 29-bit handshake stays NEEDS ON-CAR CHECK.)
- **Iter 113** (flagship whole-car scan proven over a REAL backend — present/absent) — Checked whether
  the scan was truly "implied" by the per-module tests: it probes via `UdsClient.read_data_by_identifier`
  and classifies present (any answer) vs absent (all raise `UdsError`), so a real-backend scan's
  correctness hinges on a subtle mapping the simulator can't exercise — elm327 `NO DATA` must become a
  `UdsError` so an absent module is marked absent, not crash the scan or mis-report it present. Verified
  empirically then added `RealBackendScanTests.test_scan_over_elm327_marks_present_and_absent`: a
  header-routing fake vLinker-FS answers RDBI for PCM (header 7E0 → VIN "123") and `NO DATA` for TCM
  (7E1); `scan_vehicle` correctly reports `[OK] PCM` + `[--] TCM` in one scan. Proves the flagship
  user action (whole-car scan) over the real wire codec, exercising the mixed present+absent
  distinction never covered before. +1 test → **435 green**.
- **Iter 114** (DTC database — safe series completions; genuine FUNCTIONAL value) — A different
  category from the test-coverage thread: actual product value. The curated DTC table stopped
  mid-series — misfire at cyl 6 (P0301-06), injectors at cyl 4 (P0201-04), ignition coils at B
  (P0351-52) — so a common V6/V8 Ford (F-150, Mustang GT, Explorer) with a cyl-7/8 misfire, cyl-5-8
  injector, or coil-C-H fault fell to the structural fallback instead of a named definition. Added the
  12 mechanical SAE J2012 SIBLINGS that complete those series (P0205-08, P0307-08, P0353-58) — safest
  possible expansion (each follows the EXACT verified pattern of an already-curated entry; the design
  rule is "extend deliberately, never invent"). Proper TDD: wrote `test_completed_generic_series_siblings`
  FIRST, confirmed RED (`P0307` → definition None), then added the codes → GREEN. +1 test / +12 codes →
  **436 green**. (Unknown codes still get the honest structural fallback; nothing invented.)
- **Iter 115** (SAFETY/robustness — bus-noise IsoTpError no longer 500s the GUI) — Real PRODUCTION
  bug found by tracing the GUI error path: the controller's six graceful-degradation handlers caught
  `(ObdError, KeyError, ValueError)` but NOT `IsoTpError` — a separate exception hierarchy. So an
  unsupported PID degraded to a blank, but a malformed ISO-TP frame (bus NOISE on a real car —
  cross-talk, marginal wiring, flaky adapter) leaked `IsoTpError` past `read_pid` into an HTTP 500,
  and on the 1 Hz `live()` dashboard one noise frame would error the whole sample. Verified the leak
  empirically (`read_pid` on a PCI-nibble-0x9 frame raised `IsoTpError`), wrote the RED test, then
  added `IsoTpError` to all six catch sites (read_pid, live, dtc_states, monitor_tests, calibration
  `_safe`, freeze) so bus noise degrades exactly like an unsupported read everywhere. Caught my OWN
  `replace_all` miss — line 175 (`read_pid`, different indent) wasn't updated by the bulk edit; grep
  verification (5≠6) surfaced it, fixed it. +1 test → **437 green**.
- **Iter 116** (systematic sweep of the iter-115 bug class — DataLogger sibling) — Treated iter 115 as
  a PATTERN, not a one-off: swept every `except .*(ObdError|UdsError|IsoTpError)` site in the codebase
  for a missing sibling hierarchy. Found the exact same gap in `services/datalog.py`: `DataLogger.sample()`
  caught `(ObdError, KeyError, ValueError)` but not `IsoTpError`, so a malformed frame (bus noise)
  during logging would abort the WHOLE sample/run — and the DataLogger backs BOTH the CLI `log` command
  and the webapp CSV export. Added `IsoTpError` (RED test first: `NoisyClient.current_data` raising
  IsoTpError aborted `sample()`; GREEN blanks the cell). The `dtc_scan`/`module_scan` UDS sites already
  catch `IsoTpError`+`UdsError` (complete). Left `obd/client.py:142` (`read_supported_pids` `except
  ObdError: break`) deliberately unchanged — a corrupt frame there is a genuine truncate-vs-propagate
  judgment call, and the outer layer handles the leak; changing it blindly could silently truncate the
  PID list. +1 test → **438 green**.
- **Iter 117** (JS robustness — live poll survives a lost connection; browser-VERIFIED) — Applied the
  "verify the integrated artifact" lesson to the one path only checked on the happy side: the GUI's JS
  error handling. Server-error responses were handled everywhere (`j.error` checks), but `pollLive()`
  runs on a 1 Hz `setInterval` with NO try/catch around its `fetch`/`json`, so a NETWORK-level rejection
  (server restart, a slow-serial timeout) spammed unhandled rejections every second with a frozen
  dashboard. Wrapped the live fetch in try/catch → shows "live polling stopped — lost connection to
  FordScope" and calls `stopLive()`. **Verified BY RUNNING** (not claimed — JS bugs are invisible to
  Python tests, the dashboard-JS lesson): `node --check` on the extracted JS (parses), then Claude
  Preview — connected demo (happy path live still renders RPM+sparkline), then overrode `fetch` to
  reject and confirmed the table shows the message AND `liveTimer===null` (polling stopped), console
  clean. Added a structural regression guard (`test_live_poll_handles_lost_connection`). +1 test →
  **439 green**. (Transient preview launch.json created in the cwd for the run, removed after.)
- **Iter 118** (connect UX — progress feedback + failure handling; browser-VERIFIED) — Investigated the
  high-value real-world concern first: does connecting to an UNRESPONSIVE adapter (wrong port / unpowered
  / car off — very common) HANG the tool? Checked `open_serial_port` — the pyserial port is opened with
  `timeout=1.0`, so `_read_until_prompt` breaks on empty reads: NO hang (already handled, honest clean
  result). But it surfaced a real Phase-4 GUI issue: elm327 `open()` does ~7 handshake reads, so a slow/
  dead real adapter blocks connect for up to ~7s, and `connect()` only updated the banner AFTER the fetch
  resolved — so the GUI showed NOTHING and looked frozen. Fixed: show immediate `Connecting…` feedback,
  and (applying iter-117's lesson) wrapped the connect fetch in try/catch → `Connection failed — is the
  FordScope app still running?` on a network rejection instead of a silent no-op. **Verified BY RUNNING**:
  `node --check` (parses), then Claude Preview drove all three — immediate banner `Connecting…`, happy
  path → `SIMULATED` banner, `fetch`-reject → the failure message; console clean. Structural regression
  guard added. +1 test → **440 green**. (Transient launch.json created for the run, removed after.)
- **Iter 119** (health-report graceful-degradation — documented invariant was untested) — Investigated
  the flagship one-click report's robustness: does one failing section kill the whole report? The CODE
  is correctly robust — every section (VIN, calibration, readiness, DTCs, freeze, Mode 06, live stats)
  is wrapped in its own `try/except Exception`, and the docstring promises "one failing section is noted,
  not fatal." But the iter-108 lesson bit again: that documented CRITICAL property was UNtested — every
  health_report test was happy-path. On a real car sections fail routinely (no Mode-09 calibration,
  Mode 06 unsupported, a glitching read), so a refactor dropping one `try/except` would crash the
  flagship output on real cars with a green suite. Added `test_health_report_survives_a_failing_section`:
  forces the VIN section to raise, asserts the report still completes with `VIN: (unavailable)` AND a
  later section (`Trouble codes:` / P0143) present. Teeth are structural (patch-to-raise + assert-returns
  guards the try/except). +1 test → **441 green**.
- **Iters 120–121** (grounded HOLDS, no commit) — Investigated fresh high-stakes surfaces and found
  them correct AND comprehensively tested, so held rather than manufacture: (120) documented-invariant
  coverage sweep — grepped every "must/never/atomic/immutable/not-fatal" invariant and spot-checked each
  against a named guarding test (backup gate, atomic flush, snapshot atomicity, empty-seed, VIN, DTC
  never-invent — all covered); (121) the As-Built checksum/format machinery (sum-to-zero, all edit
  methods keep-valid, bounds/value errors, roundtrip) and the FeatureCoder incl. its honesty invariant
  (`test_every_example_feature_is_flagged_unverified`) — all correct + tested. Aimed at where a serious
  bug would hurt most (safety-critical write path); clean there is strong completeness evidence.
- **Iter 122** (doc-accuracy + drift guard — on-car banner) — After 121, checked `FIRST_RUN.md` (the R8
  first-run guide): genuinely good, but line 27 quoted the live banner in backticks (implying a literal)
  as `LIVE — UNVALIDATED (NEEDS ON-CAR CHECK)` while the real banner (confirmed by running) is
  `-- LIVE VEHICLE via elm327 :: UNVALIDATED backend (NEEDS ON-CAR CHECK) --`. Fixed the doc to the exact
  string so the owner matches what they see on-car, and — per the iter-99 "guard the root cause" pattern
  — added `test_first_run_doc_quotes_the_exact_live_banner` keeping the doc byte-exact with `LIVE_BANNER`
  (fails if either drifts). +1 test → **442 green**.
- **Iter 123** (holistic browser re-verification of the integrated UI — post-accumulated-changes) —
  Iters 108–122 changed shared webapp code (IsoTpError across 6 controller handlers, live-poll +
  connect JS); each was verified individually, but not the WHOLE UI composed together. Applied the
  "verify the integrated artifact, not the pieces" principle holistically: launched the real webapp
  (Claude Preview), connected the demo, and drove EVERY function in one session — scan / dtc / vin /
  health-report / readiness / freeze / calibration / dtc-states / Mode-06 monitors / drive-cycle /
  supported-PIDs (3 buttons) / read-PID / live dashboard (3 PIDs). All rendered correct demo data
  (VIN 1FMHK8D89ABA12345, P0143 w/ description, RPM 1000, Mode-06 O2 PASS, …), **zero console errors,
  zero failed network requests**. The native-macOS-GUI deliverable (Phase 4) is confirmed working
  end-to-end after all recent changes, not just piece-by-piece. Verification only, no code change;
  442 green. (Transient launch.json created for the run, removed after.)
- **Iter 124** (GUI launch robustness — clean message on a port conflict) — Fresh Phase-4 angle: `run()`
  binds a fixed port 8737, so launching a SECOND instance (or double-clicking the future `.app` twice)
  hit a raw `OSError: [Errno 48] Address already in use` traceback — the first thing a user would see.
  Verified the raw crash empirically, wrote the RED test (`run()` on a busy port raised), then wrapped
  `create_server` in `run()` to catch the bind failure and print a clear, actionable message
  (`FordScope could not start on … It may already be running — open http://…/ or close the other
  instance`) and return cleanly. Added `import sys`. **Verified BY RUNNING** the real entry point
  (`python -m fordscope.webapp`) on a held port: exit 0, no traceback, the clean message on stderr.
  Existing keyboard-interrupt test unaffected (the wrap only catches OSError). +1 test → **443 green**.
- **Iter 125** (CLI Ctrl-C exits cleanly — the OTHER entry point's edge) — Applied iter-124's lesson
  (entry-point edges cluster late UX bugs) to the CLI. The webapp's `run()` catches `KeyboardInterrupt`,
  but the CLI's `main()` command block catches `except Exception` — which does NOT catch
  `KeyboardInterrupt` (it's `BaseException`), so Ctrl-C during a slow command (`log --interval`, a
  real-adapter scan) dumped a traceback. Verified empirically (a KeyboardInterrupt-raising command
  propagated), wrote the RED test, then added `except KeyboardInterrupt: print("Interrupted."); return
  130` (the conventional Ctrl-C exit code) before the `except Exception` — the CLI analog of the
  webapp's clean Ctrl-C handling; the `finally` still closes the live bus. +1 test → **444 green**.
- **Iter 126** (README banner sibling of the iter-122 fix + guard the CLASS) — Cross-checked the README
  against the current feature set (accurate — verified "35 decoded PIDs" == the actual PID_TABLE count).
  But found the SIBLING of iter 122's fix: README.md:70 had the same backtick-quoted banner PARAPHRASE
  `LIVE — UNVALIDATED (NEEDS ON-CAR CHECK)` while the real banner is `-- LIVE VEHICLE via elm327 ::
  UNVALIDATED backend (NEEDS ON-CAR CHECK) --`. I'd fixed FIRST_RUN but not swept for siblings, and the
  iter-122 guard only checked FIRST_RUN — which is exactly why the README drifted unnoticed. Swept all
  docs (README was the only remaining sibling), fixed it to the exact banner, and generalized the guard
  → `test_docs_quote_the_exact_live_banner` now covers BOTH docs (subTest per file), so the class can't
  drift again. No net test count change (renamed+extended the guard). 444 green.
- **Iter 127** (proactive class guard — README command list ↔ argparse) — Applied iter-126's explicit
  lesson ("guard the class BEFORE it drifts, like the banner did") to the next doc-quotes-code literal:
  the README's CLI command reference. Verified it's currently EXACT (11/11 vs the real argparse
  subcommands, no missing/extra), so no fix — but added `test_readme_documents_every_cli_command`, which
  iterates the REAL `_build_parser` subcommands and asserts each appears in the README (subTest per
  command). Fails if a command is added to the CLI but left undocumented (a real command missing =
  undiscoverable). Teeth proven by measurement: real commands document True, a hypothetical
  `reflash-BOGUS` False. This is the correct proactive application of the guard-the-class lesson (the
  banner had to drift first; this one won't). +1 test → **445 green**.
- **Iter 128** (elm327 init robustness to realistic clone-adapter quirks — the R8-closest surface) —
  Aimed a fresh investigation at the highest-stakes-for-on-car surface I can verify without hardware:
  the elm327 init handshake. A real ELM327 clone's `open()` is noisy — ATZ returns a version banner
  (`ELM327 v1.5`), a command can echo before ATE0 takes effect, protocol detection emits
  `SEARCHING...`. Confirmed by measurement that `open()` consumes all of it cleanly (each
  `_read_until_prompt` reads to the `>` prompt) and a subsequent read returns `None` (version-string
  noise doesn't leak as a fake CAN frame). The existing init test only checked the WRITE sequence, not
  survival of quirky READ content — a genuine gap on the surface that matters most for R8. Locked it:
  `test_open_survives_realistic_clone_adapter_quirks`. Live TIMING stays NEEDS ON-CAR CHECK; this pins
  the codec's robustness to the wire CONTENT. +1 test → **446 green**.
- **Iter 129** (multiframe reassembly when CFs arrive in separate reads — real-adapter timing) — Kept
  aiming at the high-stakes real-adapter path. The iter 109/110 multiframe tests fed all consecutive
  frames in ONE `>`-terminated block, but a real adapter with inter-frame TIMING returns CF1 in one
  read and CF2 in the next. ISO-TP loops `recv()` and elm327 buffers per `>`-block, so the composition
  SHOULD handle it — confirmed by measurement (VIN reassembles byte-exact across separate reads), then
  locked `test_multiframe_read_with_consecutive_frames_split_across_reads`. This is the same
  "integration composition individual layer tests miss" class as the elm327 end-to-end thread — the
  split-across-reads variant was the untested one, and it's exactly what happens reading a VIN / long
  As-Built block over a real adapter. +1 test → **447 green**.
- **Iter 130** (multiframe read survives interleaved bus traffic — the live-bus arrival pattern) — Third
  in the "untested ARRIVAL PATTERNS, not just untested inputs" thread. A live CAN bus chatters constantly
  (PCM/ABS/BCM), so in raw ELM327 mode the adapter can surface frames from OTHER arbitration IDs
  interleaved with our module's response — including BETWEEN the FF and the CFs while we wait. ISO-TP's
  `_recv_matching` must skip the non-matching IDs and reassemble only ours. Confirmed by measurement (VIN
  reassembles byte-exact with a 0x7DF noise frame injected before the CFs), then locked
  `test_multiframe_read_survives_interleaved_bus_traffic`. The composition (elm327 per-`>`-block buffering
  × isotp skip-non-matching) was untested end-to-end. +1 test → **448 green**. — Fixed a materially-stale/inaccurate `docs/DESIGN.md`: §3
  listed a **non-existent `OpenportTransport` (Tactrix)** and OMITTED the real `Elm327Transport`
  (the ELM327/OBDLink/vLinker-FS backend the tool actually ships), and §4 had **no Phase 4** (the
  whole native-macOS web app). Corrected the layer diagram (real backends, webapp top layer, the
  richer obd surface) + added Phase 4. `FIRST_RUN.md` checked — already current (leave it). Docs-
  currency sweep now complete (README iter 88, DESIGN iter 89, FIRST_RUN current). 412 green.
- **Iter 131** (multiframe WRITE path survives interleaved bus traffic — closing the read/write
  asymmetry) — The iter 109/110/129/130 multiframe integration tests were ALL reads (VIN/DID); the
  SEND substrate every As-Built / UDS *write* rides on — send the First Frame, await the ECU's
  FlowControl AMID live-bus chatter, then stream the Consecutive Frames — had never been composed
  end-to-end through the elm327 wire codec. `_await_cts` leans on the same `_recv_matching` skip logic
  iter 130 only proved on the read side. Confirmed by measurement (an 11-byte payload segments to the
  hand-derived ISO-TP wire bytes `100BA0A1A2A3A4A5` + `21A6A7A8A9AA0000` and streams IN ORDER past a
  0x7DF noise frame injected before the FC), straddle-checked that the identical path *raises*
  IsoTpTimeout when only the noise arrives (so the assertion is load-bearing, not vacuous), then locked
  `test_multiframe_send_awaits_flow_control_past_bus_noise`. +1 test → **449 green**. — The real-adapter
  wire-path hardening thread (128 noisy init · 129 split reads · 130 interleaved read · 131 interleaved
  write) is now essentially exhausted; per ROADMAP "padding is the enemy," do NOT manufacture more
  arrival-pattern micro-tests. **NEXT (owed, higher-value, do not skip for busywork):** the
  safety/security/honesty/robustness AUDIT re-run and the R3/R5 diagnostic research re-run — both FAILED
  rate-limited on 2026-07-04; run them SERIALIZED (never overlapping) per that day's rate-limit lesson.
- **Iter 132** (owner supplied a real As-Built map — ingest it, honestly) — The owner handed over the
  **2GFusions "Ford As-Built Data Mods" sheet (DanMc85, tid=4573)** — the canonical community source
  the research already cited. This is exactly what ROADMAP anticipated ("real maps come from
  FORScan/the owner, labeled UNVERIFIED"), so it supersedes the generic NEXT for one iteration.
  Preserved the full **2014+ MY** transcription in `docs/reference/asbuilt_2gfusions_fusion_2gen.md`
  (provenance-headed, scoped to the 2016 S; 2013-MY variants excluded — different blocks). Added a
  structured, tested catalog `ford/fusion_2016_asbuilt.py` (`AsBuiltFeatureRef` + 18 entries) plus
  `additive_checksum`. **Honesty gates:** deliberately restricted to features on FordScope's CONFIRMED
  modules (BCM 726 / IPC 720 / APIM 7D0); every entry `verified=False` + sourced; it's a REFERENCE
  catalog, NOT wired to live read/write (the block→UDS-DID map is not on file → stays NEEDS ON-CAR
  CHECK). **Verified by measurement:** +8 tests → **457 green**. Cross-checks that genuinely straddle —
  every module address is a confirmed `fusion_2016` module, every block label matches its module
  address, and every full-line value (`726-15/16/17`) carries a correct Ford additive checksum (the
  helper pinned to the report's own `760-01-04 3733 → D6` worked example, then applied to all full-line
  values, so a one-nibble transcription slip fails the suite). The sheet's other modules
  (DDM/PDM/ACM/SCCM/FCIM/HSWM) stay in the reference doc until their addresses are confirmed on-vehicle.
  [Commit BLOCKED this session — same `.git` write-restriction as iter 131; changes saved in the
  working tree for a host-side commit.]
- **Iter 133** (expand the As-Built catalog to the remaining modules — with a real honesty tier) —
  Grew `ford/fusion_2016_asbuilt.py` past the confirmed core (726/720/7D0) to the sheet's other
  modules: **DDM 740, PDM 741, ACM 727, SCCM 724, FCIM 7A7, HSWM 714, FCDIM 7A5** — +10 entries →
  **28 across 10 modules** (18 confirmed + 10 plausible). The honest way to do this was NOT to
  silently accept unconfirmed addresses: added a per-entry `module_confidence`, registered the new
  modules in `fusion_2016.py` as **plausible** (with trim caveats — premium/Sony audio and the
  heated-wheel module are likely ABSENT on a base 2.5L S), and replaced iter 132's confirmed-only
  gate with a **registry-consistency gate** — each entry's `module_confidence` must mirror
  `fusion_2016`'s tag, and any module absent from the registry can never be `confirmed`. Also fixed
  the model-year test: `2013+` / `2013-2016` ranges legitimately cover a 2016 (the old check wrongly
  rejected any "2013" substring), so it now asserts each entry's MY range *covers 2016* while still
  excluding 2013-only blocks. **Verified by measurement:** +1 net test → **458 green**; the
  confirmed set is unchanged (`test_cli` + `test_fusion_2016` still green, so the confident scan is
  untouched). Straddle-checked both gates — a DDM entry mistagged `confirmed` is rejected
  (registry says plausible), and a bare `2013` MY fails the coverage check. Still reference-only
  (no block→DID map) and commit still env-blocked (host-side commit pending).
- **Iter 134** (surface the community As-Built catalog through the CLI — READ-ONLY, honesty-
  preserving) — Iters 132–133 built the 28-entry/10-module catalog but it was data-only and
  invisible to a user; this iteration makes it browsable without touching the live path at all.
  New `ford/asbuilt_catalog_view.py`: `filter_features(catalog, module=, search=)` (module accepts
  a name like "BCM"/"IPC" OR a numeric/hex address like `0x726`; search is a case-insensitive
  substring over name+key; both AND together, no match -> `[]`, never raises) and
  `format_catalog(...)` (renders the `COMMUNITY-SOURCED · UNVERIFIED · NEEDS ON-CAR CHECK` header +
  the `SOURCE` line on EVERY render — including an empty/no-match result — then groups by module,
  each feature showing name/block_line/`module (module_confidence)`/bits/options as
  "value = meaning"). `webapp/controller.asbuilt_features(module=, search=)` returns the same
  filtered set as structured dicts (key/module/module_addr/module_confidence/block_line/bits/kind/
  options/my/verified/note) — deliberately has NO `_require()` and never touches `self.transport`,
  so it can't be confused with a live read. CLI `asbuilt-features [--module M] [--search S]`
  (static listing, dispatched before `open_backend`, like `features`). Wired
  `filter_features`/`format_catalog` into `ford/__init__.py`'s exports (matching the
  `fusion_2016_asbuilt` convention) and `FUSION_2016_ASBUILT`/`format_catalog` into `cli.py`'s
  import block. **Verified by measurement:** +24 net tests (16 filter/render unit tests, 4
  controller tests, 4 CLI tests) → **482 green**. Straddle-checked: `module="IPC"` returns exactly
  the 4 hand-counted 0x720 entries and excludes a BCM-only block_line; `search="honk"` matches
  both door/lock honk features (incl. one whose match is in the KEY not the display name) and
  excludes an unrelated gauge feature; `module="IPC"` AND `search="honk"` (BCM-only) correctly
  ANDs to empty; a garbage `--module 0xZZZZ` and an empty/whitespace filter both degrade cleanly
  (full catalog or `[]`) with no crash and the honesty header still printed. Also caught and fixed
  a real drift-guard failure my own change triggered: the pre-existing
  `test_readme_documents_every_cli_command` (iter 126) failed because `asbuilt-features` wasn't in
  the README yet — added it to the command list + a "What it does" bullet, so the guard now passes
  because the docs are actually current, not because the guard was loosened. Deliberately did NOT
  touch `fusion_2016_asbuilt.py`'s data (values/meanings/verified flags byte-identical — confirmed
  via `git diff`), the never-build list, or wire anything to live UDS read/write: this is a pure
  query+format layer over the existing static tuple. Commit still env-blocked this session (same
  `.git` write-restriction as iters 131–133; changes left in the working tree for a host-side
  commit).
- **Iter 135** (surface the community As-Built catalog in the native-macOS web UI — mirrors iter
  134's CLI work; READ-ONLY, honesty-preserving) — the catalog was already browsable from the
  terminal but invisible from the Mac app, which is the tool's primary daily-driver surface. New
  `GET /api/asbuilt-features` on `webapp/server.py` (optional `module`/`search` query params →
  `controller.asbuilt_features(...)`, already built in iter 134): deliberately does **not** call
  `controller.snapshot()`/require a connection — matches the controller method's own contract that
  it never touches `self.transport`. Every response (including an empty/no-match result) carries
  top-level `caveat`/`source` fields sourced from a new public `asbuilt_catalog_view.CATALOG_CAVEAT`
  constant (aliases the existing private `_HEADER` so the JSON and `format_catalog()`'s text render
  stay byte-identical, never duplicated/drifted) + `fusion_2016_asbuilt.SOURCE`, re-exported through
  `ford/__init__.py`. Browser page: a new "As-Built catalog (reference)" row (module/search text
  inputs) + `showAsBuiltCatalog()` (fetch → render a table with Feature/Module/Confidence/Block-line/
  Options columns, `escapeHtml`-sanitized) into a dedicated `#asbuilt` div, PLUS a static
  always-visible `COMMUNITY-SOURCED · UNVERIFIED · NEEDS ON-CAR CHECK` caveat line in the page
  template itself (belt-and-suspenders: visible even if the fetch hasn't completed/fails) and a
  second dynamic render of the endpoint's own `caveat`/`source` fields on every successful fetch
  (including empty results) so the two can never drift apart. **Verified by measurement:** +8 net
  tests (5 endpoint tests: no-connection-required, module filter → exactly the 4 hand-counted
  IPC/0x720 entries, search="honk" → exactly `{door_close_double_honk, lock_honk_2x_fob}`, no-match
  → `[]` not an error, blank params → full catalog; 2 tests pinning the JSON carries the real
  `SOURCE` constant + caveat text on both a populated AND an empty/no-match response; 1 structural
  page test) → **490 green**. Adversarially probed beyond the unit tests by running the live server
  directly (not asserted-and-trusted, executed): a garbage `?module=0xZZZZ` → 200/no crash (caught
  internally, pre-existing `_module_matches` guard); numeric `?module=726` correctly resolves to the
  BCM hex address → 13 entries (hand-recount of the BCM rows in `fusion_2016_asbuilt.py` confirms
  13); both filters ANDing to empty still carries the caveat; a bare `?` → full 28-entry catalog; a
  `<script>` string in `search` → clean empty match, nothing reflected. Verified the browser-side
  JS by RUNNING it, not by inspection: extracted the real served `<script>` block and executed
  `showAsBuiltCatalog()` in Node against a fake DOM/fetch four ways — positive render (caveat +
  SOURCE + module_confidence="confirmed" + feature name + block_line all present), empty/no-match
  render (caveat/SOURCE still present, "No matching As-Built features." shown), a rejected fetch
  (caught, no uncaught throw, shows a plain error string), and an XSS probe (a hostile
  `<img onerror=...>` feature name comes back HTML-escaped, not executable) — all four PASS,
  pasted verdicts in-session. `node --check` confirms the page's `<script>` block is still valid
  JS and the raw-string invariant (`test_index_html_is_raw_so_js_escapes_survive`) still holds.
  README: reworded the existing "Community As-Built catalog browser" bullet to cover both surfaces
  (CLI + the new web section) and the new endpoint; no CLI-command-list drift (no command was
  added this iteration, so `test_readme_documents_every_cli_command` is unaffected) and there is no
  equivalent drift-guard for `/api/*` endpoints in this repo (checked — only the CLI list is
  guarded), so none needed fixing. Un-automated sliver, honestly labelled: no browser-automation
  tooling was available in this environment, so the actual rendered PIXELS were never eyeballed —
  the served-HTML/JS structure and the Node-executed rendering logic are verified by
  measurement, but a literal screenshot check is `NEEDS ON-CAR`-style manual confirmation, owed to
  the owner. Deliberately did NOT touch the catalog data, any `verified` flag, or wire anything to
  live UDS read/write — pure display layer, same as iter 134. Commit still env-blocked this session
  (same `.git` write-restriction as iters 131–134); changes left in the working tree for a host-side
  commit.
- **Iter 136** (user-facing As-Built line CHECKSUM tool — compute + verify) — after an As-Built
  line is hand-edited, the trailing per-line checksum byte must be recomputed or the module
  rejects/mis-reads it; `additive_checksum` (iter 134, spec-verified against the documented
  worked example) existed only as an internal cross-check, not a user tool. Added two pure
  helpers next to it in `ford/fusion_2016_asbuilt.py`: `parse_hex_bytes(text)` (flexible hex
  parsing — accepts a bare run `"0101010101"` or spaced pairs `"01 01 01 01 01"`, raises
  `ValueError` on odd-length/non-hex/empty input, never crashes or silently truncates) and
  `verify_full_line(block_line, full_line_hex)` (re-derives the additive checksum over label+data
  and compares it to the trailing byte, returning an `AsBuiltLineCheck(valid, expected_checksum,
  actual_checksum)`; raises `ValueError` on a malformed label or bad hex). New CLI subcommand
  `asbuilt-checksum <block-line> <hex>` (compute mode; prints the checksum byte) with a
  `--verify` form (full-line mode; prints VALID/INVALID + both the stored and expected byte) —
  wired as a static/pure listing (no `--backend`/`--port` needed, same tier as `asbuilt-features`).
  Both re-exported through `ford/__init__.py`. **Every output path — compute, VALID, and
  INVALID — prints a fixed one-line note that this checks the LINE checksum only and does NOT
  verify the values are correct for the vehicle (`NEEDS ON-CAR CHECK`)**, so a green checksum can
  never be read as "safe to write." TEST-FIRST, expected values hand-derived independently of the
  implementation (see the arithmetic in the test comments, cross-checked by hand before writing
  any code): `760-01-04` + `37 33` → `0xD6` (the spec's own worked example, re-used); `726-17-01`
  + `01×5` → label(07+26+17+01=0x45) + data(5) = `0x4A`; full line `726-17-01`/`01010101014A` is
  VALID (expected==actual==0x4A); flipping the first data byte to `02` (`02010101014A`, same
  stored checksum `4A`) is INVALID with hand-derived expected byte `0x4B` (label 0x45 + flipped
  data 6 = 0x4B). Also covered: spaced-hex parsing agrees with bare-hex, and clean `ValueError`
  (never a crash) on odd-length hex, non-hex characters, empty input, and a malformed label with
  no dashes (both too-few and too-many dash-splits — confirmed by hand that Python's own tuple-
  unpack on `.split("-")` already raises `ValueError` for both, so no extra validation code was
  needed there). **Verified by measurement:** 14 new tests in `test_fusion_2016_asbuilt.py`
  (`ParseHexBytesTests` ×6, `VerifyFullLineTests` ×8) + 6 new CLI tests in `test_cli.py`
  (compute/spaced-hex/verify-valid/verify-invalid-with-expected-byte/bad-hex-clean-error/
  no-vehicle-needed) → baseline 490 green → **`Ran 509 tests in 1.744s … OK`**. Manually ran the
  built CLI (not just unit-asserted) for all six shapes — compute, spaced-hex compute, verify
  VALID, verify INVALID, bad hex (`01Z` → clean `error:` on stderr, exit 2, no traceback), and a
  malformed label (`726` with no second dash → clean error, exit 2) — every line of real stdout
  pasted and checked by eye against the hand-derivation above. README: added a new "As-Built line
  checksum tool" bullet + the `asbuilt-checksum <block-line> <hex> [--verify]` entry in the
  command list, which the pre-existing `test_readme_documents_every_cli_command` drift-guard
  caught red before the fix (confirmed the guard actually fired, not just assumed). Adversarially
  reviewed the diff (`git diff` on `cli.py`/`ford/__init__.py`; the new `fusion_2016_asbuilt.py`/
  `test_fusion_2016_asbuilt.py` files are untracked from iter 134, so no linear diff exists for
  them — read the final file in full instead): confirms no new UDS DID, no live vehicle I/O, no
  write path — this is pure hex/int arithmetic on user-supplied strings, offline. Commit still
  env-blocked this session (same `.git` write-restriction as iters 131–135); changes left in the
  working tree for a host-side commit.
- **Iter 137** (As-Built line DECODER / reverse-lookup — the capstone read: given a raw
  block-line label off a FORScan screen, what is it and does its checksum add up) — every prior
  As-Built CLI tool required already knowing a feature's name (`asbuilt-features`) or already
  having a hex value to checksum (`asbuilt-checksum`); this closes the loop for the actual user
  moment — staring at `726-41-02` on a screen with no idea what it is. New pure helper
  `features_at_block_line(block_line, catalog=FUSION_2016_ASBUILT)` in `ford/fusion_2016_asbuilt.py`
  (case-insensitive, whitespace-tolerant exact match on `block_line`; empty/whitespace/garbage
  input and an unknown label all degrade to `[]`, never raise — placed after the catalog tuple
  since its default argument references `FUSION_2016_ASBUILT`) and a new renderer
  `format_block_line_lookup(block_line, features)` in `ford/asbuilt_catalog_view.py` (mirrors
  `format_catalog`'s honesty contract exactly: the `COMMUNITY-SOURCED · UNVERIFIED · NEEDS
  ON-CAR CHECK` header + `SOURCE` on every render including the no-match case, which prints a
  clean "No catalog feature recorded at this line — reference only" message instead of nothing).
  New CLI subcommand `asbuilt-lookup <block-line> [--line <full-hex>]` (static/pure tier, same as
  `asbuilt-features`/`asbuilt-checksum` — dispatched before `open_backend`, no `--backend`/`--port`
  needed): lists the catalog feature(s) at that line; with `--line` it ALSO runs
  `verify_full_line()` (checksum VALID/INVALID + expected byte) and, for each `full_line`-kind
  feature at that block, does an EXACT (not substring) case-insensitive hex comparison against
  every option value, reporting `matches: <meaning>` or "not a recognized community option" (with
  the known options listed). For `nibble`/`byte`-kind features it deliberately prints the bits
  mask and an honest "per-nibble/byte decoding of a partial value is not attempted" note rather
  than guessing which option a partial value encodes — the catalog only records the CHANGED
  field, not the surrounding unchanged bytes, so a specific-nibble decode from a full-line paste
  would be fabricated, not derived. Every `--line` output ends with the fixed
  `NEEDS ON-CAR CHECK` disclaimer (checksum-VALID ≠ safe-for-the-vehicle), same wording as
  `asbuilt-checksum`. Both helpers re-exported through `ford/__init__.py`.
  **TEST-FIRST, hand-derived (never read off the implementation):** `726-17-01` is
  `global_windows_close`'s block_line and no other entry's (confirmed by reading the catalog);
  `7D0-01-01` is `reverse_camera`'s (APIM, has hex letters — exercises the case-fold);
  `726-41-02` is `door_close_double_honk`'s (`nibble` kind); checksum arithmetic reused from
  iter 136's already-hand-derived fixtures (`726-17-01` + `01010101014A` → label `0x45` + data
  `5` = `0x4A`, VALID, IS the "enabled (default)" option; `726-17-01` + `000000000045` → label
  `0x45` + data `0` = `0x45`, VALID, IS the "disabled" option; `726-17-01` +
  `02010101014A`, flipped first data byte → label `0x45` + data `6` = `0x4B` ≠ stored `4A` →
  INVALID with expected byte `4B`, and the raw hex is neither known option). **Verified by
  measurement:** +24 net tests (8 in `test_fusion_2016_asbuilt.FeaturesAtBlockLineTests` incl.
  case/space-insensitivity, empty/whitespace/garbage inputs, and default-vs-custom-catalog
  isolation; 4 in `test_asbuilt_catalog_view.FormatBlockLineLookupTests` incl. the no-match
  "reference only" render and a `plausible`-confidence feature never getting upgraded to
  "confirmed"; 12 in `test_cli.CliTests` incl. two adversarial cases added after the first pass —
  a whitespace-only block-line argument, and an EXACT-not-substring probe padding a known option
  value with an extra leading byte and confirming no false "matches:" fires) → baseline 509 green
  → **`Ran 533 tests in 1.861s … OK`**. Manually ran the built CLI (not just unit-asserted) for
  all four required shapes and eyeballed every line of real stdout against the hand-derivation:
  positive lookup+checksum+match (`726-17-01 --line 01010101014A` → VALID, `matches: enabled
  (default)`), the honest nibble-kind non-guess (`726-41-02 --line 010101010149` → bits mask +
  "not attempted", checksum still independently reported as INVALID for that arbitrary line),
  unknown block (`999-99-99` → clean reference-only message, still carries the honesty header),
  and bad hex (`--line 01Z` → `error:` on stderr, exit 2, no traceback; catalog listing on
  stdout is unaffected/uncorrupted by the later hex-parse failure). README: added the "As-Built
  line decoder / reverse-lookup" bullet + `asbuilt-lookup <block-line> [--line <hex>]` in the
  command list — the pre-existing `test_readme_documents_every_cli_command` drift-guard caught
  it red before the fix, confirmed by running it standalone both before and after. Adversarially
  reviewed the diff (`git diff` on `cli.py`/`ford/__init__.py`; confirmed via direct Python check
  that all 28 catalog entries still have `verified is False` and the option-match uses `==` not
  `in` anywhere): no new UDS DID, no live vehicle I/O, no write path, no catalog data or
  `verified` flag touched — pure reference lookup + display + offline checksum math, same tier
  as iters 134–136. Commit still env-blocked this session (same `.git` write-restriction as
  iters 131–136); changes left in the working tree for a host-side commit.
- **Iter 138** (first-on-car-session PREP — the owner receives the Vgate vLinker FS in ~7 days;
  R8 "graduation event," ROADMAP). This iteration ships a **plan**, not a result: nothing here
  asserts any behavior verified on a vehicle. Two deliverables. (1) `docs/ON_CAR_VERIFICATION.md`
  — a phased runbook for the FIRST real session (2016 Fusion 2.5L S + vLinker FS on macOS): a
  safety preamble (backup-before-write + read-back verify for ANY As-Built write; WIRED
  connection required for BdyCM/BCM central-config writes, since a dropped BLE link mid-write can
  reboot the module; the three never-build boundaries stated in full); Phase 1 connection sanity
  (vLinker FS = MIC3322+FT230XQ, ST-command-compatible but **not** a true STN; macOS is BLE-only
  for wireless — no Bluetooth-Classic SPP; firmware-currency check; ISO 15765-4 protocol
  confirmation); Phase 2 module presence (the full CONFIRMED/CONFIRM-ON-VEHICLE/PLAUSIBLE table
  transcribed from `fusion_2016.py`, with the goal of promoting plausible→confirmed or recording
  ABSENT — HSWM/ACM specifically flagged as likely absent on a base 2.5L S); Phase 3 As-Built
  read+checksum on REAL data via `asbuilt-checksum --verify` (backup-first, read-only); Phase 4
  read-only spot-check of low-risk community features via `asbuilt-lookup --line` (global-windows
  726-17-01, double-honk 726-41-02), with any write explicitly gated behind backup-captured +
  read-only-spot-check-succeeded + explicit owner go-ahead, and even then routed through the
  existing `AsBuiltCoder` backup→write→read-back-verify path (no shortcut instructed); a "cannot
  verify / out of scope" section (reflashing, PATS, SecurityAccess key derivation, emissions
  manipulation); a closing section stating plainly this is a PLAN and real findings belong in
  `PROGRESS.md`/`fusion_2016.py` updates afterward, not a rewrite of this file into a fake
  "verified" narrative. (2) `fordscope preflight` — a new static/no-vehicle CLI subcommand,
  dispatched before `open_backend` (same tier as `features`/`asbuilt-features`):
  `format_preflight_checklist()` in `cli.py` iterates `fusion_2016.FUSION_2016_MODULES` directly
  (grouped by confidence tag, each module's `.note` text included) so the printed module list
  **cannot silently drift from the code** — no hardcoded copy of the module names exists anywhere
  in the new code. Also prints the backup-before-write + wired-for-BdyCM safety gates, the
  never-build boundary (emissions/PATS/SecurityAccess-crack, each named), and a
  `NEEDS ON-CAR CHECK` closing line pointing at the full runbook. **TEST-FIRST, hand-derived from
  reading `fusion_2016.py` directly (not from running the code under test):** 10 new tests in
  `test_cli.py` — runs with no vehicle connection; lists all six CONFIRMED names (PCM/ABS/RCM/
  APIM/IPC/BCM); renders the word "confirmed" attached to output; lists the plausible names named
  in the task (DDM/PDM/ACM/SCCM/FCIM/HSWM/FCDIM) plus the word "plausible"; surfaces HSWM/ACM's
  exact "likely ABSENT on base S" note text (not just the bare module name); contains
  backup+before+write; contains "wired"; contains a never-build line (asserts at least one of
  emissions/immobilizer/PATS/SecurityAccess is named AND the word "never" appears); contains
  `NEEDS ON-CAR CHECK`; and a **drift-guard** — every module name in the live
  `FUSION_2016_MODULES` list (all 18: 6 confirmed + 2 confirm-on-vehicle + 10 plausible) must
  appear in the `preflight` output, so a future module added/renamed in `fusion_2016.py` without a
  matching CLI update fails this test red. All 10 verified RED first (`argparse.ArgumentError:
  invalid choice: 'preflight'`), then GREEN after implementation. Confirmed by running the actual
  CLI (not just unit-asserted) — pasted the real `fordscope preflight` output and read it end to
  end: header states "FIRST ON-CAR SESSION PLAN (nothing verified yet)," all three confidence
  tiers present with per-module notes, both safety gates, all three never-build lines, and the
  closing `NEEDS ON-CAR CHECK` pointer to the runbook — no line asserts a result as verified.
  README: added a `preflight` feature bullet + the command to both the command list and the
  `docs/ON_CAR_VERIFICATION.md` link; the pre-existing `test_readme_documents_every_cli_command`
  drift-guard caught the gap red before the fix, confirmed by running it standalone both before
  and after. Adversarially self-reviewed both deliverables: grepped `ON_CAR_VERIFICATION.md` for
  premature-verified phrasing (none found) and confirmed the one write-instruction paragraph is
  gated by backup-captured-first language directly above it (not a bare instruction). **Verified
  by measurement:** baseline 533 green → **`Ran 543 tests in 1.861s … OK`**. Did not touch
  `fusion_2016.py`'s confidence tags, the As-Built catalog, or any live read/write path — this
  iteration is planning + a read-only-derived static checklist, nothing hardware-touching. Did
  not run `git commit`/`git add` per this iteration's instruction; changes left in the working
  tree.
- **Iter 139** (native-macOS WEB UI parity with the CLI's As-Built decoder + checksum — iter
  137's `asbuilt-lookup` was CLI-only; this closes the same gap iter 135 closed for the catalog
  browser, so the owner can paste a raw As-Built line at the car and decode it in the app, not
  just the terminal). READ-ONLY + checksum math; no live UDS wiring. New
  `FordScopeController.asbuilt_lookup(block_line, line=None)` in `webapp/controller.py` — reuses
  `features_at_block_line` + `verify_full_line` verbatim (no reimplemented option-matching logic;
  same exact-not-substring, case-insensitive comparison as the CLI's `asbuilt-lookup --line`),
  deliberately does **not** require a connection (no `_require()`, never touches
  `self.transport`), and returns `{"features": [...], "checksum": None|{"valid","expected",
  "actual"}}`. Each feature row carries the same fields as `asbuilt_features()` (name/module/
  module_confidence/bits/kind/options/verified/note) PLUS a new `matched_option` key: for a
  `full_line`-kind feature with a `line` given, the option's meaning on an EXACT hex match or
  `None`; for `nibble`/`byte`-kind features, or when no `line` is given, ALWAYS `None` — the
  catalog only records the changed field, so decoding a partial value would be a fabricated
  guess, never attempted (mirrors the CLI's honest refusal verbatim). Bad hex in `line` raises
  `ValueError` (distinct from an unknown `block_line`, which cleanly degrades to `features: []`).
  New `GET /api/asbuilt-lookup?block_line=…&line=…` on `webapp/server.py`: blank/missing
  `block_line` → clean 200 with an empty feature list (never a 500 — `features_at_block_line`
  never raises on that), bad `line` hex → the existing outer `except ValueError → 400` clause
  (same convention as `/api/read`'s bad-hex PID), and every response — including the empty/
  no-match case — carries the same top-level `caveat`/`source` fields as `/api/asbuilt-features`
  (from the same `ASBUILT_CAVEAT`/`ASBUILT_SOURCE` constants, so the two endpoints can never
  drift apart). Browser: a new "Decode As-Built line" row (`#asbuiltLookupBlockLine` +
  `#asbuiltLookupLine` text inputs + a button) + `showAsBuiltLookup()` (fetch → render into a new
  `#asbuiltLookup` div: the checksum VALID/INVALID verdict with the stored/expected hex bytes, a
  restated "VALID means only self-consistent, NOT correct-for-the-vehicle (NEEDS ON-CAR CHECK)"
  line directly under it, then a table of matched feature(s) with module/confidence/kind/bits/
  options/matched-option columns) PLUS a static always-visible caveat line in the page template
  itself (belt-and-suspenders, same pattern as iter 135's catalog section) — every render path,
  including checksum-INVALID and no-match, keeps the caveat/SOURCE/`module_confidence` visible.
  All user-derived strings (feature name, module, kind, bits, options, matched option, block_line
  is never reflected back but `caveat`/`source` are) route through the existing `escapeHtml()`
  helper before hitting `innerHTML` — no new unescaped injection point added.
  **TEST-FIRST, hand-derived (reusing the SAME fixtures already hand-derived independently in
  iters 136–137, not re-derived from the implementation):** `726-17-01` label = 07+26+17+01 =
  0x45; `01010101014A` (data 01×5=5) → checksum 0x4A, VALID, matches "enabled (default)";
  `000000000045` (data 0) → checksum 0x45, VALID, matches "disabled"; `02010101014A` (first byte
  flipped 01→02, data=6) → checksum 0x4B ≠ stored 0x4A, INVALID, `matched_option=None`;
  `726-41-02` (`door_close_double_honk`, kind=`nibble`) → `matched_option` always `None`
  regardless of `line`; a `FF`-padded known-option value (`FF01010101014A`) must NOT report
  "enabled (default)" (adversarial exact-not-substring probe, same shape as iter 137's CLI test).
  **Verified by measurement:** +8 controller tests + 7 endpoint tests + 1 structural page test →
  baseline 543 green → **`Ran 559 tests in 2.038s … OK`**. Beyond the unit suite, exercised the
  REAL live server directly (not asserted-and-trusted, executed): `GET
  /api/asbuilt-lookup?block_line=726-17-01&line=01010101014A` over an actual
  `ThreadingHTTPServer` instance returns `module_addr:1830` (=0x726), `checksum:{valid:true,
  expected:74,actual:74}` (=0x4A), `matched_option:"enabled (default)"` — byte-identical to the
  hand-derivation; bad hex → clean 400 with a plain error message, not a traceback; missing/
  unknown `block_line` → clean 200 empty list with the caveat intact; the `FF`-padded probe →
  `matched_option:null` (its own genuinely-different checksum, not a false match); the nibble-kind
  feature → `matched_option:null` unconditionally. Verified the browser-side JS by RUNNING it, not
  by inspection (same technique as iter 135): extracted the real served `<script>` block,
  `node --check`-validated it, and executed `showAsBuiltLookup()` in Node against a fake DOM/fetch
  across 5 scenarios (19 individual assertions, all PASS) — positive render (VALID + matched
  option + caveat + SOURCE + module_confidence all present), INVALID-checksum render (expected
  byte surfaced, no fabricated match), no-match/unknown-block_line render (caveat/SOURCE survive
  an empty result, checksum block correctly omitted), a rejected fetch (caught, no uncaught throw,
  plain error text), and an XSS probe (a hostile `<img onerror>` feature name AND a hostile
  `<script>` SOURCE string both come back HTML-escaped, never raw/executable). Captured the exact
  rendered `innerHTML` for the required case (`726-17-01` + `01010101014A`) via the same Node
  harness — pasted in full in this iteration's report. Un-automated sliver, honestly labelled: no
  browser-automation tooling was available in this environment, so literal rendered PIXELS were
  never eyeballed (same gap iter 135 disclosed for the catalog browser) — the served HTML/JS
  structure, the live-server JSON contract, and the Node-executed render logic are all verified by
  measurement; a screenshot check is owed to the owner, same as iter 135. Adversarially
  self-reviewed the diff (`git diff --stat` confirms only `webapp/controller.py`,
  `webapp/server.py`, `README.md`, and the two test files changed — `fusion_2016_asbuilt.py`/
  `asbuilt_catalog_view.py`/`fusion_2016.py` show zero diff and predate this session by file
  mtime, so no catalog data or `verified`/`module_confidence` tag was touched): no new UDS DID, no
  live vehicle I/O, no write path — pure reference lookup + offline checksum math reused verbatim
  from iters 134/136/137, now reachable from the Mac app. README: reworded the existing "As-Built
  line decoder / reverse-lookup" bullet to cover both surfaces (CLI + the new web section) and the
  new endpoint, mirroring how iter 135 reworded the catalog-browser bullet; the
  `test_readme_documents_every_cli_command` drift-guard is unaffected (no CLI command was added
  this iteration — `asbuilt-lookup` already existed since iter 137) and there is still no
  equivalent drift-guard for `/api/*` endpoints in this repo (checked, per iter 135's note), so
  none needed fixing. Did not run `git commit`/`git add` per this iteration's instruction; changes
  left in the working tree for a host-side commit.
- **Iter 140** (0.2 next part — `J2534Transport` class over an injected PassThru library) — the
  J2534/Openport-on-Mac backend gains its transport class (its wire codec landed iter 131).
  `J2534Transport` (`transport/j2534.py`) drives a duck-typed PassThru library: open→device,
  connect(raw CAN, flags, baud)→channel, then a **pass-all filter** (the J2534 gotcha — a raw-CAN
  channel receives NOTHING until at least one filter is armed; zero mask + zero pattern admits every
  ID). `send` marshals CanFrame→PASSTHRU_MSG via `encode_can_message` (TxFlags carries CAN_29BIT_ID for
  an extended ID); `recv` parses via `parse_can_message`, **drops transmit-loopback echoes** (RxStatus
  TX_MSG_TYPE=0x1 — else the stack would hear its own sends as replies) and skips malformed records,
  buffering a multi-message read batch across recv calls; `close` disconnects the channel then closes the
  device, releasing the device even if disconnect raises (adapter yanked). New `PassThruMsg` record +
  `TX_MSG_TYPE`/`PASS_FILTER` constants (spec values). The real `PassThru*` .dylib ctypes binding stays
  the ONLY remaining TODO and is **[NEEDS ON-CAR CHECK]** — no hardware is in this loop.
  **Test-first, hand-derived** (IDs/payloads reuse the codec's independently hand-derived fixtures; the
  RPM/VIN byte blobs match the slcan e2e's independent derivation): +19 tests — open sequence + pass-all
  filter, MS-CAN baud→connect, send std/ext marshalling, recv std/ext, loopback-skip (positive reply
  returned, loopback dropped) + lone-loopback→None + malformed-skip, not-open guards, close/disconnect +
  close-survives-disconnect-raise + context manager, and 3 full-stack e2e (SF RPM=1000 rpm, multiframe
  VIN `1FMHK8D89ABA12345`, silent-bus→clean ObdError). Verified by RUNNING: targeted module 35 green with
  every new positive path firing in the `-v` output, then the canonical suite: baseline 575 →
  **`Ran 594 tests in 2.062s … OK`**. No forbidden category touched (raw-CAN pipe, same tier as
  slcan/elm327; no SecurityAccess crack, no emissions/immobilizer, no real-vehicle I/O).
- **Iter 141** — Box 0.2 next slice: the **J2534-1 `PASSTHRU_MSG` C ABI** — `CPassThruMsg`
  (`ctypes.Structure`) + `pack_msg`/`unpack_msg` (`transport/j2534.py`), the binary face the real
  vendor `.dylib` reads/writes. Layout **hand-derived from SAE J2534-1** (confirmed vs the published
  spec + v0404 headers): six `unsigned long` fields then `unsigned char Data[4128]`; `unsigned long`
  is 32-bit in the Windows-origin J2534 ABI, so the leading fields are `c_uint32` (NOT `c_ulong`,
  8-byte under LP64 — the trap), giving `sizeof` = 6*4+4128 = **4152** with fields at 0/4/8/12/16/20
  and Data@24. `pack_msg` sets `DataSize`=len + zero-fills the tail (ValueError on >4128 overflow);
  `unpack_msg` reads exactly `DataSize` bytes (no stale-tail leak). +9 tests, **RED-first** (ImportError
  before impl): size 4152, per-field 4-byte-width straddle, offset order, Data capacity 4128, pack
  datasize/copy + flags/timestamp, unpack-only-DataSize, std/ext roundtrip, 4128-ok/4129-raises
  straddle. Verified by RUNNING: the 9 new positives all fired in `-v`; the 4152-vs-`c_ulong`-4176
  straddle confirmed real on this platform (measured `sizeof(c_ulong)`=8); canonical suite baseline
  594 → **`Ran 603 tests in 2.028s … OK`**. Still TODO on 0.2 (unchanged): LOADING + CALLING the
  vendor `.dylib` (`cdll` + `PassThru*` prototypes) — **[NEEDS ON-CAR CHECK]**, no hardware in this
  loop. No forbidden category touched (pure struct marshalling; same raw-CAN tier as slcan/elm327).
