# On-Car Verification Runbook — first real session (2016 Fusion 2.5L S + Vgate vLinker FS)

> **THIS DOCUMENT IS A PLAN. IT ASSERTS NOTHING AS VERIFIED.**
> Every module address, every As-Built block/line mapping, every option value in this repo has
> been built and proven against an in-memory simulator only. No car has been in the loop. This
> runbook exists to retire the `NEEDS ON-CAR CHECK` / `plausible` labels **honestly, one item at
> a time**, by recording what the vehicle *actually* says back — not by assuming the simulator's
> behavior generalizes. Until each step below has been run and its real output recorded, treat
> every "confirmed" and every catalog entry exactly as labelled elsewhere in this repo: unproven.
>
> Companion tool: run `fordscope preflight` before you start. It prints this same module list and
> safety-gate summary derived straight from `ford/fusion_2016.py`, so this document and the code
> cannot silently drift apart — if you ever see the two disagree, the code (and `preflight`'s
> live output) is the current truth, not this file.

## Safety preamble — read this before touching anything

These four rules are absolute. None of the phases below override them.

1. **Backup-before-write, always, for ANY As-Built write.** `AsBuiltCoder` in this codebase
   already refuses a write without a captured backup (`BackupRequiredError`) — do not work around
   that refusal, and do not hand-edit a block outside the tool without saving the original bytes
   first. After every write, **read the block back and compare it to what you intended** before
   trusting it. If the read-back doesn't match, restore from backup immediately and stop.
2. **Use a WIRED connection for any BdyCM/BCM (central-config) write.** A dropped BLE link
   mid-write can leave the module in a partially-written state and force a reboot mid-operation.
   The vLinker FS's wireless mode is fine for reads and for exploration; switch to USB/wired
   before writing anything to the BCM (module `726`) or any other central-configuration block.
3. **Never build or use these, regardless of what the community catalog suggests is possible:**
   - Emissions-defeat coding (readiness-monitor spoofing, EGR/DPF delete) — illegal defeat device
     under the US Clean Air Act, even on a car you own.
   - Anti-theft / immobilizer (PATS) bypass — theft-enabling, out of scope no matter the source.
   - Reflashing that cracks SecurityAccess (UDS 0x27) or ships real Ford calibration data —
     FordScope implements the *protocol* only (seed/key handshake, transfer state machine); no
     real Ford key algorithm is shipped or cracked, and no calibration file is ever loaded. The
     legitimate path for real reflashing is an FDRS subscription, not this tool.
4. **If anything looks wrong, stop and re-read, don't push through.** A module that doesn't
   answer, a checksum that doesn't verify, or a read-back mismatch is information, not an
   obstacle to route around. This session has one job: learn what's true, safely.

---

## Phase 1 — Connection sanity

**Goal:** confirm the adapter is reachable and speaking the right protocol before trusting any
data it returns.

- [ ] **Adapter identity check.** The Vgate vLinker FS uses a **MIC3322 + FT230XQ** chipset. It is
  **ST-command-compatible, but it is NOT a genuine STN chip** (unlike the OBDLink EX/MX+, which
  use real STN21xx/22xx silicon). This matters for buffer size and flow-control behavior under
  load — don't assume STN-class robustness; watch for dropped frames on long multi-frame reads
  (As-Built full-block reads, VIN, calibration IDs) and re-read if a response looks truncated.
- [ ] **Connection mode.** Decide wired-USB vs. wireless (BT/BLE) for this session per the safety
  preamble. Remember: **macOS is BLE-only for wireless OBD** — there is no Bluetooth-Classic SPP
  support on macOS/iOS, so if you're going wireless it must be the vLinker FS's BLE mode, not its
  classic-Bluetooth mode (which simply will not pair on a Mac). For any BCM/central-config write
  step later in this session, switch to wired first.
