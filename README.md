# FordScope

A macOS **OBD-II diagnostic** and **Ford As-Built coding** tool, built hardware-first but
hardware-*independent*: every layer runs against an in-process CAN **simulator**, so the
whole application is developed, tested, and demonstrable with **no car and no adapter
attached**. Real hardware plugs in behind the same `Transport` interface.

> **Status:** feature-complete against its roadmap (diagnostics + native-macOS web app +
> As-Built coding + a gated reflashing protocol). **400+ tests, all green**, and the codebase
> has been through 8 adversarial safety-audit passes (28 real bugs fixed). Nothing here has
> been validated on a real vehicle — see **Honesty boundaries** below. Build history:
> [`PROGRESS.md`](PROGRESS.md); architecture: [`docs/DESIGN.md`](docs/DESIGN.md).

## What it does

- **Native macOS app (no Windows VM):** a local web app (`python -m fordscope.webapp`) with a
  browser UI that talks to a **Vgate vLinker FS** (or any ELM327 adapter) — connect, whole-car
  scan, a live dashboard with rolling **SVG sparkline graphs** + session **min/max/avg**, DTC
  states, calibration, a shareable **health report**, and more. (FORScan is Windows-only; this
  is the native-Mac path — the reason the tool exists.)
- **Generic OBD-II (SAE J1979):** read/clear DTCs (plain-English descriptions + confirmed /
  pending / permanent **state separation**), live data (35 decoded PIDs with units), VIN,
  **calibration IDs + CVN** (Mode 09), **I/M readiness** + a **drive-cycle coach**, **freeze
  frame** (Mode 02), **Mode 06** on-board monitoring test results (named monitor category +
  raw value/limits + pass/fail from the ECU's own limits), whole-car module scan.
- **Ford enhanced (UDS / ISO 14229):** ReadDataByIdentifier across every module, whole-car
  DTC report, bidirectional actuator/routine controls, SecurityAccess seed/key handshake.
- **As-Built coding:** read/decode Ford As-Built blocks, set named features — with
  **un-bypassable backup-before-write, atomic durable backups, read-back verification, and
  one-click restore.**
- **Community As-Built catalog browser:** `asbuilt-features` (CLI) and an **As-Built catalog**
  section in the web app list the 2016 Fusion S reference catalog (28 features across 10
  modules, filterable by module/search, `GET /api/asbuilt-features`) — **COMMUNITY-SOURCED,
  UNVERIFIED, reference/display only**, not wired to any live read/write; the web view shows
  the caveat, SOURCE provenance, and each feature's `module_confidence` alongside it.
- **As-Built line checksum tool:** `asbuilt-checksum <block-line> <hex>` computes the Ford
  As-Built per-line additive checksum (spec-verified algorithm), and `--verify` checks a full
  line value (data + trailing checksum byte) and reports VALID/INVALID plus the expected byte.
  Pure/offline, no vehicle needed — always prints that it checks the LINE checksum only, not
  whether the values are correct for the vehicle (`NEEDS ON-CAR CHECK`).
- **As-Built line decoder / reverse-lookup:** `asbuilt-lookup <block-line> [--line <hex>]` (CLI)
  and a **Decode As-Built line** section in the web app (`GET /api/asbuilt-lookup?block_line=…
  &line=…`) — the inverse of `asbuilt-features`: paste a block-line label seen in FORScan and see
  which catalog feature (if any) lives there, or nothing recorded (a clean reference-only message,
  not an error). With a full line hex value it also checksum-verifies the value and, for
  `full_line`-kind features, reports an EXACT match against a known community option (never a
  substring guess); for `nibble`/`byte`-kind features it deliberately does **not** guess which
  option a partial value encodes. Pure/offline, no vehicle needed on either surface; every output
  carries the UNVERIFIED/SOURCE/`module_confidence` caveat and the same `NEEDS ON-CAR CHECK`
  framing as the checksum tool — a VALID checksum means only the trailing byte is self-consistent,
  never that the value is correct for the vehicle.
- **Live-data logging:** poll PIDs to timestamped CSV.
- **2016 Ford Fusion S profile:** the **confirmed-tier** module addresses (`--profile fusion2016`).
  The underlying data grades modules `confirmed` / `confirm-on-vehicle` / `plausible`; the profile
  uses only the corroborated `confirmed` tier. Presence of any module is still `NEEDS ON-CAR CHECK`.
- **`preflight` checklist:** first-on-car-session plan printed straight from
  `ford/fusion_2016.py` (so it can't drift from the code) — every module with its real
  confidence tag, the backup-before-write / wired-for-BCM safety gates, and the never-build
  boundary. Static/no-vehicle tier; pairs with the full runbook in
  [`docs/ON_CAR_VERIFICATION.md`](docs/ON_CAR_VERIFICATION.md). Asserts nothing verified.

## Quick start

```bash
# No dependencies for the simulator (Python 3.10+, stdlib only).
PYTHONPATH=src python3 -m fordscope scan            # whole-car scan (simulated demo vehicle)
PYTHONPATH=src python3 -m fordscope dtc             # trouble-code report
PYTHONPATH=src python3 -m fordscope read 0C         # live PID (0C = engine RPM)
PYTHONPATH=src python3 -m fordscope log --pids 0C,05,0D --samples 5   # log to CSV
PYTHONPATH=src python3 -m fordscope features        # list As-Built features (EXAMPLE/UNVERIFIED)
```

Commands: `scan`, `dtc`, `read <pid>`, `vin`, `clear-dtc`, `ports`, `features`, `preflight`,
`asbuilt-features [--module M] [--search S]`, `asbuilt-checksum <block-line> <hex> [--verify]`,
`asbuilt-lookup <block-line> [--line <hex>]`, `read-feature`, `set-feature`, `restore-feature`,
`log`. Global options: `--backend {simulator,slcan,elm327}`, `--port`,
`--profile {generic,fusion2016}`, `--backup-file`.

### The Mac app (browser UI)
```bash
PYTHONPATH=src python3 -m fordscope.webapp        # opens the UI in your browser
```
Pick **Demo (simulator)** to explore with no hardware, or a real `/dev/cu.*` serial port
(e.g. the Vgate vLinker FS) to run diagnostics on a live vehicle. Packaging it as a
double-clickable `.app` is scaffolded but UNVERIFIED — see [`docs/PACKAGING.md`](docs/PACKAGING.md).

## Real hardware (unvalidated)

Two backends target real adapters — the **wire protocols are tested against a fake serial
port; the live serial path has never touched an adapter** and is labelled accordingly:

```bash
pip install pyserial   # only needed for a live backend
python3 -m fordscope --backend elm327 --port /dev/tty.usbserial-XXXX --profile fusion2016 scan
```

`elm327` = OBDLink EX / ELM327; `slcan` = CANable-class dongle. Live runs print a
`-- LIVE VEHICLE via elm327 :: UNVALIDATED backend (NEEDS ON-CAR CHECK) --` banner.

## Honesty boundaries (by design)

- **No live-vehicle validation exists.** Everything is proven against the simulator and unit
  tests. Anything confirmable only on a car is labelled `NEEDS ON-CAR CHECK` and never called
  "working."
- **No emissions-defeat coding** (readiness spoof, EGR/DPF delete) and **no anti-theft /
  immobilizer bypass** — out of scope regardless of vehicle ownership.
- **SecurityAccess** is the protocol only; the key algorithm (`key_fn`) is user-supplied.
  FordScope ships and cracks **no** real Ford key.
- **Reflashing** (RequestDownload/TransferData) is the transfer protocol only — no calibration
  files, and deliberately **not exposed in the CLI** (bricking risk).
- **Built-in As-Built features are EXAMPLE/UNVERIFIED** demonstration maps; real coding needs
  verified definitions or FORScan.

## Run the tests

```bash
./run_tests.sh        # the full stdlib-unittest suite (no third-party deps); exit 0 == green
```
