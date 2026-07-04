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
- **Live-data logging:** poll PIDs to timestamped CSV.
- **2016 Ford Fusion S profile:** the **confirmed-tier** module addresses (`--profile fusion2016`).
  The underlying data grades modules `confirmed` / `confirm-on-vehicle` / `plausible`; the profile
  uses only the corroborated `confirmed` tier. Presence of any module is still `NEEDS ON-CAR CHECK`.

## Quick start

```bash
# No dependencies for the simulator (Python 3.10+, stdlib only).
PYTHONPATH=src python3 -m fordscope scan            # whole-car scan (simulated demo vehicle)
PYTHONPATH=src python3 -m fordscope dtc             # trouble-code report
PYTHONPATH=src python3 -m fordscope read 0C         # live PID (0C = engine RPM)
PYTHONPATH=src python3 -m fordscope log --pids 0C,05,0D --samples 5   # log to CSV
PYTHONPATH=src python3 -m fordscope features        # list As-Built features (EXAMPLE/UNVERIFIED)
```

Commands: `scan`, `dtc`, `read <pid>`, `vin`, `clear-dtc`, `ports`, `features`, `read-feature`,
`set-feature`, `restore-feature`, `log`. Global options: `--backend {simulator,slcan,elm327}`,
`--port`, `--profile {generic,fusion2016}`, `--backup-file`.

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
`LIVE — UNVALIDATED (NEEDS ON-CAR CHECK)` banner.

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
