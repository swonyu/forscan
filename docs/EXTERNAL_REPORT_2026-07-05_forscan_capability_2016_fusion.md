<!--
  PROVENANCE / VERIFICATION STATUS — READ FIRST
  - Source: owner-provided research synthesis, imported into the repo 2026-07-05.
    NOT produced by FordScope's own deep-research loop and NOT run through the
    3-vote adversarial verification that gates the docs/RESEARCH_* files.
  - Trust level: broad synthesis. Treat EVERY specific hex value, PID, module
    address, As-Built block, buffer size, and price below as a CANDIDATE ->
    NEEDS ON-CAR CHECK, not authoritative.
  - Known correction: this report states DLC pins 3/11 carry HS-CAN2. The
    verified finding V1 in docs/RESEARCH_2026-07-04_ford_diagnostics.md shows the
    owner's non-hybrid 2.5L "S" retains TRUE MS-CAN on pins 3/11 (the HS2 swap hit
    the *hybrid* Fusion/C-Max first). Where the two disagree, the 2026-07-04
    verified subset wins.
  - Do NOT build the drive-cycle coach (R3) or Mode 06 decode (R5) on this report;
    those angles remain OPEN (see RESEARCH_2026-07-04).
-->

# Building a Native macOS Ford Diagnostic App to Match and Exceed FORScan (2016 Ford Fusion)

## TL;DR
- **It is entirely feasible to build a native macOS app that matches and exceeds FORScan for a 2016 Fusion, and the single most important architectural fact is that you must use a BLE or USB-serial adapter with a genuine STN chipset (OBDLink EX USB / MX+ BLE) or the ST-command-compatible Vgate vLinker FS, because macOS cannot use the Bluetooth-Classic SPP profile that classic ELM327 dongles rely on, and because the 2016 Fusion hides its body/infotainment modules behind a multi-bus gateway that plain ELM327 clones cannot reach.**
- **Lead with the Python + local-web-UI "FordScope" stack for fastest capability delivery (pyserial/bleak give the cleanest hardware access and cross-platform reach), while building the SwiftUI app in parallel for the premium Mac/iOS UX; the two share no code but should share a documented protocol/PID/As-Built data model.** Reading (DTCs, PIDs, Mode 06, readiness, module ID, As-Built read/backup) is low-risk and should ship first; As-Built writing needs a full safety gate; module reflashing should be explicitly out of scope (boundary-only) because Ford gates it with signed firmware and unpublished seed/key algorithms.
- **The biggest "beyond FORScan" wins are a beautiful real-time dashboard, high-rate logging with charting/export, guided readiness drive-cycle coaching, and an automated As-Built backup/diff/restore workflow with plain-language feature names and an honest "verified vs. needs-on-car-check" labeling system** — none of these require anything FORScan can't technically do; they are UX/data problems where FORScan is weakest.

## Key Findings

