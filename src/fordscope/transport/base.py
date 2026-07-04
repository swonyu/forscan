"""CAN frame abstraction and the ``Transport`` interface.

Everything above this layer (ISO-TP, UDS, OBD-II, services, UI) speaks in
``CanFrame`` objects and never touches hardware directly. Concrete transports
— the simulator, an slcan dongle, a Tactrix Openport — all implement the same
``Transport`` ABC, so the rest of FordScope is hardware-agnostic and fully
testable without a car attached.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

# Classic CAN (CAN 2.0) limits. CAN-FD is explicitly out of scope for now.
CAN_MAX_11BIT_ID = 0x7FF
CAN_MAX_29BIT_ID = 0x1FFFFFFF
CAN_MAX_CLASSIC_DLC = 8


class TransportError(Exception):
    """Base class for transport-layer failures."""


class TransportNotOpen(TransportError):
    """Raised when send/recv is attempted before ``open()``."""


@dataclass(frozen=True)
class CanFrame:
    """A single classic-CAN data frame.

    Attributes:
        arbitration_id: 11-bit (standard) or 29-bit (extended) identifier.
        data: 0..8 payload bytes.
        is_extended: True for a 29-bit identifier, False for 11-bit.
        timestamp: optional receive time in seconds, populated by receivers.
    """

    arbitration_id: int
    data: bytes = b""
    is_extended: bool = False
    timestamp: "float | None" = None

    def __post_init__(self) -> None:
        if self.arbitration_id < 0:
            raise ValueError(
                f"arbitration_id must be non-negative, got {self.arbitration_id}"
            )
        max_id = CAN_MAX_29BIT_ID if self.is_extended else CAN_MAX_11BIT_ID
        if self.arbitration_id > max_id:
            width = "29" if self.is_extended else "11"
            raise ValueError(
                f"arbitration_id 0x{self.arbitration_id:X} exceeds {width}-bit "
                f"maximum 0x{max_id:X}"
            )
        if not isinstance(self.data, (bytes, bytearray)):
            raise TypeError(f"data must be bytes-like, got {type(self.data).__name__}")
        if len(self.data) > CAN_MAX_CLASSIC_DLC:
            raise ValueError(
                f"classic CAN frame carries at most {CAN_MAX_CLASSIC_DLC} bytes, "
                f"got {len(self.data)}"
            )
        # Normalise bytearray -> bytes so the frozen instance stays hashable.
        if isinstance(self.data, bytearray):
            object.__setattr__(self, "data", bytes(self.data))

    def __repr__(self) -> str:
        kind = "ext" if self.is_extended else "std"
        return f"CanFrame(0x{self.arbitration_id:X}/{kind}, [{self.data.hex(' ')}])"


class Transport(ABC):
    """Abstract CAN transport.

    Concrete backends: ``SimulatorTransport`` (no hardware), and later an slcan
    dongle and a Tactrix Openport. Supports use as a context manager::

        with SomeTransport(...) as bus:
            bus.send(frame)
            reply = bus.recv(timeout=1.0)
    """

    @abstractmethod
    def open(self) -> None:
        """Bring the bus up. Idempotent."""

    @abstractmethod
    def close(self) -> None:
        """Tear the bus down. Idempotent."""

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """True between ``open()`` and ``close()``."""

    @abstractmethod
    def send(self, frame: CanFrame) -> None:
        """Transmit one frame. Raises ``TransportNotOpen`` if closed."""

    @abstractmethod
    def recv(self, timeout: float = 1.0) -> "CanFrame | None":
        """Return the next received frame, or None if none arrives in ``timeout``."""

    def __enter__(self) -> "Transport":
        self.open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def close_port(port) -> None:
    """Close a duck-typed serial port if it supports close(), swallowing errors.

    A concrete transport is handed a serial port it does not otherwise own a way to
    release; its ``close()`` must deterministically close that fd rather than leaving
    it to GC (else the webapp leaks one fd per connect/disconnect). Safe on injected
    fakes / ports without a real fd (no-op if there's no ``close``)."""
    close = getattr(port, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
