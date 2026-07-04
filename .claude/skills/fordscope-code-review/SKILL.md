---
name: fordscope-code-review
description: Use when reviewing FordScope code for correctness before committing an iteration, or when the build loop reaches a review pass — targets the protocol-parser, exception-hierarchy, HTTP-status, and resource-leak bug classes that have historically shipped here.
---

# FordScope Code Review

## Overview
Adversarial correctness review for a hardware-abstracted OBD-II tool whose inputs are
untrusted bytes off a noisy CAN bus / flaky serial adapter. **Core principle: reproduce
every suspected bug with a FAILING test before fixing it.** A finding you can't turn red
is a finding you can't trust — and a green test written after the fix proves nothing about
the fix. No exceptions, even for "obvious" bugs.

## When to use
- Before committing any iteration that changed protocol/parser/HTTP/error-path code.
- On a dedicated review-pass iteration (the loop should schedule one regularly).
- After adding a new transport backend, UDS/OBD service, or web endpoint.

## The bug classes that actually shipped here
Every row below is a *real* bug found + fixed in this repo. Check each class every pass —
these are where FordScope breaks, not hypotheticals.

| Class | What to verify | Historical bug |
|---|---|---|
| **Parser bound/length checks** | A malformed serial/CAN line returns the *documented* value (None / typed error), never an uncaught crash that kills the recv loop. Check DLC>8, len>8, truncated slices. | slcan/elm327 crashed on DLC>8; `parse_isotp` accepted a First Frame with total 1–7 (must be a Single Frame) → bogus data + spurious Flow Control. |
| **Exception-hierarchy completeness** | A caller catches the *full* set a lower layer can raise. `IsoTpSocket` raises `IsoTpError` **and** the UDS layer raises `UdsError` — catching only one aborts a loop that should continue. | Module scan aborted the whole vehicle scan on one dropped multi-frame instead of marking the module present. |
| **HTTP exception ordering** | Specific handlers precede the broad one: `NotConnectedError`→409 and `ValueError`→400 are caught **before** `except Exception`→500. | Bad hex PID returned 500 instead of 400. |
| **Resource cleanup on error paths** | A serial port/fd opened then failing (bad handshake, timeout) is closed before the exception propagates. | `open_backend` leaked the serial fd on a failed ELM327 handshake. |
| **Spec-math constants** | Independently re-derive from SAE/ISO — PID scale/offset (RPM /4, temp −40, MAF /100, trim 100/128), DTC first-nibble→letter (0=P,1=C,2=B,3=U), checksum sum-to-zero mod 256, 11-bit +8 vs 29-bit `0x18DA{TA}{SA}`, CF sequence-number 0–15 wrap. | (Verified clean across passes — keep re-checking on any decoder change.) |

## How to run a pass
1. Dispatch one adversarial auditor per subsystem in parallel (codecs · UDS/OBD clients ·
   decoders/As-Built math · web/services). Give each the bug-class table and demand a
   **concrete `input → wrong output → correct output` repro** per finding — no style nits,
   and "no bugs found" is a valid, valuable result.
2. **Verify each finding yourself** before acting — auditors produce false positives. Read
   the code + write the failing test. If it won't go red, the finding is wrong; discard it.
3. Fix test-first, re-run `./run_tests.sh` to green, log the bug + fix in `PROGRESS.md`.

## Iron rules
- **Never fix a contract test by editing its assertion.** Fixtures are hand-derived from the
  SAE/ISO spec, not from the code under test. If a spec-fixture test fails, the *code* is
  wrong until proven otherwise.
- **Simulation green ≠ works on a car.** Nothing here validates hardware behavior; keep the
  `NEEDS ON-CAR CHECK` label on anything that only a real vehicle can confirm.