1. **FORScan's capabilities decompose cleanly into protocol layers.** Everything rides on ISO 15765-4 (CAN) with ISO-TP (ISO 15765-2) transport. Generic diagnostics use SAE J1979 modes 01–0A; enhanced diagnostics use UDS (ISO 14229) services (0x22 ReadDataByIdentifier, 0x2E WriteDataByIdentifier, 0x27 SecurityAccess, 0x2F InputOutputControl, 0x31 RoutineControl, 0x19 ReadDTCInformation, 0x10 DiagnosticSessionControl, 0x3E TesterPresent, and 0x34/0x36/0x37 for reflash download). As-Built configuration is a Ford-specific data format layered on UDS read/write.
2. **The 2016 Fusion is NOT a simple HS-CAN/MS-CAN car.** It uses a Gateway Module (GWM, address 716) bridging HS-CAN1, HS-CAN2, HS-CAN3 and MS-CAN, and the DLC pins are remapped so pins 3/11 carry HS-CAN2 (not classic MS-CAN). This is precisely why a capable auto-switching adapter is mandatory and why cheap ELM327 clones see only a fraction of the car.
3. **The adapter market splits sharply on chipset.** Genuine STN chips (STN2120/STN2230 in OBDLink EX, STN2255 in OBDLink MX+) support Ford MS-CAN and offer larger buffers, better ISO-TP flow control and the extended "ST" command set. The Vgate vLinker FS is *ST-command-compatible* but uses a different processor (MIC3322 + FT230XQ USB-serial), not a true STN. Clone ELM327s support neither MS-CAN nor the ST set.
4. **macOS wireless is BLE-only.** Apple/macOS dropped Bluetooth Classic SPP support, so classic-Bluetooth ELM327/OBDLink MX (non-plus) adapters cannot connect wirelessly; you must use a BLE adapter (OBDLink MX+, vLinker FS in its BLE mode) via CoreBluetooth, or a wired USB adapter via a serial library.
5. **Reflashing is the hard wall.** Full module reprogramming needs UDS 0x27 SecurityAccess with seed/key algorithms Ford does not publish and signed/validated firmware; even FORScan's own firmware-update feature is a suspended beta with a high brick rate, and Ford officially routes this through FDRS/FJDS with a paid subscription (now $120 for a 2-day license as of the September 2025 migration). This should be a documented boundary, not a build target.

## Details

### 1. Complete FORScan capability map for a 2016 Ford Fusion

| Capability | Underlying protocol/standard | R/W | Risk |
|---|---|---|---|
| Generic DTC read (stored/pending/permanent) | J1979 Mode 03/07/0A over ISO 15765-4 | Read | None |
| Clear DTCs / reset monitors | J1979 Mode 04 | Write (volatile) | Low (clears freeze frame/readiness) |
| Enhanced/module DTC read & clear (BCM, ABS, RCM, APIM, PATS, etc.) | UDS 0x19 ReadDTCInformation / 0x14 ClearDiagnosticInformation | R/W | Low |
| Live data / generic PIDs | J1979 Mode 01 | Read | None |
| Ford-enhanced / manufacturer PIDs (per-module) | UDS 0x22 ReadDataByIdentifier over ISO-TP | Read | None |
| Mode 06 on-board monitor tests (TID/MID results) | J1979 Mode 06 | Read | None |
| Readiness monitors | J1979 Mode 01 PID 01 | Read | None |
| Freeze frame | J1979 Mode 02 | Read | None |
| VIN / calibration IDs / CVN | J1979 Mode 09 (PIDs 02/04/06); UDS 0x22 for module part numbers | Read | None |
| Module inventory / identification (assy/part numbers, software levels) | UDS 0x22 (part-number DIDs) + gateway routing | Read | None |
| KOEO / KOER on-demand self-tests | Ford enhanced "black-box" routines (RoutineControl 0x31-class) | Command | Low–Med (engine actuation in KOER) |
| Actuator/output tests | UDS 0x2F InputOutputControlByIdentifier | Write (transient) | Med (commands physical components) |
| Service functions/routines (ABS bleed, battery-monitor reset, TPMS, injector/characterization, DPF regen where applicable, parameter reset) | UDS 0x31 RoutineControl (+ 0x10 session, 0x3E keep-alive) | Command | Med (real actuation; can block if faults present) |
| PATS key programming | Ford security routines (0x27 SecurityAccess seed/key + timed access) | Write | High (immobilizer/anti-theft) |
| As-Built module configuration READ | UDS 0x22 (As-Built blocks) | Read | None |
| As-Built configuration WRITE (feature enable/coding) | UDS 0x2E WriteDataByIdentifier (+0x10 extended session, checksum) | Write | Med–High (mis-coding → DTCs/module misbehavior) |
| Central configuration (shared params, stored in BdyCM blocks on this platform) | UDS 0x2E; may need Secondary Boot Loader; can reboot car mid-write | Write | High |
| PCM VID / TCM TRID block edits | Checksum-protected; may require full reflash on older cars (not 2016) | Write | High |
| Module firmware reflashing (MFU) | UDS 0x10→0x27→0x31 erase→0x34/0x36/0x37 download→reset | Write | Very High (bricking) |

