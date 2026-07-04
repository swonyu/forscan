"""FordScope command-line interface.

Runs against a **simulated** demo vehicle (there is no hardware in this build).
Every command prints a clear SIMULATED banner, and the real-hardware backends are
honest placeholders that refuse rather than pretend — a hardware backend must be
written and validated on-car before ``--backend slcan``/``openport`` do anything.

Run it:  PYTHONPATH=src python -m fordscope scan
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Tuple

from .transport import SimulatorTransport
from .isotp import IsoTpSocket, SimulatedIsoTpEcu, multiplex
from .obd import SimulatedObdEcu, ObdClient
from .uds import SimulatedUdsEcu, UdsDtc, STATUS_CONFIRMED
from .ford import eleven_bit_module, AddressPair
from .services import (
    scan_vehicle,
    format_scan_report,
    scan_vehicle_dtcs,
    format_dtc_report,
)

BANNER = "-- SIMULATED VEHICLE (no hardware attached) --"
DEMO_VIN = "1FMHK8D89ABA12345"
_OBD_MODES = set(range(0x01, 0x0B))


def _combined(obd_ecu, uds_ecu):
    """Route OBD modes (0x01-0x0A) to the OBD ECU, everything else to UDS."""

    def handle(request: bytes):
        if request and request[0] in _OBD_MODES:
            return obd_ecu(request)
        return uds_ecu(request)

    return handle


def build_demo_vehicle() -> Tuple[SimulatorTransport, List[AddressPair]]:
    """A small simulated Ford: PCM (OBD+UDS), BCM, ABS present; APIM absent."""
    pcm = SimulatedIsoTpEcu(
        _combined(
            SimulatedObdEcu(
                pids={0x0C: bytes([0x0F, 0xA0]), 0x05: bytes([90]), 0x0D: bytes([0x40])},
                dtcs=["P0143"],
                vin=DEMO_VIN,
            ),
            SimulatedUdsEcu(
                dids={0xF190: DEMO_VIN.encode(), 0xF187: b"AB-1234-CD"},
                dtcs=[UdsDtc("P0143", 0x00, STATUS_CONFIRMED)],
            ),
        ),
        request_id=0x7E0,
        response_id=0x7E8,
    )
    bcm = SimulatedIsoTpEcu(
        SimulatedUdsEcu(dids={0xF187: b"BCM-PART-01", 0xF194: b"v3.1"}),
        request_id=0x726,
        response_id=0x72E,
    )
    abs_module = SimulatedIsoTpEcu(
        SimulatedUdsEcu(dids={0xF187: b"ABS-PART-9"}),
        request_id=0x760,
        response_id=0x768,
    )
    bus = SimulatorTransport(multiplex(pcm, bcm, abs_module))
    bus.open()
    modules = [
        eleven_bit_module(0x7E0, name="PCM"),
        eleven_bit_module(0x726, name="BCM"),
        eleven_bit_module(0x760, name="ABS"),
        eleven_bit_module(0x7D0, name="APIM"),  # absent — demonstrates detection
    ]
    return bus, modules


def _obd_client(bus: SimulatorTransport) -> ObdClient:
    return ObdClient(IsoTpSocket(bus, tx_id=0x7E0, rx_id=0x7E8))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fordscope", description="FordScope OBD-II / Ford enhanced diagnostics"
    )
    parser.add_argument(
        "--backend",
        default="simulator",
        choices=["simulator", "slcan", "openport"],
        help="hardware backend (only 'simulator' is implemented)",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("scan", help="whole-car module identification scan")
    sub.add_parser("dtc", help="whole-car diagnostic trouble-code report")
    read_p = sub.add_parser("read", help="read one Mode 01 PID (hex, e.g. 0C)")
    read_p.add_argument("pid", help="PID in hex, e.g. 0C for engine RPM")
    sub.add_parser("vin", help="read the vehicle VIN")
    sub.add_parser("clear-dtc", help="clear stored DTCs")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.backend != "simulator":
        print(
            f"error: hardware backend '{args.backend}' is not implemented yet. "
            f"Only the simulator is available; a real backend must be written and "
            f"validated on-car first (see PROGRESS.md).",
            file=sys.stderr,
        )
        return 2

    if not args.command:
        parser.print_help()
        return 1

    bus, modules = build_demo_vehicle()
    try:
        if args.command == "scan":
            print(BANNER)
            print(format_scan_report(scan_vehicle(bus, modules)))
        elif args.command == "dtc":
            print(BANNER)
            print(format_dtc_report(scan_vehicle_dtcs(bus, modules)))
        elif args.command == "read":
            pid = int(args.pid, 16)
            result = _obd_client(bus).current_data(pid)
            print(BANNER)
            print(f"{result.name}: {result.value} {result.unit}")
        elif args.command == "vin":
            print(BANNER)
            print(f"VIN: {_obd_client(bus).read_vin()}")
        elif args.command == "clear-dtc":
            _obd_client(bus).clear_dtcs()
            print(BANNER)
            print("DTCs cleared (simulated).")
    except Exception as exc:  # surface a clean message, non-zero exit
        print(f"error: {exc}", file=sys.stderr)
        return 3
    return 0
