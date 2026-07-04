#!/usr/bin/env bash
# Build a double-clickable macOS FordScope.app that launches the local web UI.
#
# ⚠️ UNVERIFIED: this was NOT run/verified by the tool author — it needs
# `pip install pyinstaller` in your Python environment, which wasn't available at
# build time. Treat it as a starting point; expect to iterate. See docs/PACKAGING.md.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pip install --upgrade pyinstaller pyserial

# --windowed: no console window (a GUI-style .app). The launcher runs the stdlib
# server and opens the browser; the .app process stays alive serving.
# --paths src: so pyinstaller finds the `fordscope` package under src/.
python3 -m PyInstaller --noconfirm --windowed --name FordScope \
  --paths src \
  --collect-submodules fordscope \
  tools/fordscope_launcher.py

echo
echo "If the build succeeded: dist/FordScope.app  (double-click to run)."
echo "First run may need Gatekeeper approval: right-click → Open."