The KOEO/KOER tests are "black-box" routines whose exact internal logic is hardcoded in the ECU and hidden from the tool — the tool can only trigger them and read the result. FORScan's Service Procedures menu on this platform includes items like Battery Monitor System Reset (needed after battery replacement to avoid overcharging the new battery and a U3003-class fault), ABS Service Bleed (electronically cycles the ABS valve body), and PATS key programming (gated by a coded challenge/response or a mandatory ~10-minute timed wait).

### 2. 2016 Fusion network topology and adapter requirements

The 2016 Fusion (2nd-gen, Ford CD4/CD391 platform) uses a **Gateway Module (GWM, address 716)** that bridges four+ buses. At the OBD-II DLC, **pins 6/14 carry HS-CAN1** and **pins 3/11 carry HS-CAN2** (the platform remapped what used to be the MS-CAN pins), with true MS-CAN and HS-CAN3 reachable through the gateway's diagnostic routing. Module-to-bus map (from the Ford Fusion 2013–2020 workshop "Communications Network — Diagnosis and Testing"):

- **HS-CAN1:** PCM (7E0), BCM/BdyCM (726), Parking Aid (integrated with BCM, 736), Battery Energy Control Module B (723), Headlamp Control Module, DC/DC converter. APIM/SYNC (7D0) is commonly reachable here per community/adapter notes.
- **HS-CAN2:** ABS (760), Vehicle Dynamics Module, RCM/airbags (737), Occupant Classification System, Steering Column Control Module (724), Gear Shift Module, Transmission Range Control Module, Image Processing Module A / camera (706).
- **HS-CAN3:** Instrument Panel Cluster / IPC (720), Audio Front Control Module / ACM (727).
- **MS-CAN:** Front Controls Interface Module (FCIM, 7A7), GPS Module (GPSM, 701).

The practical consequence: many Ford enhanced diagnostics and As-Built operations target body/infotainment modules (IPC, ACM, FCIM, APIM configuration) that do not live on the primary pin-6/14 bus. An adapter must therefore support switchable/dual-CAN or (better) automatic gateway-aware bus switching to reach them. Plain ELM327 clones bound to pins 6/14 see only HS-CAN1 modules. Note this differs from older Fords where a manual HS/MS toggle switch (rewiring pins 6/14 vs 3/11) sufficed — the gateway architecture is why FORScan added HS2/HS3 support (v2.2.4, May 2015) and why a "recommended" adapter matters more on this platform.

### 3. Adapter research

**(a) Vgate vLinker FS (specific).** The vLinker FS is explicitly recommended by the FORScan team and is compatible with both the ELM327 AT command set and the STN "ST" command set (vendor literature cites "up to 15 ELM protocols, 23 STN protocols"). **Important correction on chipset:** the vLinker FS is *not* an STN device — it uses a **MIC3322 processor** ("not a STN processor, like on OBDLink EX, but compatible with the ST command") with an **FT230XQ chip as USB-to-serial converter** and ~1.3 ms average command response. It performs **automatic electronic HS-CAN/MS-CAN switching** (no manual toggle), supports **FEPS 18V programming voltage output**, and per Vgate's own spec reaches "Up to 3Mbps Transmission Rate, OBD Request Byte up to 4128 Bytes, Serial Buffer is 8192 Bytes" (USB version) — meaningful for long-frame As-Built and programming work. Three variants exist: **vLinker FS USB** (fast, most reliable for programming; presents as an FTDI USB-serial/VCP device), **vLinker FS BT** (Bluetooth), and BLE-capable firmware modes ("Use VgateFwUpdater to switch between MFi and BLE+BT modes"). For a Mac native app the **USB variant is the most robust** (appears as a `/dev/cu.*` serial device); the BT/BLE variant is usable over CoreBluetooth if you target its BLE GATT service. Caveats: an owner review confirms the FS was "recently removed from the list of recommended devices for the Forscan diagnostic program" at points, and a FORScan-forum thread (t=20648) documents a case where only HS modules appeared and auto-switch appeared to fail — verify firmware is current (v2.2.78+).

