# Packaging FordScope as a macOS `.app` (R7) — UNVERIFIED

> **Honesty note:** this packaging was **authored but NOT verified** — building it needs
> `pip install pyinstaller` in a Python environment that wasn't available when this was
> written. The steps below are the intended approach and a best-effort script; expect to
> iterate. Nothing here has run on a machine. (The diagnostic tool itself is fully tested
> — full stdlib-unittest suite green — this is only about wrapping it in a double-clickable app.)

## What the `.app` is
FordScope's UI is a **local web app** (Python stdlib `http.server` + one embedded page).
The `.app` just bundles Python + the `fordscope` package + a launcher that starts the
server on `127.0.0.1:8737` and opens your browser. No cloud, no external services.

## Build it
```bash
cd /path/to/fordscope
bash tools/build_macos_app.sh      # installs pyinstaller + pyserial, then builds
# -> dist/FordScope.app  (double-click to run; right-click → Open on first launch)
```
The launcher entry point is [`tools/fordscope_launcher.py`](../tools/fordscope_launcher.py)
(`from fordscope.webapp.server import run; run()`).

## Likely things to iterate on
- **pyserial hidden import:** if the live `elm327`/`slcan` adapter path fails in the bundle,
  add `--hidden-import serial` (or `--collect-all serial`) to the pyinstaller command.
- **`--windowed` vs console:** `--windowed` gives a GUI-style app with no terminal. If you
  want to see server logs, drop `--windowed` and run the produced binary from a terminal.
- **Gatekeeper:** an unsigned `.app` needs right-click → Open the first time (or
  `xattr -dr com.apple.quarantine dist/FordScope.app`). Code-signing is a separate step.
- **Port in use:** the launcher uses the default port 8737; edit `run(port=…)` in the
  launcher if it clashes.

## The honest alternative (works today, no packaging)
Until the `.app` is verified, the tool runs directly with no build step:
```bash
cd /path/to/fordscope && PYTHONPATH=src python3 -m fordscope.webapp
```
This opens the same UI in your browser. The `.app` is a convenience wrapper, not a
different program.

## Status
- **R7 (this doc + script):** authored, UNVERIFIED — needs your Mac to build/confirm.
- **R8 (first on-car run with the Vgate vLinker FS):** the real graduation event — still
  owner-gated. Everything the simulator can prove is proven; the car is the last unknown.
