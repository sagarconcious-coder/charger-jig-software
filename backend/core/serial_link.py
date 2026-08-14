from __future__ import annotations

import threading

import serial

from .events import Signal
from .packet import MLD_BAUDRATE_ACK, StreamFramer, build_frame

# Sent once on connect to tell the JIG tool which CAN baudrate to run at.
# Mirrors the legacy Node bridge: canId=974256 (0xEDEF0), mld=2 (baudrate set).
BAUDRATE_SET_CAN_ID = 974256
_BAUDRATE_CODES = {125_000: 0x01, 250_000: 0x02, 500_000: 0x03, 1_000_000: 0x04}


def _baudrate_set_payload(baudrate: int) -> bytes:
    code = _BAUDRATE_CODES.get(baudrate, 0x03)
    return bytes([code, 0, 0, 0, 0, 0, 0, 0x00])


class SerialWorker:
    """Reads raw bytes from a serial port on a background thread and emits
    parsed frames. Runs inside a daemon Thread started by SerialLink.
    """

    def __init__(self, port: str, baudrate: int) -> None:
        self._port_name = port
        self._baudrate = baudrate
        self._running = False
        self._ser: serial.Serial | None = None
        self._lock = threading.Lock()

        self.frame_received = Signal()  # ParsedFrame
        self.parse_error = Signal()
        self.connection_lost = Signal()
        self.connected = Signal()

    def write_frame(self, mld: int, can_id: int, payload: bytes) -> None:
        frame = build_frame(mld, can_id, payload)
        with self._lock:
            if self._ser is not None:
                self._ser.write(frame)

    def run(self) -> None:
        self._running = True
        print("RUNNING.....................................")
        try:
            self._ser = serial.Serial(self._port_name, self._baudrate, timeout=0.2)
        except serial.SerialException as exc:
            self.connection_lost.emit(str(exc))
            return

        self.connected.emit()
        self.write_frame(MLD_BAUDRATE_ACK, BAUDRATE_SET_CAN_ID, _baudrate_set_payload(self._baudrate))
        framer = StreamFramer()

        while self._running:
            try:
                data = self._ser.read(256)
            except serial.SerialException as exc:
                self.connection_lost.emit(str(exc))
                break

            if not data:
                continue

            try:
                frames = framer.feed(data)
            except Exception as exc:  # noqa: BLE001
                self.parse_error.emit(str(exc))
                continue

            for frame in frames:
                self.frame_received.emit(frame)

        with self._lock:
            if self._ser is not None:
                self._ser.close()

    def stop(self) -> None:
        self._running = False


class SerialLink:
    """Owns the worker thread lifecycle for a real serial connection."""

    # How long to wait for the worker thread to actually open the port
    # before giving up and reporting failure to the caller.
    CONNECT_TIMEOUT = 3.0

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._worker: SerialWorker | None = None

        self.frame_received = Signal()
        self.parse_error = Signal()
        self.connection_lost = Signal()
        self.connected = Signal()

    def connect_to(self, port: str, baudrate: int = 115200) -> tuple[bool, str]:
        """Starts the worker thread and blocks until the serial port has
        actually been opened (or failed to open), so callers get a real
        success/failure result instead of an optimistic 'thread started' ack.
        Returns (ok, error_message)."""
        self.disconnect()

        outcome: dict[str, str | None] = {"error": None}
        done = threading.Event()

        self._worker = SerialWorker(port, baudrate)
        self._worker.frame_received.connect(self.frame_received.emit)
        self._worker.parse_error.connect(self.parse_error.emit)

        def _on_connected() -> None:
            done.set()

        def _on_connection_lost(reason: str) -> None:
            outcome["error"] = reason
            done.set()

        self._worker.connected.connect(_on_connected)
        self._worker.connected.connect(self.connected.emit)
        self._worker.connection_lost.connect(_on_connection_lost)
        self._worker.connection_lost.connect(self.connection_lost.emit)

        self._thread = threading.Thread(target=self._worker.run, daemon=True)
        self._thread.start()

        if not done.wait(timeout=self.CONNECT_TIMEOUT):
            self.disconnect()
            return False, f"Timed out opening {port}"

        if outcome["error"] is not None:
            self._thread = None
            self._worker = None
            return False, outcome["error"]

        return True, ""

    def write_frame(self, mld: int, can_id: int, payload: bytes) -> None:
        if self._worker is not None:
            self._worker.write_frame(mld, can_id, payload)

    def disconnect(self) -> None:
        if self._worker is not None:
            self._worker.stop()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._worker = None

    @property
    def is_connected(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