**(b) macOS-compatible adapter survey.**

| Adapter | Chipset | MS-CAN | macOS interface | Notes |
|---|---|---|---|---|
| OBDLink EX (USB) | STN2230 (genuine STN) | Yes, auto-switch | FTDI USB CDC/VCP → `/dev/cu.*` serial | Best for programming/reflash-class reliability; wired lowest latency (can tune latency ~16 ms→2 ms) |
| OBDLink MX+ (BLE) | STN2255 (genuine STN) | Yes, auto-switch, +SW-CAN | BLE via CoreBluetooth (iOS-supported) | Only OBDLink wireless model that works with iOS/BLE; FORScan added MX+ support Christmas 2019 (v2.3.19) |
| OBDLink MX (classic BT) | STN1170-variant | Yes | **Not usable wirelessly on macOS** (Bluetooth Classic SPP) | Works on Android/Windows only |
| Vgate vLinker FS (USB/BT/BLE) | MIC3322 + FT230XQ (ST-command compatible, not STN) | Yes, auto-switch | USB serial or BLE | FORScan-recommended; cheapest full-function option |
| Modded ELM327 + HS/MS toggle | Clone ELM327 | Manual switch only | USB serial or (classic BT, not macOS) | Cheap but buffer-limited; unreliable for programming; cannot read UBP buses |

**STN command-set advantages over base ELM327 that matter here:** genuine STN chips have large RAM — "STN2120 has over five times as much RAM as its nearest competitor, virtually eliminating BUFFER OVERFLOW errors" (and STN2120 has "twice as much flash and four times as much RAM" vs STN1170) — plus better/faster ISO-TP flow control, monitor modes, larger message buffers, and the extended ST command set that exposes SW-CAN/MS-CAN and lets the device interpret proprietary Ford network data. These are exactly the properties needed for enhanced PID streaming, As-Built long frames, and any programming. The ST-command compatibility of the vLinker FS gives it the same access without the STN silicon. Note that the chip only *transports* the proprietary codes; per OBD Solutions, "the proprietary GM & Ford codes must be obtained independently. A popular method is to join the Equipment and Tool Institute where the codes can be accessed/purchased. Alternately, the traffic can be analyzed and reverse engineered."

### 4. macOS connectivity feasibility for each stack

**Native SwiftUI/Swift app.**
- **USB serial:** Use ORSSerialPort (mature Obj-C/Swift library, MIT license, SPM/CocoaPods/Carthage installable) which wraps IOKit + BSD TTY. Open `/dev/cu.usbserial-*` at the adapter baud (115200 for OBDLink EX FTDI; up to 3 Mbps for vLinker FS USB). IOUSBHost/IOKit are the lower-level alternatives.
- **BLE:** Use CoreBluetooth. BLE OBD adapters expose a serial-over-GATT service — commonly service UUID FFF0 with a notify characteristic (FFF1) and a write characteristic (FFF2) on many Chinese/OBDLink-class dongles. There is an existing open-source SwiftOBD2 project (SwiftUI + CoreBluetooth) to learn from.
- **Bluetooth Classic SPP is impossible on macOS/iOS** — Apple's guidance and developer forums confirm iOS/macOS support only standard BLE profiles for third-party serial devices; this is the decisive constraint that forces BLE for wireless.
- **Sandboxing/entitlements:** A Mac App Store build needs the App Sandbox with `com.apple.security.device.usb` (USB) and the Bluetooth entitlement plus the `NSBluetoothAlwaysUsageDescription` Info.plist string (BLE). Note that sandbox serial-port access to `/dev/cu.*` is historically fraught (documented "deny file-read-data /dev/cu.usbserial" sandbox violations); the pragmatic path is **Developer-ID distribution outside the App Store with a hardened-runtime, notarized `.app`**, which avoids the tightest sandbox serial restriction while still giving Gatekeeper trust.
- **Libraries:** ORSSerialPort (serial), CoreBluetooth (BLE), SwiftOBD2 (reference).

