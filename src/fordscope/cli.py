"""FordScope command-line interface.

Runs against a **simulated** demo vehicle by default; every simulator command prints a
clear SIMULATED banner. The two real-hardware backends (``--backend slcan`` and
``--backend elm327``, both needing ``--port``) carry real, unit-tested codecs but are
UNVALIDATED on-car: they announce a ``NEEDS ON-CAR CHECK`` banner rather than pretend to
be trustworthy, and must be verified against a real vehicle before being relied on.

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
    FUSION_2016_ASBUILT,
    format_catalog,
    additive_checksum,
    parse_hex_bytes,
    verify_full_line,
    features_at_block_line,
    format_block_line_lookup,
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


def format_preflight_checklist() -> str:
    """The first-on-car-session checklist, DERIVED FROM CODE so it can't silently drift
    from ``fusion_2016.FUSION_2016_MODULES``: every module the code currently knows about,
    each with its real confidence tag, plus the safety gates and boundaries that apply to
    ANY on-car session. Static/no-vehicle tier -- pure string formatting, no I/O.

    HONESTY: this is a PLAN. Nothing printed here has been confirmed on a vehicle; every
    module's presence and every As-Built value is `NEEDS ON-CAR CHECK` until read on the
    owner's actual 2016 Fusion S with the Vgate vLinker FS.
    """
    lines = [
        "FordScope preflight checklist -- FIRST ON-CAR SESSION PLAN (nothing verified yet)",
        "=" * 78,
        f"Vehicle scope: {fusion_2016.SCOPE}",
        "",
        "-- Module list (from ford/fusion_2016.py; this output cannot drift from the code) --",
    ]
    by_confidence = {"confirmed": [], "confirm-on-vehicle": [], "plausible": []}
    for m in fusion_2016.FUSION_2016_MODULES:
        by_confidence.setdefault(m.confidence, []).append(m)
    labels = {
        "confirmed": "CONFIRMED (adversarially-verified address; scan first to confirm PRESENCE)",
        "confirm-on-vehicle": "CONFIRM-ON-VEHICLE (address known; presence on this build unverified)",
        "plausible": "PLAUSIBLE (address plausible; presence unverified -- promote or mark ABSENT)",
    }
    for tag in ("confirmed", "confirm-on-vehicle", "plausible"):
        entries = by_confidence.get(tag, [])
        if not entries:
            continue
        lines.append(f"  [{tag}] {labels[tag]}")
        for m in entries:
            addr = f"0x{m.address:03X}"
            note = f" -- {m.note}" if m.note else ""
            lines.append(f"    {m.name:6s} {addr}  confidence={tag}{note}")
    lines += [
        "",
        "Goal for this session: PROMOTE each plausible/confirm-on-vehicle module to",
        "confirmed (it answered) or mark it ABSENT (silence) -- this retires the",
        "\"plausible\" tags honestly instead of leaving them stale.",
        "",
        "-- Safety gates (apply to ANY on-car session) --",
        "  * BACKUP-BEFORE-WRITE: never write an As-Built block without a captured backup",
        "    and a read-back verify AFTER the write. No exceptions.",
        "  * WIRED CONNECTION for BdyCM/BCM (central-config) writes: a dropped BLE link",
        "    mid-write can reboot the module in a bad state. Use a wired OBD connection",
        "    for any BCM/central-config write, not the vLinker FS's wireless mode.",
        "  * macOS is BLE-only for wireless OBD (no Bluetooth-Classic SPP) -- confirm the",
        "    connection mode before relying on it for anything beyond a read.",
        "",
        "-- Never-build boundary (hard stop, no exceptions) --",
        "  * NEVER emissions-defeat coding (readiness spoof, EGR/DPF delete).",
        "  * NEVER anti-theft / immobilizer (PATS) bypass.",
        "  * NEVER reflash that cracks SecurityAccess or ships OEM calibrations.",
        "",
        "NEEDS ON-CAR CHECK: every module's presence, every As-Built read value, and every",
        "community catalog block/line mapping in this checklist is UNVERIFIED until",
        "confirmed on the owner's actual vehicle. This checklist is a PLAN, not a result.",
        "See docs/ON_CAR_VERIFICATION.md for the full phased runbook.",
    ]
    return "\n".join(lines)


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
    sub.add_parser(
        "preflight",
        help="first-on-car-session checklist derived from code (modules + safety gates + "
        "never-build boundary; no vehicle needed, asserts nothing verified)",
    )
    abf = sub.add_parser(
        "asbuilt-features",
        help="browse the community As-Built reference catalog (COMMUNITY-SOURCED/UNVERIFIED; "
        "reference only, no live read/write)",
    )
    abf.add_argument(
        "--module", default=None,
        help="filter by module name (e.g. BCM, IPC) or numeric/hex address (e.g. 0x726)",
    )
    abf.add_argument(
        "--search", default=None,
        help="case-insensitive substring search over feature name and key (e.g. honk)",
    )
    ack = sub.add_parser(
        "asbuilt-checksum",
        help="compute/verify an As-Built LINE checksum (pure; no vehicle needed)",
    )
    ack.add_argument("block_line", help="block label, e.g. 726-17-01")
    ack.add_argument(
        "hex_value",
        help="data hex bytes to checksum (e.g. '0101010101' or '01 01 01 01 01'), or, "
        "with --verify, the FULL line hex incl. the trailing checksum byte",
    )
    ack.add_argument(
        "--verify", action="store_true",
        help="treat hex_value as a full line (data + trailing checksum byte) and report "
        "VALID/INVALID against the recomputed checksum",
    )
    alk = sub.add_parser(
        "asbuilt-lookup",
        help="reverse-lookup: what catalog feature lives at a block-line (pure; no "
        "vehicle needed) -- the inverse of asbuilt-features",
    )
    alk.add_argument("block_line", help="block label as seen in FORScan, e.g. 726-17-01")
    alk.add_argument(
        "--line", default=None, dest="full_line_hex",
        help="full line hex incl. trailing checksum byte (e.g. '01010101014A') to also "
        "check the checksum and match it against known community option values",
    )
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

    # 'ports', 'features', and 'asbuilt-features' are static listings — no vehicle needed.
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
    if args.command == "preflight":
        print(format_preflight_checklist())
        return 0
    if args.command == "asbuilt-features":
        print(format_catalog(FUSION_2016_ASBUILT, module=args.module, search=args.search))
        return 0
    if args.command == "asbuilt-checksum":
        try:
            if args.verify:
                result = verify_full_line(args.block_line, args.hex_value)
                verdict = "VALID" if result.valid else "INVALID"
                print(f"{args.block_line}  {args.hex_value.strip()}  -> {verdict}")
                print(f"  stored checksum byte: {result.actual_checksum:02X}")
                print(f"  expected checksum byte: {result.expected_checksum:02X}")
            else:
                data = parse_hex_bytes(args.hex_value)
                checksum = additive_checksum(args.block_line, data)
                print(f"{args.block_line}  {args.hex_value.strip()}  -> checksum {checksum:02X}")
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print("  ! This computes the LINE checksum only -- it does NOT verify the values "
              "are correct for the vehicle (NEEDS ON-CAR CHECK).")
        return 0
    if args.command == "asbuilt-lookup":
        features = features_at_block_line(args.block_line, FUSION_2016_ASBUILT)
        print(format_block_line_lookup(args.block_line, features))
        if args.full_line_hex is not None:
            try:
                result = verify_full_line(args.block_line, args.full_line_hex)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            verdict = "VALID" if result.valid else "INVALID"
            print(f"Line value: {args.full_line_hex.strip()}  -> checksum {verdict}")
            print(f"  stored checksum byte: {result.actual_checksum:02X}")
            print(f"  expected checksum byte: {result.expected_checksum:02X}")
            # Match against known community option values -- but ONLY for a full_line-kind
            # feature: a full_line option is the whole 6-byte value, so an exact string
            # comparison is meaningful. For nibble/byte-kind features the catalog only
            # records the CHANGED field, not the surrounding bytes, so which option a
            # partial value encodes cannot be determined from a full-line paste without
            # fabricating a decode -- say so honestly instead of guessing.
            full_line_features = [f for f in features if f.kind == "full_line"]
            given_norm = parse_hex_bytes(args.full_line_hex).hex().upper()
            for f in full_line_features:
                match = next(
                    (meaning for value, meaning in f.options
                     if value.upper() == given_norm),
                    None,
                )
                if match is not None:
                    print(f"  {f.name}: matches: {match}")
                else:
                    print(f"  {f.name}: value is not a recognized community option "
                          f"(known options: {', '.join(v for v, _ in f.options)})")
            partial_features = [f for f in features if f.kind in ("nibble", "byte")]
            for f in partial_features:
                print(f"  {f.name}: bits={f.bits} — per-nibble/byte decoding of a partial "
                      f"value is not attempted (would require guessing the unchanged "
                      f"surrounding bytes); options: "
                      f"{', '.join(v + '=' + m for v, m in f.options)}")
            print("  ! Checksum VALID means only that the trailing byte is self-consistent "
                  "with this label+data -- it does NOT mean the value is correct for the "
                  "vehicle (NEEDS ON-CAR CHECK).")
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
    except KeyboardInterrupt:  # Ctrl-C during a slow command -> clean abort, not a traceback
        print("Interrupted.", file=sys.stderr)
        return 130
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
