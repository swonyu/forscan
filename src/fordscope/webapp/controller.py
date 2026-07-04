"""Web-app controller — the testable bridge between the UI and the engine.

No HTTP or GUI here: it lists serial ports, connects a backend, and runs the
diagnostic commands, returning plain data. Reuses the CLI's ``open_backend`` so
the simulator / elm327 (vLinker FS) / slcan paths and the honesty banner are
identical to the terminal tool.
"""
from __future__ import annotations

import glob
from typing import List, Optional

from ..cli import open_backend
from ..isotp import IsoTpSocket
from ..obd import ObdClient
from ..services import (
    scan_vehicle,
    format_scan_report,
    scan_vehicle_dtcs,
    format_dtc_report,
)

DEMO_PORT = "Demo (simulator)"
_NOISE = ("Bluetooth-Incoming", "debug-console")


def list_ports() -> List[str]:
    """Selectable ports: the demo simulator plus real /dev/cu.* serial devices."""
    real = [
        p for p in sorted(glob.glob("/dev/cu.*"))
        if not any(n in p for n in _NOISE)
    ]
    return [DEMO_PORT] + real


class NotConnectedError(RuntimeError):
    pass


class FordScopeController:
    def __init__(self, *, port_factory=None) -> None:
        self.port_factory = port_factory  # inject a fake serial for tests
        self.transport = None
        self.modules = None
        self.banner: Optional[str] = None

    @property
    def connected(self) -> bool:
        return self.transport is not None

    def connect(self, port: str, *, profile: Optional[str] = None) -> str:
        """Connect the demo simulator or a real serial adapter. Returns the banner."""
        self.disconnect()
        if port == DEMO_PORT:
            self.transport, self.modules, self.banner = open_backend(
                "simulator", None, profile=profile
            )
        else:
            self.transport, self.modules, self.banner = open_backend(
                "elm327", port, port_factory=self.port_factory, profile=profile
            )
        return self.banner

    def disconnect(self) -> None:
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
        self.transport = None
        self.modules = None
        self.banner = None

    def _require(self) -> None:
        if not self.connected:
            raise NotConnectedError("connect to an adapter first")

    def _obd(self) -> ObdClient:
        return ObdClient(IsoTpSocket(self.transport, tx_id=0x7E0, rx_id=0x7E8))

    def scan(self) -> str:
        self._require()
        return format_scan_report(scan_vehicle(self.transport, self.modules))

    def dtc(self) -> str:
        self._require()
        return format_dtc_report(scan_vehicle_dtcs(self.transport, self.modules))

    def read_pid(self, pid: int) -> dict:
        self._require()
        r = self._obd().current_data(pid)
        return {"pid": pid, "name": r.name, "value": r.value, "unit": r.unit}

    def vin(self) -> str:
        self._require()
        return self._obd().read_vin()
