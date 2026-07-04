"""In-process CAN transport for hardware-free development and testing.

A ``SimulatorTransport`` runs a *responder* that maps each outgoing ``CanFrame``
to zero or more reply frames, which are queued and returned by ``recv``. This
lets every layer above the transport be exercised deterministically with no car
and no adapter attached. The responder is swappable, so later layers can supply
richer simulated ECUs (ISO-TP, UDS) without changing the transport itself.
"""
from __future__ import annotations

from collections import deque
from typing import Callable, Iterable

from .base import CanFrame, Transport, TransportNotOpen

# A responder turns one request frame into zero or more reply frames.
Responder = Callable[[CanFrame], Iterable[CanFrame]]


def null_responder(frame: CanFrame) -> Iterable[CanFrame]:
    """A silent bus: nothing answers."""
    return ()


def echo_responder(frame: CanFrame) -> Iterable[CanFrame]:
    """Reply on ``arbitration_id + 8`` (mirrors the OBD-II 0x7E0->0x7E8 offset),
    echoing the payload. A trivially-correct fixture for send/recv plumbing."""
    reply_id = frame.arbitration_id + 8
    return (CanFrame(reply_id, frame.data, is_extended=frame.is_extended),)


def canned_obd_responder(frame: CanFrame) -> Iterable[CanFrame]:
    """Minimal single-frame OBD-II ECU.

    Answers a Mode 01 / PID 0x0C (engine RPM) request sent to the functional
    address 0x7DF or the physical address 0x7E0 with a positive response from
    0x7E8 encoding exactly 1000 rpm (raw 4000 = 0x0FA0, since rpm = raw/4).

    This is a *fixture*, not a real ISO-TP/UDS stack — proper segmentation and
    decoding arrive in later layers. It only pattern-matches the raw request.
    """
    if frame.arbitration_id not in (0x7DF, 0x7E0):
        return ()
    if len(frame.data) < 3:
        return ()
    length, service, pid = frame.data[0], frame.data[1], frame.data[2]
    if (length, service, pid) != (0x02, 0x01, 0x0C):
        return ()
    payload = bytes([0x04, 0x41, 0x0C, 0x0F, 0xA0, 0x00, 0x00, 0x00])
    return (CanFrame(0x7E8, payload),)


class SimulatorTransport(Transport):
    """A CAN bus that exists entirely in memory."""

    def __init__(self, responder: "Responder | None" = None) -> None:
        self._responder: Responder = responder or null_responder
        self._rx: "deque[CanFrame]" = deque()
        self._open = False
        # Every frame passed to send(), kept for test/inspection convenience.
        self.sent: list[CanFrame] = []

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False
        self._rx.clear()

    @property
    def is_open(self) -> bool:
        return self._open

    def set_responder(self, responder: Responder) -> None:
        """Swap the simulated-ECU behaviour (used by higher-layer test fixtures)."""
        self._responder = responder

    def send(self, frame: CanFrame) -> None:
        if not self._open:
            raise TransportNotOpen("send() called before open()")
        self.sent.append(frame)
        for reply in self._responder(frame):
            self._rx.append(reply)

    def recv(self, timeout: float = 1.0) -> "CanFrame | None":
        if not self._open:
            raise TransportNotOpen("recv() called before open()")
        if self._rx:
            return self._rx.popleft()
        return None
