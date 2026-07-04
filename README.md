# FordScope

A macOS OBD-II **diagnostic** and Ford **As-Built coding** tool, built hardware-first
but hardware-*independent*: every layer runs against an in-process CAN **simulator**,
so the whole application is developed and tested with no car and no adapter attached.
Real hardware (a CANable-class slcan dongle, or a Tactrix Openport) plugs in behind the
same interface later.

> **Status:** early, under active autonomous TDD construction. See
> [`PROGRESS.md`](PROGRESS.md) for exactly where the build is and how to resume it, and
> [`docs/DESIGN.md`](docs/DESIGN.md) for the architecture and the honesty boundaries.

## What it will do
- Generic OBD-II (SAE J1979): read/clear codes, live data, freeze-frame, readiness, VIN.
- Ford enhanced diagnostics (UDS / ISO 14229) across **every** module, not just the engine.
- Bidirectional actuator tests and service routines.
- Ford **As-Built** feature coding — with mandatory *backup-before-write*.

## What it will not do
Emissions-defeat coding and anti-theft/immobilizer bypass are out of scope, by design —
illegal and/or unsafe regardless of vehicle ownership.

## Run the tests
```bash
./run_tests.sh
```
No third-party dependencies required (standard-library `unittest`).
