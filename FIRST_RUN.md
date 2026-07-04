# FordScope — first run on your car

Everything in FordScope is proven against a built-in simulator. This guide is the bridge to
your **real** vehicle. Nothing here has been validated on a car yet — expect the live path to
need a little fiddling the first time, and treat every reading as **to be confirmed** until
you've sanity-checked it against a known value.

## What you need
- A macOS Mac (you have one).
- A USB OBD adapter — a **Vgate vLinker FS** or **OBDLink EX** (ELM327/STN class).
- Python 3.10+ and one dependency: `pip install pyserial`.

## 1. Plug in and find the port
Plug the adapter into the OBD-II port (under the dash, driver's side) with the ignition **on**.
Then:
```bash
python3 -m fordscope ports
```
It lists `/dev/cu.*` devices. Your adapter is usually `/dev/cu.usbserial-XXXX` or
`/dev/cu.wchusbserialXXXX`. If nothing relevant appears, a CH340-based adapter may need its
macOS driver installed (search "CH340 macOS driver").

## 2. First connection — the terminal way
```bash
python3 -m fordscope --backend elm327 --port /dev/cu.usbserial-XXXX --profile fusion2016 scan
```
- The output starts with a `LIVE — UNVALIDATED (NEEDS ON-CAR CHECK)` banner. That is expected
  and honest: the serial path has never touched an adapter before your run.
- A working scan lists your modules (PCM, ABS, BCM, IPC…). That's your first real confirmation.

Then try:
```bash
python3 -m fordscope --backend elm327 --port /dev/cu.usbserial-XXXX dtc     # read codes
python3 -m fordscope --backend elm327 --port /dev/cu.usbserial-XXXX vin     # read VIN
```
If `vin` returns your actual VIN, the whole stack is talking to your car correctly.

## 3. The Mac app (browser UI)
```bash
python3 -m fordscope.webapp
```
Opens a page in your browser. Pick your adapter's port from the dropdown → Connect → then use
Scan / Codes / Live dashboard / Readiness / Health report. (Pick **Demo (simulator)** to try
the UI with no hardware.)

## Troubleshooting
- **"needs pyserial"** → `pip install pyserial`.
- **Port not listed** → wrong/again-unplugged adapter, or missing CH340 driver.
- **Permission / busy** → close anything else using the port; unplug/replug the adapter.
- **Connects but no data / NO DATA** → ignition not fully on, adapter not seated, or the
  ELM327 raw-frame timing needs adjustment (this is the finicky live-hardware area flagged
  throughout — the protocol is tested, the on-adapter behavior is what you're validating).
- **As-Built coding** → not in FordScope for real cars yet (maps unverified). Use FORScan for
  actual coding until verified definitions exist.