**Python + local-web-UI ("FordScope").**
- **USB:** pyserial. **BLE:** bleak (cross-platform incl. macOS CoreBluetooth backend). python-OBD handles ELM327 command formatting and ISO 15765-4 framing; ELM327-emulator is invaluable for offline testing (it can emulate multi-ECU UDS with ISO-TP flow control on macOS). Existing projects (e.g., nissan-leaf-obd-ble) show the bleak+python-OBD pattern of wrapping BLE GATT as a pyserial-like interface — a proven template for a modified python-OBD layer doing ISO-TP framing and flow control over BLE.
- **Local web UI:** run a local server (Flask/FastAPI + a JS frontend), which gives instant cross-platform reach and easy charting.
- **Packaging:** PyInstaller for a standalone app; still requires signing/notarization for smooth macOS distribution.

**Comparison and recommendation on which to lead with.**

| Dimension | FordScope (Python) | SwiftUI (native) |
|---|---|---|
| Development speed | **Fast** (python-OBD, bleak, emulator) | Slower (build ISO-TP/UDS layer yourself) |
| Hardware ergonomics | Clean (pyserial/bleak) | Good (ORSSerialPort/CoreBluetooth) |
| UX quality | Web UI — good, not native | **Best** (native Mac feel, energy-efficient) |
| Cross-platform reach | **Windows/Linux too** | Mac + **iOS/iPadOS companion** |
| Distribution | PyInstaller (heavier, sign/notarize) | **One notarized `.app`** |

Lead with **FordScope (Python)** for capability velocity: bleak/pyserial + python-OBD get you to reading DTCs/PIDs/Mode 06/readiness fastest, and the local-web-UI is the quickest route to charting and export. Build the **SwiftUI app in parallel** for the premium native Mac experience and the iOS/iPadOS companion (a shared Swift core across Mac and iOS is a major strategic advantage FORScan cannot match). A **hybrid makes sense**: keep the protocol/PID/As-Built definitions in a shared, language-neutral data format (JSON/YAML schema) consumed by both stacks, so decoding logic and the "verified vs. unverified" As-Built database stay in sync.

### 5. As-Built configuration on the 2016 Fusion — what is known-unlockable

**Format.** As-Built is represented as lines of the form `<module address>-<block#>-<line#> <D1 D2> <D3 D4> <D5 Cs>` — e.g., `726-16-01 ...`. The last byte (Cs) is a per-line checksum computed by an additive algorithm from the other bytes (sum the preceding hex byte pairs; e.g. `760-01-04 3733 D6` = 07+60+01+04+37+33 = D6). FORScan validates the checksum and **auto-recalculates it** if you accept the warning after editing a byte — so mistyped edits are caught and the checksum need not be hand-computed. Ford publishes each VIN's factory As-Built at motorcraftservice.com under Free Resources → "Module Built Data (As-Built)," which FORScan can also pull ("Load factory AB").

