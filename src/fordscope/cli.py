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

from .transport import SimulatorTransport, SlcanTransport, Elm327Transport
from .isotp import IsoTpSocket, SimulatedIsoTpEcu, multiplex
from .obd import SimulatedObdEcu, ObdClient
from .uds import SimulatedUdsEcu, UdsDtc, STATUS_CONFIRMED, UdsClient
from .ford import (
    eleven_bit_module,
    AddressPair,
    TYPICAL_FORD_MODULES,
    fusion_2016,
    AsBuiltCoder,
    InMemoryBackupStore,
    FileBackupStore,
    FeatureCoder,
    EXAMPLE_FEATURES,
)
from .services import (
    scan_vehicle,
    format_scan_report,
    scan_vehicle_dtcs,
    format_dtc_report,
    DataLogger,
    rows_to_csv,
)

BANNER = "-- SIMULATED VEHICLE (no hardware attached) --"
LIVE_BANNER = "-- LIVE VEHICLE via {backend} :: UNVALIDATED backend (NEEDS ON-CAR CHECK) --"
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
                pids={
                    0x0C: bytes([0x0F, 0xA0]), 0x05: bytes([90]), 0x0D: bytes([0x40]),
                    # monitor status: MIL on, 1 DTC, O2-sensor monitor not complete
                    0x01: bytes([0x81, 0x07, 0x21, 0x20]),
                },
                dtcs=["P0143"],
                pending=["P0113"],      # detected this cycle, not yet confirmed
                permanent=["P0420"],    # confirmed; won't clear until the ECU re-verifies
                vin=DEMO_VIN,
                # obviously-fake demo calibration (Mode 09 0x04/0x06) so the
                # calibration readout is demonstrable end-to-end on the simulator
                calibration_ids=["DEMO-PCM-CAL-01"],
                cvns=[bytes([0x1A, 0x2B, 0x3C, 0x4D])],
                ecu_names=["DEMO-ECM-EngineCtl"],
                # Mode 06: catalyst + O2 pass; EGR deliberately out-of-limits (fails)
                # so the pass/fail path is demonstrable end-to-end. (tid,uasid,val,min,max)
                monitor_tests={
                    0x21: [(0x80, 0x01, 100, 50, 200)],
                    0x01: [(0x8E, 0x10, 5, 0, 10)],
                    0x31: [(0x83, 0x01, 300, 100, 250)],
                },
                # frozen snapshot captured when P0143 set: idling, warm, stopped
                freeze_frame={0x0C: bytes([0x0F, 0xA0]), 0x05: bytes([85]), 0x0D: bytes([0x00])},
                freeze_dtc="P0143",
            ),
            SimulatedUdsEcu(
                dids={0xF190: DEMO_VIN.encode(), 0xF187: b"AB-1234-CD"},
                dtcs=[UdsDtc("P0143", 0x00, STATUS_CONFIRMED)],
            ),
        ),
        request_id=0x7E0,
        response_id=0x7E8,
    )
    # BCM/IPC carry the EXAMPLE As-Built feature blocks (all "off"), so the
    # As-Built CLI commands are demonstrable end-to-end on the simulator.
    bcm = SimulatedIsoTpEcu(
        SimulatedUdsEcu(dids={
            0xF187: b"BCM-PART-01", 0xF194: b"v3.1",
            0xDE01: bytes(4),  # fog_drl block  (byte2 high nibble = off)
            0xDE02: bytes(2),  # double_honk block (byte0 low nibble = off)
        }),
        request_id=0x726,
        response_id=0x72E,
    )
    ipc = SimulatedIsoTpEcu(
        SimulatedUdsEcu(dids={0xF187: b"IPC-PART-7", 0xDE10: bytes(3)}),  # gauge_sweep (off)
        request_id=0x720,
        response_id=0x728,
    )
    abs_module = SimulatedIsoTpEcu(
        SimulatedUdsEcu(dids={0xF187: b"ABS-PART-9"}),
        request_id=0x760,
        response_id=0x768,
    )
    bus = SimulatorTransport(multiplex(pcm, bcm, ipc, abs_module))
    bus.open()
    modules = [
        eleven_bit_module(0x7E0, name="PCM"),
        eleven_bit_module(0x726, name="BCM"),
        eleven_bit_module(0x760, name="ABS"),
        eleven_bit_module(0x7D0, name="APIM"),  # absent — demonstrates detection
    ]
    return bus, modules


