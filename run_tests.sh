#!/usr/bin/env bash
# Canonical test command. Runs the full stdlib-unittest suite with src/ on the path.
# Exit code is the suite verdict — 0 == green. Used by every build iteration.
set -euo pipefail
cd "$(dirname "$0")"
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' "$@"
