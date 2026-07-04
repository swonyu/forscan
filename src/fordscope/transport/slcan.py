"""slcan (LAWICEL) CAN transport — the bridge to a real serial CAN adapter.

slcan is the ASCII line protocol spoken by CANable / CANtact / many USB-CAN
dongles (the ~$30 path). A frame is a line like ``t7DF3020100`` (standard) or
``T18DAF110322F190`` (extended), terminated by CR.

WHAT IS TESTED HERE: the wire codec (encode/parse) and the transport's command
sequencing against an injected port — all pure/deterministic. WHAT IS NOT: real
serial-port timing, buffering, and adapter quirks. ``SlcanTransport`` takes a
duck-typed port (``.write(bytes)`` / ``.read(n) -> bytes``, e.g. a pyserial
Serial) so it stays dependency-free and testable; the live serial path is
NEEDS ON-CAR CHECK.
"""
from __future__ import annotations

from typing import Optional

from .base import (
    CanFrame,
    Transport,
    TransportNotOpen,
    CAN_MAX_CLASSIC_DLC,
    CAN_MAX_11BIT_ID,
    CAN_MAX_29BIT_ID,
    close_port,
)

OPEN_COMMAND = b"O\r"
CLOSE_COMMAND = b"C\r"
_CR = 0x0D

# slcan bitrate presets. Ford: HS-CAN = 500 kbit (S6), MS-CAN = 125 kbit (S4).
_BITRATE_CMDS = {
    10: b"S0\r", 20: b"S1\r", 50: b"S2\r", 100: b"S3\r", 125: b"S4\r",
    250: b"S5\r", 500: b"S6\r", 800: b"S7\r", 1000: b"S8\r",
}


def bitrate_command(kbps: int) -> bytes:
    if kbps not in _BITRATE_CMDS:
        raise ValueError(f"unsupported slcan bitrate {kbps} kbit; choices: {sorted(_BITRATE_CMDS)}")
    return _BITRATE_CMDS[kbps]


def encode_frame(frame: CanFrame) -> bytes:
    """CanFrame -> an slcan transmit line (with trailing CR)."""
    dlc = len(frame.data)
    data_hex = frame.data.hex().upper()
    if frame.is_extended:
        return f"T{frame.arbitration_id:08X}{dlc:X}{data_hex}\r".encode("ascii")
    return f"t{frame.arbitration_id:03X}{dlc:X}{data_hex}\r".encode("ascii")


def parse_frame(line) -> Optional[CanFrame]:
    """Parse one slcan line (CR already stripped or not) into a CanFrame.

    Returns None for empty lines, status replies, or malformed frames — so a
    receiver can skip non-data lines without crashing.
    """
    if isinstance(line, (bytes, bytearray)):
        line = bytes(line).decode("ascii", errors="ignore")
    line = line.strip()
    if not line:
        return None
    kind = line[0]
    if kind == "t":
        if len(line) < 5:
            return None
        id_hex, dlc_hex, rest = line[1:4], line[4], line[5:]
        extended = False
    elif kind == "T":
        if len(line) < 10:
            return None
        id_hex, dlc_hex, rest = line[1:9], line[9], line[10:]
        extended = True
    else:
        return None  # 'r'/'R' remote frames and status lines are ignored
    try:
        arb = int(id_hex, 16)
        dlc = int(dlc_hex, 16)
    except ValueError:
        return None
    if dlc > CAN_MAX_CLASSIC_DLC:
        return None  # malformed: exceeds classic-CAN 8-byte max — skip, don't crash
    if arb > (CAN_MAX_29BIT_ID if extended else CAN_MAX_11BIT_ID):
        return None  # malformed: ID exceeds the 11-/29-bit range — skip, don't crash
    data_hex = rest[: 2 * dlc]
    if len(data_hex) < 2 * dlc:
        return None
    try:
        data = bytes.fromhex(data_hex)
    except ValueError:
        return None
    return CanFrame(arb, data, is_extended=extended)


class SlcanTransport(Transport):
    def __init__(self, port, *, bitrate_kbps: int = 500) -> None:
        self.port = port
        self.bitrate_kbps = bitrate_kbps
        self._open = False
        self._rx = bytearray()

    def open(self) -> None:
        self.port.write(bitrate_command(self.bitrate_kbps))
        self.port.write(OPEN_COMMAND)
        self._open = True

    def close(self) -> None:
        try:
            if self._open:
                self.port.write(CLOSE_COMMAND)
        except Exception:
            pass  # adapter may be gone (OSError) — release the fd regardless
        self._open = False
        close_port(self.port)

    @property
    def is_open(self) -> bool:
        return self._open

    def send(self, frame: CanFrame) -> None:
        if not self._open:
            raise TransportNotOpen("send() before open()")
        self.port.write(encode_frame(frame))

    def recv(self, timeout: float = 1.0) -> Optional[CanFrame]:
        if not self._open:
            raise TransportNotOpen("recv() before open()")
        while True:
            idx = self._rx.find(bytes([_CR]))
            if idx != -1:
                line = bytes(self._rx[:idx])
                del self._rx[: idx + 1]
                frame = parse_frame(line)
                if frame is not None:
                    return frame
                continue  # status/ack line — keep scanning
            chunk = self.port.read(64)
            if not chunk:
                return None  # nothing more available within the port's timeout
            self._rx.extend(chunk)