- [ ] **Firmware currency.** Confirm the adapter is running current firmware before relying on it
  (check the Vgate app / vendor tool for an update). The vLinker FS line was briefly pulled from
  FORScan's recommended-adapter list in Feb 2025 over a compatibility issue — a firmware check
  costs nothing and rules out a known class of adapter-side flakiness before you blame the car.
- [ ] **Protocol confirmation.** Confirm the adapter negotiates **ISO 15765-4** (CAN, 500 kbps,
  11-bit or 29-bit identifiers) — this is what `fordscope`'s ISO-TP layer
  (`src/fordscope/isotp/`) is built against. If the adapter reports a different protocol (e.g. it
  falls back to a legacy protocol), stop and record that — it means either the gateway isn't
  responding the way FordScope's transport layer expects, or the adapter mis-negotiated, and
  either is worth understanding before going further.
- [ ] **Basic FordScope connectivity.** Run, in order, and record the raw output of each:
  ```bash
  python3 -m fordscope ports
  python3 -m fordscope --backend elm327 --port /dev/cu.usbserial-XXXX vin
  python3 -m fordscope --backend elm327 --port /dev/cu.usbserial-XXXX --profile fusion2016 scan
  ```
  A `vin` command that returns your actual 17-character VIN is the first genuine end-to-end
  confirmation that the whole stack (serial → ISO-TP → OBD/UDS) is talking to your car and not
  just to an idle bus. (See `FIRST_RUN.md` for the general first-connection walkthrough this
  phase assumes you've already followed once.)

**Cannot verify here / defer:** actual BLE GATT behavior on macOS is not something this repo's
test suite can exercise (no CoreBluetooth simulator) — this phase is where that first gets
exercised for real, and its outcome should be recorded, not assumed from the wired path.

---

## Phase 2 — Module presence: promote or mark absent

**Goal:** retire the `plausible` / `confirm-on-vehicle` tags in `ford/fusion_2016.py` honestly —
by recording which modules actually answer on THIS car, not by leaving the tags stale.

Run `fordscope preflight` first — it prints the exact list below, generated from
`FUSION_2016_MODULES`, so this table and the code cannot drift apart silently.

### CONFIRMED tier (adversarially-verified address; still confirm PRESENCE on this car)
| Module | Address | What it is |
|---|---|---|
| PCM | 0x7E0 | Powertrain (2.5L I4) |
| ABS | 0x760 | Anti-lock brakes |
| RCM | 0x737 | Restraints (airbags) |
| APIM | 0x7D0 | SYNC / infotainment |
| IPC | 0x720 | Instrument cluster |
| BCM | 0x726 | Body Control / Smart Junction Box |

These addresses are well-established; a scan should show all six answering. If any of these six
is silent, that itself is a real, worth-recording finding — don't assume a typo in the address
map without first re-checking wiring/protocol from Phase 1.

### CONFIRM-ON-VEHICLE tier (address known; presence unverified)
| Module | Address | Note |
|---|---|---|
| TCM | 0x7E1 | 6F35 transmission is PCM-controlled; may have no separate live node |
| HVAC | 0x733 | base S manual A/C may be BCM-handled, not a separate module |

### PLAUSIBLE tier (address plausible; presence unverified)
| Module | Address | Note |
|---|---|---|
| PAM | 0x736 | presence unverified |
| OCS | 0x765 | presence unverified |
| SCCM | 0x724 | address confirmed, presence unverified |
| PSCM | 0x730 | address confirmed, presence unverified |
| DDM | 0x740 | Driver door module; As-Built reference addr (2GFusions) |
| PDM | 0x741 | Passenger door module; As-Built reference addr (2GFusions) |
| ACM | 0x727 | Audio module; **premium/Sony audio likely absent on a base S** |
| FCIM | 0x7A7 | Front Controls Interface Module; As-Built reference addr |
| HSWM | 0x714 | Heated-steering-wheel module; **likely ABSENT on a base S** (no HSW hardware) |
| FCDIM | 0x7A5 | Front Control Display Interface (basic Sync); As-Built ref |

- [ ] Run the whole-car scan (`scan --profile fusion2016` covers only the confirmed tier by
  design — for this phase, scan the **full** address list, confirmed + confirm-on-vehicle +
  plausible, so every entry above gets a real answer/silence recorded).
- [ ] For each module that **answers** (even a negative response counts as present — silence is
  the absence signal, per `services/module_scan.py`'s present/absent convention): record it as a
  candidate to promote to `confirmed` in `ford/fusion_2016.py`, with the real response noted.
- [ ] For each module that is **silent**: record it as `ABSENT on this vehicle` — this is
  expected and useful information, not a failure. HSWM and ACM are specifically flagged above as
  likely absent on a base 2.5L S (no heated steering wheel hardware, no premium/Sony audio) — a
  silent answer there would corroborate the trim-based expectation, not contradict it.
- [ ] Do **not** edit `ford/fusion_2016.py`'s confidence tags during the live session itself —
  record the raw findings here (or in a session log), then make the code edit afterward as its
  own test-first, verified change, per the repo's normal iteration discipline.

---

## Phase 3 — As-Built read + checksum, on real data

**Goal:** confirm the additive-checksum convention (`ford/fusion_2016_asbuilt.additive_checksum`,
hand-derived from the documented worked example `760-01-04 3733 → 0xD6`) holds against bytes that
actually came off the vehicle, not just against hand-derived fixtures.

- [ ] **Back up first.** Before reading anything with intent to later modify it, capture and save
  the block's current bytes (e.g. via `--backup-file` on any `set-feature`/`code`-style command,
  or by hand-recording the raw read). This phase is READ-ONLY by design, but the backup habit
  starts here, before Phase 4 gets anywhere near a write.
- [ ] **Pick two or three low-risk blocks to read.** Good first candidates (all on the CONFIRMED
  BCM/IPC modules, all in the community catalog as reference points):
  - `726-17-01` (BCM) — global windows remote close
  - `726-41-02` (BCM) — door-close double horn honk
  - `720-01-01` (IPC) — AWD gauge / chime routing
- [ ] **Read the raw block bytes off the vehicle** (via whatever UDS ReadDataByIdentifier path
  the session uses — the block's DID, not just its label) and record the full hex value,
  including the trailing checksum byte.
- [ ] **Run the checksum tool against the real bytes:**
  ```bash
  python3 -m fordscope asbuilt-checksum --verify 726-17-01 <the real full-line hex you read>
  ```
  Record whether it reports VALID or INVALID, and the expected-vs-actual checksum bytes either
  way. A VALID result confirms the additive-checksum convention holds for a real value from this
  vehicle — it does **not** confirm the data bytes' *meaning* (see Phase 4). An INVALID result on
  a value read straight off the car (not hand-edited) would be a real, notable finding about the
  checksum convention itself and should be recorded carefully, not dismissed.
- [ ] Repeat for each block picked above.

**What this phase does NOT do:** it does not write anything. It does not attempt to interpret
what the option value *means* beyond what the checksum math confirms. That's Phase 4.

---

## Phase 4 — Spot-check community features, READ-ONLY first

**Goal:** confirm the community catalog's block/line/option mapping matches what the vehicle
actually reports, for a couple of low-risk, easily-observable features — before any write is
considered.

- [ ] **Look up the catalog entry** for a feature you can visually/audibly confirm the current
  state of without any tools (so you have an independent way to check "does the byte match
  reality"):
  ```bash
  python3 -m fordscope asbuilt-lookup 726-17-01   # global windows remote close
  python3 -m fordscope asbuilt-lookup 726-41-02   # door-close double honk
  ```
  This prints the catalog's recorded options (e.g. `726-17-01` full-line `01010101014A` =
  "enabled (default)", `000000000045` = "disabled") with the standard
  `COMMUNITY-SOURCED · UNVERIFIED · NEEDS ON-CAR CHECK` header — nothing here is claimed true
  until you check it.
- [ ] **Read the real value off the vehicle** (Phase 3's read step) and pass it to the same
  command with `--line` to get an exact-match verdict against the catalog's known options:
  ```bash
  python3 -m fordscope asbuilt-lookup 726-17-01 --line <the real full-line hex you read>
  ```
  - If it reports `matches: enabled (default)` (or whichever option), and you can independently
    confirm the car currently behaves that way (e.g. the fob does/doesn't close windows on a
    long-press), that's a genuine corroboration — record it as such, still `NEEDS ON-CAR CHECK`
    for anyone else's vehicle/model-year, but corroborated for THIS one.
  - If it reports "not a recognized community option," record the raw value and the mismatch —
    this either means the catalog is wrong for this model year/trim, or there's a different
    factory configuration than the sheet's default assumption. Either is useful information;
    neither should be forced to fit by assuming a transcription error without checking.
  - For `nibble`/`byte`-kind entries (e.g. `726-41-02`), the tool deliberately does **not**
    attempt to decode a partial value from a full-line paste (it would have to guess the
    surrounding unchanged bytes) — it prints the bits mask and the known option values instead.
    Cross-check those against the real behavior manually.
- [ ] **Only after this read-only spot-check succeeds, a backup is captured, and you (the owner)
  give an explicit go-ahead, consider a write.** Any write still goes through the mandatory
  `AsBuiltCoder` backup-before-write + read-back-verify path — there is no CLI shortcut around
  it, and this runbook does not instruct one. If a write is attempted:
  - Confirm the backup was actually captured (don't just trust that the flag was passed).
  - Write the smallest, most reversible change first (e.g. flip one binary on/off feature).
  - Read the block back immediately and confirm it matches the intended value AND that the
    checksum re-verifies.
  - Confirm the real-world behavior changed as expected.
  - Keep the backup file until the change has been lived with for a while, in case a restore is
    ever needed.

---

## Cannot verify / out of scope for this session

These are explicitly not part of this runbook, regardless of what the community catalog or forum
posts suggest is technically possible:

- **Reflashing / module reprogramming.** FordScope implements the RequestDownload/TransferData
  protocol state machine only (`uds/client.py`); it is deliberately not wired to the CLI, ships no
  calibration data, and this session should not attempt any transfer. Real reflashing goes through
  Ford FDRS, not this tool.
- **PATS / immobilizer configuration.** Not attempted, not investigated as a "how would one," full
  stop.
- **SecurityAccess key derivation.** The seed/key handshake (`UdsClient.request_seed`/`send_key`)
  is protocol-only; no real Ford key algorithm is shipped or attempted here. If a module refuses
  a write with a SecurityAccess-related negative response, that's the end of that line of
  investigation for this session, not a puzzle to solve.
- **Emissions-related monitor/readiness manipulation.** Reading readiness/Mode 06 data is in
  scope (it's already built); writing anything that would spoof or defeat an emissions monitor is
  not, ever.

---

## What this document is (and isn't)

This is the **plan** for the owner's first on-car session with the 2016 Fusion 2.5L S and the
Vgate vLinker FS. It was written before any car was in the loop. **Nothing in it should be read
as a claim that any module has answered, any checksum has verified against real data, or any
catalog entry has been corroborated** — those are exactly the outcomes this runbook exists to
produce and record, honestly, one phase at a time. When a real session happens, its actual
findings belong in `PROGRESS.md` (as a normal dated iteration) and in updates to
`ford/fusion_2016.py`'s confidence tags — not in a rewrite of this file's plan into a fake
after-the-fact "verified" narrative. If the plan itself turns out to be wrong in some way (a step
doesn't make sense once a real adapter is in hand), that's worth fixing here too, but only after
being observed, not anticipated.
