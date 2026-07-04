"""macOS .app entry point — launch FordScope's local web UI + open the browser.

Bundled by tools/build_macos_app.sh (pyinstaller). Running this starts the stdlib
web server on 127.0.0.1:8737 and opens the default browser; the app stays alive
serving until quit. [NEEDS ON-CAR CHECK for the live-adapter path; the packaging
itself is UNVERIFIED — see docs/PACKAGING.md.]
"""
from fordscope.webapp.server import run

if __name__ == "__main__":
    run()