_PORT_NOISE = ("Bluetooth-Incoming", "debug-console")


def list_serial_ports() -> List[str]:
    """Candidate serial adapter devices on macOS (/dev/cu.* minus obvious non-adapters)."""
    import glob
    return [
        p for p in sorted(glob.glob("/dev/cu.*"))
        if not any(n in p for n in _PORT_NOISE)
    ]


def default_modules() -> List[AddressPair]:
    """Typical Ford module list for a live scan (addresses are non-authoritative)."""
    return [eleven_bit_module(addr, name=name) for name, addr in TYPICAL_FORD_MODULES.items()]


def modules_for_profile(profile):
    """Module list for a named vehicle profile, or None to use the backend default."""
    if profile == "fusion2016":
        return fusion_2016.confirmed_modules()
    if profile == "generic":
        return default_modules()
    return None


def _open_serial(port_name: str):
    """Open a real serial port via pyserial (only reached on a live backend)."""
    try:
        import serial  # pyserial
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "a live backend needs pyserial: pip install pyserial"
        ) from exc
    return serial.Serial(port_name, baudrate=115200, timeout=1.0)


def open_backend(backend: str, port, *, port_factory=None, profile=None):
    """Return (transport, modules, banner) for the chosen backend.

    port_factory lets tests inject a fake serial port; production uses pyserial.
    profile overrides the module list (e.g. 'fusion2016' = confirmed-tier 2016 Fusion map).
    """
    profile_modules = modules_for_profile(profile)
    if backend == "simulator":
        bus, demo = build_demo_vehicle()
        return bus, (profile_modules if profile_modules is not None else demo), BANNER
    if port is None:
        raise ValueError(f"--port is required for the '{backend}' backend")
    opener = port_factory or _open_serial
    serial_port = opener(port)
    try:
        if backend == "slcan":
            transport = SlcanTransport(serial_port)
        elif backend == "elm327":
            transport = Elm327Transport(serial_port)
        else:  # pragma: no cover - argparse restricts choices
            raise ValueError(f"unknown backend {backend!r}")
        transport.open()
    except Exception:
        # Handshake failed after the port opened — close the fd so a failed retry
        # doesn't leak handles (eventually "device busy").
        try:
            serial_port.close()
        except Exception:
            pass
        raise
    modules = profile_modules if profile_modules is not None else default_modules()
    return transport, modules, LIVE_BANNER.format(backend=backend)


def _obd_client(bus) -> ObdClient:
    return ObdClient(IsoTpSocket(bus, tx_id=0x7E0, rx_id=0x7E8))


# Module addresses used by the EXAMPLE As-Built features.
_FEATURE_MODULE_ADDR = {"BCM": 0x726, "IPC": 0x720, "APIM": 0x7D0, "PCM": 0x7E0}


def _feature_coder_for(bus, feature, *, store=None) -> FeatureCoder:
    """A FeatureCoder bound to the feature's module over the given bus."""
    addr = _FEATURE_MODULE_ADDR[feature.module]
    pair = eleven_bit_module(addr, name=feature.module)
    uds = UdsClient(IsoTpSocket(bus, tx_id=pair.request_id, rx_id=pair.response_id))
    # Scope backups by MODULE, not a flat "cli": two features on different modules
    # that reuse the same DID number must not collide to one backup slot (which would
    # make restore write the wrong module's bytes into a module).
    coder = AsBuiltCoder(uds, store or InMemoryBackupStore(), scope=f"cli:{feature.module}")
    return FeatureCoder(coder, {feature.key: feature})


