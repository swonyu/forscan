"""ELM327 / STN CAN transport — the bridge to an OBDLink EX / ELM327 adapter.

ELM327 is an AT-command serial device. Configured with headers on (``ATH1``),
spaces on (``ATS1``), and CAN auto-formatting OFF (``ATCAF0``) it exposes raw CAN
frames: you set the tx arbitration id with ``ATSH<id>``, write the payload as
hex, and responses arrive as ``<header> <bytes...>`` lines terminated by a ``>``
prompt. Our ISO-TP layer then rides on top.

WHAT IS TESTED HERE: the response-line parser, the AT command builder, and the
transport's write sequencing over an injected port — all deterministic. WHAT IS
NOT: the live device's timing/prompt handshake, 29-bit header handling, and
multi-frame flow-control in raw mode. Those are genuinely finicky and are
NEEDS ON-CAR CHECK. ``Elm327Transport`` takes a duck-typed serial port so it
stays dependency-free and testable.
"""
from __future__ import annotations

from typing import List, Optional

from .base import (
    CanFrame,
    Transport,
    TransportNotOpen,
    CAN_MAX_CLASSIC_DLC,
    CAN_MAX_11BIT_ID,
    CAN_MAX_29BIT_ID,
)

_PROMPT = 0x3E  # '>'

# Init sequence: reset, echo off, linefeeds off, spaces ON (parseable), headers
# ON, CAN auto-format OFF (raw frames — we do our own ISO-TP).
DEFAULT_INIT_COMMANDS = [b"ATZ\r", b"ATE0\r", b"ATL0\r", b"ATS1\r", b"ATH1\r", b"ATCAF0\r"]

# Lines that are status/acks, never CAN data.
_STATUS_MARKERS = (
    "SEARCHING", "NO DATA", "UNABLE TO CONNECT", "STOPPED", "BUS INIT", "BUS BUSY",
    "BUFFER FULL", "CAN ERROR", "DATA ERROR", "FB ERROR", "ERROR", "?", "OK",
)


def protocol_command(protocol: str = "6") -> bytes:
    """ATSP<n>: set the CAN protocol (6 = ISO 15765-4 11-bit 500k, 7 = 29-bit 500k)."""
    return f"ATSP{protocol}\r".encode("ascii")


def header_command(arb_id: int, is_extended: bool = False) -> bytes:
    """ATSH<id>: set the transmit header. 29-bit form is NEEDS ON-CAR CHECK."""
    if is_extended:
        return f"ATSH{arb_id:08X}\r".encode("ascii")
    return f"ATSH{arb_id:03X}\r".encode("ascii")


def payload_line(data: bytes) -> bytes:
    """The hex payload line to transmit (device wraps it with the current header)."""
    return (data.hex().upper() + "\r").encode("ascii")


def parse_response_line(line, *, is_extended: bool = False) -> Optional[CanFrame]:
    """Parse one ``<header> <bytes...>`` response line into a CanFrame.

    Returns None for prompts, blank lines, and status/error replies.
    """
    if isinstance(line, (bytes, bytearray)):
        line = bytes(line).decode("ascii", errors="ignore")
    line = line.replace(">", " ").strip()
    if not line:
        return None
    if any(marker in line.upper() for marker in _STATUS_MARKERS):
        return None
    tokens = line.split()
    header_tokens = 4 if is_extended else 1
    if len(tokens) < header_tokens + 1:
        return None
    try:
        arb = int("".join(tokens[:header_tokens]), 16)
        data = bytes(int(tok, 16) for tok in tokens[header_tokens:])
    except ValueError:
        return None
    if len(data) > CAN_MAX_CLASSIC_DLC:
        return None  # malformed: more than 8 data bytes — skip, don't crash
    if arb > (CAN_MAX_29BIT_ID if is_extended else CAN_MAX_11BIT_ID):
        return None  # malformed: header exceeds the 11-/29-bit range — skip, don't crash
    return CanFrame(arb, data, is_extended=is_extended)


class Elm327Transport(Transport):
    def __init__(self, port, *, protocol: str = "6") -> None:
        self.port = port
        self.protocol = protocol
        self._open = False
        self._current_header: Optional[int] = None
        self._current_extended: bool = False
        self._rx_frames: List[CanFrame] = []

    def _read_until_prompt(self) -> str:
        buf = bytearray()
        while True:
            chunk = self.port.read(64)
            if not chunk:
                break
            buf.extend(chunk)
            if _PROMPT in buf:
                break
        return buf.decode("ascii", errors="ignore")

    def open(self) -> None:
        for command in DEFAULT_INIT_COMMANDS:
            self.port.write(command)
            self._read_until_prompt()
        self.port.write(protocol_command(self.protocol))
        self._read_until_prompt()
        self._open = True

    def close(self) -> None:
        self._open = False
        self._current_header = None
        self._rx_frames.clear()

    @property
    def is_open(self) -> bool:
        return self._open

    def send(self, frame: CanFrame) -> None:
        if not self._open:
            raise TransportNotOpen("send() before open()")
        if frame.arbitration_id != self._current_header or frame.is_extended != self._current_extended:
            self.port.write(header_command(frame.arbitration_id, frame.is_extended))
            self._read_until_prompt()
            self._current_header = frame.arbitration_id
            self._current_extended = frame.is_extended
        self.port.write(payload_line(frame.data))

    def recv(self, timeout: float = 1.0) -> Optional[CanFrame]:
        if not self._open:
            raise TransportNotOpen("recv() before open()")
        if not self._rx_frames:
            text = self._read_until_prompt()
            for raw in text.replace("\r", "\n").split("\n"):
                frame = parse_response_line(raw, is_extended=self._current_extended)
                if frame is not None:
                    self._rx_frames.append(frame)
        if self._rx_frames:
            return self._rx_frames.pop(0)
        return None