**Safety pattern (this is the core of a good tool).** Read + back up original As-Built per module before any write (FORScan has no whole-car one-click backup — you save each module's `.abt` via Read → Save All); write one line at a time and verify (turn ignition off then to Run without starting, and confirm the change); keep the original for restore; recognize that exact per-module byte meanings are vehicle-specific and community-sourced. Writing wrong values can trigger DTCs, cause module misbehavior, or (for central-configuration/BdyCM writes that load a Secondary Boot Loader) reboot the whole car mid-write — a stable wired adapter is strongly recommended for those.

**Community-verified 2016 Fusion candidates (ALL need on-car verification).** From 2gfusions tid=4573, FORScan forums and sibling-platform sheets:
- **Double-honk (door close, engine running) disable:** BdyCM `726-41-02` `0001 0001 0072` (enabled/default) → `0000 0001 0071` (disabled).
- **Lock-confirmation honk (fob press) disable:** BdyCM `726-38-02 xxxX...` 1→0 (a *different* setting than door-close double honk).
- **Global window open/close via fob:** BdyCM `726-21-02` (Fusion-specific line; note the F-150 uses a different `726-17-01` chain — do not assume cross-model block numbers). US cars ship with global close disabled.
- **DRL enable:** BdyCM multi-line procedure including `726-50-01` mode byte (01 disabled/US default, 02 low beams, 04 fog, 08 turn, 10 dedicated DRL, 20 high beams). 2015+ may expose this in the GUI config rather than raw As-Built.
- **Auto-lock/unlock behavior:** sibling-platform BdyCM lines `726-48-03` (auto-lock), `726-48-04` (auto-unlock), `726-49-01` (one- vs two-stage unlock) — verify block presence on the Fusion.
- **IPC/gauge options (address 720, HS-CAN3):** climate on right-hand IPC screen `720-05-01`, 30-min fuel history `720-02-01`, temps above gauges `720-07-01` — all cluster-type dependent.
- **APIM/SYNC (7D0) options:** best decoded via CyanLabs' SYNC3 APIM As-Built database.

The exact block numbers frequently differ between Ford models even when a feature name matches; many "Fusion" codes circulating online are actually F-150/Explorer/Taurus blocks. A tool must therefore label each entry with its provenance and a confidence level, and prompt on-car verification.

### 6. The reflash / reprogramming boundary — map it, don't build it

Module reflashing at the protocol level is: enter programming session (0x10 0x02) → SecurityAccess (0x27 seed/key) → erase (RoutineControl 0x31) → RequestDownload (0x34) → TransferData (0x36, multi-frame via ISO-TP flow control) → RequestTransferExit (0x37) → ECU reset (0x11), with a CRC/checksum validation after 0x37 that the module refuses to activate if it fails. It is the highest-risk operation because an interruption after the flash is erased typically bricks the module.

**The hard technical walls** are (1) Ford's **signed/validated firmware images** — the module will not accept unsigned or altered firmware, and (2) the **0x27 seed/key algorithms Ford does not publish**. Because of these, FORScan's own Module Firmware Update (MFU, v2.4 beta) is explicitly a **suspended, high-brick-rate beta**; FORScan cannot implement full Programmable Module Installation (PMI) precisely due to "restricted access to firmware information and update procedures." Ford officially routes reflashing through **FDRS/FJDS with a paid, time-based subscription**, a J2534 pass-through device, and — for security functions — NASTF Vehicle Security Professional credentials. Per Ford's motorcraftservice.com FDRS Help page, "Ford J2534 Diagnostic Software (FJDS) – Provides module reprogramming software that covers 1996 to select 2018 Ford, Lincoln and Mercury module reprogramming functions" — which includes the 2016 Fusion. As of the September 2025 migration to a unified "Ford Diagnostic Subscription," pricing rose sharply: **2-day = $120 (up from $50), 30-day = $300, yearly = $1,200.**

**Verdict for this project:** treat reflashing as **boundary-only** — document and understand it, surface module firmware/calibration levels (read-only), and explicitly *defer* actual reflashing to Ford's FDRS/FJDS. Do **not** attempt to bypass SecurityAccess, defeat firmware signing, or circumvent emissions/immobilizer (PATS) protections; doing so raises legal, safety, and emissions-compliance issues (reprogramming second-hand modules or remapping is treated as a breach of vehicle-security and emissions regulations).

### 7. "Beyond FORScan" feature roadmap — prioritized

FORScan's weak spots are its dated Windows-centric UI, thin data visualization, weak logging/analytics, no trip intelligence, and no native Mac experience. Prioritized candidate features (value vs. difficulty; MS-CAN/write flags noted):

**Tier 1 — High value, low/medium difficulty, read-only (ship first):**
- Beautiful real-time live dashboard with configurable gauges (generic + Ford-enhanced PIDs). *HS-CAN mostly; some enhanced PIDs need MS-CAN/gateway.*
- High-rate PID logging with charting and CSV/JSON export. *Read-only.*
- DTC lookup with plain-language explanations + repair guidance (generic + Ford enhanced). *Read-only; MS-CAN for body modules.*
- Whole-car health report (scan all modules, summarize DTCs + readiness). *Needs MS-CAN/gateway for full coverage.*
- Freeze-frame and Mode 06 visualization (named TID/MID where known, raw otherwise). *Read-only.*

**Tier 2 — High value, medium difficulty:**
- Guided readiness drive-cycle coaching to pass emissions/inspection (interpret Mode 01 PID 01 + Mode 06 progress live). *Read-only; big differentiator.*
- Trip/journey recording with GPS correlation (Mac location or phone GPS; correlate PIDs to route). *Read-only.*
- Automated As-Built backup/diff/restore with a safety workflow and human-readable feature names. *Read for backup; write for restore.*
- Scheduled/automated scans and cloud/local history. *Read-only.*

**Tier 3 — High value, higher difficulty / write access:**
- Friendly guided UI for enabling factory features with plain-language descriptions + warnings and an **"honest verified vs. unverified / needs-on-car-check" labeling system** for community-sourced As-Built codes. *Write (0x2E); MS-CAN for body/infotainment.*
- iOS/iPadOS companion sharing the Swift core. *Transport = BLE.*
- Actuator tests / service routines (ABS bleed, battery reset, TPMS). *Write (0x2F/0x31); MS-CAN for body modules.*

**Explicitly out of scope:** module reflashing (boundary-only), PATS key programming beyond documentation (security/legal risk).

### 8. Phased implementation roadmap

| Phase | Scope | Protocol work | Key risks |
|---|---|---|---|
| **0. Transport foundation** | Serial (ORSSerialPort/pyserial) + BLE (CoreBluetooth/bleak) transport; ELM327/STN AT+ST command layer; ISO-TP (ISO 15765-2) segmentation/flow control; gateway/bus-switch handling | AT init, ATSH headers, ISO-TP multi-frame reassembly, ST commands for bus selection | Adapter variability; BLE GATT UUID discovery; buffer sizing (favor STN/large-buffer) |
| **1. Generic OBD read** | J1979 modes 01–0A: live PIDs, DTC read/clear, freeze frame, readiness, VIN/CVN | Mode 01/02/03/04/06/07/09/0A parsing | Low; foundation for everything |
| **2. Enhanced PIDs + DTCs** | UDS 0x22 per-module PIDs; 0x19 module DTCs; requires gateway/MS-CAN routing | 0x22 DID map, 0x19 subfunctions, session 0x10 + 0x3E keep-alive | Need MS-CAN/HS2/HS3; Ford PID definitions are proprietary/community-sourced |
| **3. Mode 06 + readiness** | On-board monitor test visualization; drive-cycle coaching | Mode 06 TID/MID decode | TID/MID naming is OEM-specific |
| **4. Module identification** | Assy/part numbers, software/calibration levels, full module inventory | 0x22 part-number DIDs + gateway enumeration | Gateway routing correctness |
| **5. As-Built read + backup** | Read all As-Built blocks; per-module `.abt`-style backup; diff/compare; checksum calc | 0x22 As-Built block reads; additive checksum | None (read-only) but must be complete before any write |
| **6. As-Built write (full safety gate)** | Guided feature enable with backup-first, verify-after, restore; verified/unverified labels | 0x2E WriteDataByIdentifier + 0x10 extended session + checksum; central-config SBL handling | Med–High: mis-coding → DTCs; central-config writes reboot car; use wired adapter |
| **7. Beyond-FORScan UX** | Dashboards, logging/charting/export, trip+GPS, health report, scheduled scans, iOS companion, cloud/local history | Mostly built on phases 1–5 | Product/data work, not protocol risk |
| **— Reflash** | **Out of scope / boundary-only** — surface firmware levels read-only; defer actual reprogramming to FDRS/FJDS | 0x27/0x34/0x36/0x37 documented but not implemented | Very high (brick); signed firmware + unpublished seed/key are hard walls |

## Recommendations
1. **Buy the right hardware first.** Standardize development on two adapters: an **OBDLink EX (USB, STN2230)** for wired reliability (essential for any write/programming work) and an **OBDLink MX+ (BLE, STN2255)** for the wireless/iOS path. Add a **Vgate vLinker FS** as the budget FORScan-recommended reference (remembering it is MIC3322/ST-compatible, not STN). Avoid classic-Bluetooth ELM327/OBDLink MX for macOS entirely.
2. **Lead with FordScope (Python), build SwiftUI in parallel.** Ship reading capabilities (Phases 1–5) in Python first for velocity; mirror them in SwiftUI for the premium Mac/iOS experience. Keep a **shared JSON/YAML data model** for PIDs, DTC text, and the As-Built database so both stacks decode identically.
3. **Gate all writes behind a safety workflow.** No As-Built write without an automatic read-and-backup of the target module, a human-readable diff, an explicit confirm, and a verify-after step, plus a prominent verified/unverified provenance label. Require a wired adapter for central-configuration/BdyCM writes.
4. **Distribute as a Developer-ID-signed, hardened-runtime, notarized `.app`** (outside the Mac App Store) to sidestep the tightest sandbox serial-port restrictions while retaining Gatekeeper trust. If you later want App Store distribution, plan for the USB/Bluetooth sandbox entitlements and the serial-access limitations.
5. **Draw the reflash boundary in ink.** Implement read-only firmware/calibration display, document the 0x27/0x34–0x37 sequence for understanding, and route real reprogramming to Ford FDRS/FJDS. Do not build seed/key bypass or signing-defeat.

**Benchmarks that would change the plan:** If SwiftUI development velocity matches Python (e.g., you find a robust Swift ISO-TP/UDS library), lead with Swift instead. If a genuine, reliable UDS-capable adapter with a documented, open BLE GATT profile emerges at low cost, standardize on it for both stacks. If Apple relaxes sandbox serial access, revisit Mac App Store distribution. If community As-Built verification for the specific 2016 Fusion trim reaches high confidence for a feature, promote it from "unverified" to "verified" in the UI.

## Caveats
- **Per-vehicle As-Built byte meanings are community-sourced and require on-car verification.** Block numbers differ across Ford models even for identically named features; many "Fusion" codes online are actually F-150/Explorer/Taurus. Treat all specific hex values in this report as candidates, not authoritative.
- **Adapter behavior varies.** Even FORScan-recommended adapters (including the vLinker FS) have documented cases of failed auto-switching or being temporarily de-listed; firmware currency matters. Verify MS-CAN/gateway access on the actual car. The vLinker FS chipset is MIC3322 (ST-command compatible), not a true STN — a distinction worth confirming against your own protocol testing.
- **Reflashing risk is real and largely irreducible** given signed firmware and unpublished seed/key algorithms; this report deliberately treats it as a boundary, not a capability to build.
- **Legal/emissions/security compliance:** enabling some features or altering emissions-related or immobilizer (PATS) configuration may have legal, warranty, inspection, or safety implications; the tool should warn users and avoid facilitating emissions-defeat or anti-theft circumvention.
- **Some vendor specifications** (buffer sizes, transfer rates, subscription prices) come from marketing or forum reports and should be validated directly; Ford subscription pricing in particular changed materially in September 2025 and may change again.
- **The exact module-to-bus assignments** are drawn from a reproduced Ford workshop manual and community sources; confirm on the specific VIN/trim, since option content (e.g., navigation, driver-assist modules) alters which modules are present and where they sit.