def _store_for(backup_file):
    """Durable FileBackupStore when --backup-file is given, else in-session memory."""
    return FileBackupStore(backup_file) if backup_file else InMemoryBackupStore()


def print_features() -> None:
    print("As-Built features (EXAMPLE / UNVERIFIED — demonstration mappings):")
    for key, f in EXAMPLE_FEATURES.items():
        print(f"  {key:12s} {f.name} [{f.module}]  options={sorted(f.options)}")
    print("These are demo mappings. Real coding needs VERIFIED definitions or FORScan.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fordscope", description="FordScope OBD-II / Ford enhanced diagnostics"
    )
    parser.add_argument(
        "--backend",
        default="simulator",
        choices=["simulator", "slcan", "elm327"],
        help="transport backend (default: simulator; slcan/elm327 need --port and are "
        "UNVALIDATED on real hardware)",
    )
    parser.add_argument(
        "--port",
        default=None,
        help="serial device for a live backend, e.g. /dev/tty.usbserial-XXXX",
    )
    parser.add_argument(
        "--profile",
        default=None,
        choices=["generic", "fusion2016"],
        help="module profile for scan/dtc (fusion2016 = confirmed-tier 2016 Fusion S addresses)",
    )
    parser.add_argument(
        "--backup-file",
        default=None,
        help="persist As-Built backups to this JSON file (enables restore-feature later)",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("scan", help="whole-car module identification scan")
    sub.add_parser("dtc", help="whole-car diagnostic trouble-code report")
    read_p = sub.add_parser("read", help="read one Mode 01 PID (hex, e.g. 0C)")
    read_p.add_argument("pid", help="PID in hex, e.g. 0C for engine RPM")
    sub.add_parser("vin", help="read the vehicle VIN")
    sub.add_parser("clear-dtc", help="clear stored DTCs")
    sub.add_parser("ports", help="list connected serial adapters (for --port)")
    sub.add_parser("features", help="list built-in As-Built features (EXAMPLE/UNVERIFIED)")
    rf = sub.add_parser("read-feature", help="read a feature's current setting")
    rf.add_argument("key", help="feature key, e.g. fog_drl")
    sf = sub.add_parser("set-feature", help="set a feature (simulator only; needs --confirm)")
    sf.add_argument("key", help="feature key, e.g. fog_drl")
    sf.add_argument("option", help="option name, e.g. on / off")
    sf.add_argument("--confirm", action="store_true", help="actually write (default is a dry run)")
    rs = sub.add_parser("restore-feature", help="undo a set-feature from its saved backup (simulator only)")
    rs.add_argument("key", help="feature key, e.g. fog_drl")
    lg = sub.add_parser("log", help="log live PIDs to CSV")
    lg.add_argument("--pids", default="0C,05,0D", help="comma-separated hex PIDs (default RPM,coolant,speed)")
    lg.add_argument("--samples", type=int, default=5, help="number of samples to capture")
    lg.add_argument("--interval", type=float, default=0.0, help="seconds between samples")
    lg.add_argument("--out", default=None, help="write CSV to this file (else print)")
    return parser


def main(argv: Optional[List[str]] = None, *, port_factory=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    # 'ports' and 'features' are static listings — no vehicle needed.
    if args.command == "ports":
        ports = list_serial_ports()
        if ports:
            print("Serial adapters (use one with --port):")
            for p in ports:
                print("  " + p)
        else:
            print("No serial adapters found. Plug in your OBD adapter (e.g. Vgate vLinker FS) "
                  "and re-run. A CH340-based adapter may need its macOS driver installed.")
        return 0
    if args.command == "features":
        print_features()
        return 0

    try:
        bus, modules, banner = open_backend(
            args.backend, args.port, port_factory=port_factory, profile=args.profile
        )
    except Exception as exc:  # bad backend / missing port / serial open failed
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.command == "scan":
            print(banner)
            print(format_scan_report(scan_vehicle(bus, modules)))
        elif args.command == "dtc":
            print(banner)
            print(format_dtc_report(scan_vehicle_dtcs(bus, modules)))
        elif args.command == "read":
            pid = int(args.pid, 16)
            result = _obd_client(bus).current_data(pid)
            print(banner)
            print(f"{result.name}: {result.value} {result.unit}")
        elif args.command == "vin":
            print(banner)
            print(f"VIN: {_obd_client(bus).read_vin()}")
        elif args.command == "clear-dtc":
            _obd_client(bus).clear_dtcs()
            print(banner)
            print("DTCs cleared.")
        elif args.command == "read-feature":
            feature = EXAMPLE_FEATURES.get(args.key)
            if feature is None:
                raise ValueError(
                    f"unknown feature {args.key!r}; try 'features' to list them"
                )
            _def, current = _feature_coder_for(bus, feature).read_feature(args.key)
            print(banner)
            print(f"{feature.name} [{feature.module}]: {current or 'unknown'}  "
                  f"(options: {sorted(feature.options)})")
            print("  ! EXAMPLE/UNVERIFIED mapping — demo only; confirm the real "
                  "block before trusting this.")
        elif args.command == "set-feature":
            feature = EXAMPLE_FEATURES.get(args.key)
            if feature is None:
                raise ValueError(f"unknown feature {args.key!r}; try 'features'")
            if args.option not in feature.options:
                raise ValueError(
                    f"unknown option {args.option!r} for {args.key}; "
                    f"choices: {sorted(feature.options)}"
                )
            # Gate 3: never write a built-in EXAMPLE (unverified) map to a real car.
            if args.backend != "simulator":
                print(
                    "error: set-feature runs on the simulator only — the built-in feature "
                    "maps are EXAMPLE/UNVERIFIED. For real coding use FORScan, or supply a "
                    "verified feature definition.",
                    file=sys.stderr,
                )
                return 2
            coder = _feature_coder_for(bus, feature, store=_store_for(args.backup_file))
            _def, current = coder.read_feature(args.key)
            print(banner)
            if not args.confirm:  # Gates 1+2: dry run unless --confirm
                print(f"{feature.name} [{feature.module}]: {current} -> {args.option}  (DRY RUN)")
                print("  Re-run with --confirm to write. Backup-before-write + read-back "
                      "verify will apply.")
            else:
                coder.set_feature(args.key, args.option)  # backup -> write -> verify
                _def2, now = coder.read_feature(args.key)
                print(f"{feature.name} [{feature.module}]: {current} -> {now}  "
                      f"(written, read-back verified)")
                backed = "saved to %s" % args.backup_file if args.backup_file else "captured in-session"
                print(f"  Original block backed up ({backed}).")
        elif args.command == "restore-feature":
            feature = EXAMPLE_FEATURES.get(args.key)
            if feature is None:
                raise ValueError(f"unknown feature {args.key!r}; try 'features'")
            if args.backend != "simulator":
                print(
                    "error: restore-feature runs on the simulator only (built-in maps are "
                    "EXAMPLE/UNVERIFIED).",
                    file=sys.stderr,
                )
                return 2
            coder = _feature_coder_for(bus, feature, store=_store_for(args.backup_file))
            coder.restore_feature(args.key)  # NoBackupError if none saved
            _def, now = coder.read_feature(args.key)
            print(banner)
            print(f"{feature.name} [{feature.module}]: restored to '{now}' from backup.")
        elif args.command == "log":
            pids = [int(p, 16) for p in args.pids.split(",") if p.strip()]
            rows = DataLogger(_obd_client(bus), pids).run(args.samples, interval=args.interval)
            csv_text = rows_to_csv(rows, pids)
            print(banner)
            if args.out:
                with open(args.out, "w", newline="") as fh:
                    fh.write(csv_text)
                print(f"logged {len(rows)} samples of {len(pids)} PID(s) to {args.out}")
            else:
                print(csv_text, end="")
    except Exception as exc:  # surface a clean message, non-zero exit
        print(f"error: {exc}", file=sys.stderr)
        return 3
    finally:
        if args.backend != "simulator":
            try:
                bus.close()
            except Exception:
                pass
    return 0
