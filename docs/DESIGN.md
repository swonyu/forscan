# FordScope — Design & Spec

_Autonomous design of record. Owner delegated all decisions; this is the plan being built._

## 1. Purpose
A macOS tool to fully diagnose and legitimately customize a **Ford the owner owns**:
generic OBD-II, Ford enhanced (UDS) diagnostics across all modules, bidirectional
tests, and As-Built feature coding.

## 2. Honesty boundaries (non-negotiable)
- **No live-vehicle validation in the build environment.** There is no CAN hardware in
  the dev loop. Every layer is proven against an in-process simulator and unit tests.
  Anything that can only be confirmed on the car is labelled **NEEDS ON-CAR CHECK** and
  is never claimed to "work" — only "passes simulation."
- **No emissions-defeat** coding (readiness spoofing, EGR/DPF delete). Illegal defeat
  device under the U.S. Clean Air Act regardless of ownership.
- **No anti-theft / immobilizer (PATS) bypass.**
- **Reflashing (Tier 5)** is built as a state machine but gated: Ford SecurityAccess keys
  and official calibrations come from an FDRS subscription. FordScope does not crack
  security or ship calibration files.

## 3. Architecture — strict layers, each independently testable
```
app / CLI / dashboards
   └── services: whole-car scan, DTC report, live data, As-Built coding
        └── obd (SAE J1979)      uds (ISO 14229)
             └── isotp (ISO 15765-2 segmentation)
                  └── transport (CanFrame + Transport ABC)
                       ├── SimulatorTransport   (no hardware — always available)
                       ├── SlcanTransport       (CANable / slcan dongle)   [later]
                       └── OpenportTransport     (Tactrix, macOS-native)     [later]
```
Rule: nothing above `transport` knows which backend is attached. The simulator is a
first-class backend, not a test mock — it makes the product runnable with zero hardware.

## 4. Phased plan
- **Phase 1 — Diagnostics foundation (Tiers 0–3).** transport → ISO-TP → UDS → OBD-II →
  PID/DTC decode + database → Ford enhanced module addressing → bidirectional tests →
  whole-car scan → CLI + live dashboard + logging.
- **Phase 2 — As-Built coding (Tier 4).** backup-before-write engine → As-Built
  read/decode → guarded write with read-back verify + rollback.
- **Phase 3 — Reflashing (Tier 5).** flashing state machine, gated behind FDRS keys.

## 5. Safety invariants
- **Backup-before-write:** no configuration write is permitted unless the module's
  original block was read and persisted first, with one-click restore.
- **Read-back verify:** every write is confirmed by re-reading the value.
- **Simulator parity:** each protocol layer ships with a simulated ECU that exercises it,
  so regressions surface without a car.

## 6. Testing
Standard-library `unittest`, TDD. Hand-derived fixtures from the SAE/ISO byte formats,
never derived from the code under test. `./run_tests.sh` is the canonical green check.

## 7. Non-goals (YAGNI)
CAN-FD, non-Ford OEM coverage, cloud sync, and a GUI framework are out of scope until the
diagnostic core and As-Built coding are solid on the simulator.
