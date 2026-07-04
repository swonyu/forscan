"""FordScope local web app — a native-feeling macOS UI (browser + stdlib server)
that talks to a real adapter (e.g. Vgate vLinker FS) over USB, so no Windows VM
is needed for diagnostics.

Layers: a testable ``controller`` (engine wiring, no HTTP) and a thin stdlib
``server`` (http.server) that exposes it as a JSON API + a single embedded page.
"""

from .controller import FordScopeController, list_ports, DEMO_PORT

__all__ = ["FordScopeController", "list_ports", "DEMO_PORT"]
