from __future__ import annotations

import logging
import threading
import time

import serial

from .diagnostics import port_details, port_present, power_source
from .events import Signal
from .packet import MLD_BAUDRATE_ACK, ParsedFrame, StreamFramer, build_frame

logger = logging.getLogger(__name__)

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

    # No bytes at all for this long while the port is open counts as a stall.
    # Field logs show the JIG sometimes goes silent with the port still open
    # and no serial error (only a USB replug brings it back), so silence is
    # the only symptom there is to detect. Short gaps while a charger is being
    # swapped also trip this - the warning just clears once data resumes.
    STALL_SECONDS = 10.0

    # While stalled, repeat a "still silent" line this often so the log shows
    # the app itself stayed alive (vs. the PC sleeping) until the replug.
    STALL_REPEAT_SECONDS = 60.0

    # A gap this long between two loop iterations (each read waits at most
    # 0.2s) means the whole process was suspended - normally PC sleep.
    SUSPEND_GAP_SECONDS = 5.0

    # How often to re-check the laptop's power source and log any change.
    POWER_CHECK_SECONDS = 5.0

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
        self.handshake_ack = Signal()  # fired on every valid frame from the JIG (ack or CAN data)
        self.data_stalled = Signal()  # float: seconds since the last byte
        self.data_resumed = Signal()  # float: how long the stall lasted

    def write_frame(self, mld: int, can_id: int, payload: bytes) -> None:
        frame = build_frame(mld, can_id, payload)
        with self._lock:
            if self._ser is not None:
                self._ser.write(frame)

    def run(self) -> None:
        self._running = True
        try:
            # write_timeout: a JIG whose USB has stopped accepting data must
            # not block write() forever - that would wedge this thread with
            # the port still open, so every later Connect fails until replug.
            self._ser = serial.Serial(self._port_name, self._baudrate, timeout=0.2, write_timeout=1.0)
        except serial.SerialException as exc:
            logger.error("Serial %s: failed to open: %s", self._port_name, exc)
            self.connection_lost.emit(str(exc))
            return

        logger.info(
            "Serial port %s opened at %d baud: %s; laptop power=%s",
            self._port_name, self._baudrate, port_details(self._port_name), power_source(),
        )
        self.connected.emit()
        try:
            self.write_frame(MLD_BAUDRATE_ACK, BAUDRATE_SET_CAN_ID, _baudrate_set_payload(self._baudrate))
            logger.info("Serial %s: baudrate-set sent", self._port_name)
        except serial.SerialException as exc:
            # Keep reading anyway - some JIG firmware streams without it.
            logger.error("Serial %s: sending baudrate-set failed: %s", self._port_name, exc)
        framer = StreamFramer()

        # Diagnostic counters for "connected but no live data" reports: proves
        # whether raw bytes are arriving at all, and separately whether the
        # framer is successfully turning them into ParsedFrames, without
        # logging every single read (which would flood the log at real bus rates).
        bytes_read_total = 0
        frames_parsed_total = 0
        last_log_time = 0.0
        last_data_time = time.monotonic()
        stalled = False
        last_stall_log = 0.0
        last_port_check = 0.0
        last_port_present: bool | None = True
        last_power = power_source()
        last_power_check = time.monotonic()
        # Wall clock, not monotonic: on Windows time.monotonic() may not
        # advance while the PC sleeps, which is exactly the gap to detect.
        last_iteration_wall = time.time()

        while self._running:
            try:
                data = self._ser.read(256)
            except serial.SerialException as exc:
                logger.error(
                    "Serial %s: read failed: %s (port listed by Windows: %s)",
                    self._port_name, exc, port_present(self._port_name),
                )
                self.connection_lost.emit(str(exc))
                break

            wall = time.time()
            if wall - last_iteration_wall >= self.SUSPEND_GAP_SECONDS:
                logger.warning(
                    "Serial %s: app was paused for %.0fs - PC was probably asleep or suspended",
                    self._port_name, wall - last_iteration_wall,
                )
            last_iteration_wall = wall

            mono = time.monotonic()
            if mono - last_power_check >= self.POWER_CHECK_SECONDS:
                last_power_check = mono
                power = power_source()
                if power.split()[0] != last_power.split()[0]:  # ignore battery % changes
                    logger.info("Laptop power source changed: %s -> %s", last_power, power)
                last_power = power

            if not data:
                silent_for = mono - last_data_time
                if not stalled and silent_for >= self.STALL_SECONDS:
                    stalled = True
                    last_stall_log = last_port_check = mono
                    last_port_present = port_present(self._port_name)
                    logger.warning(
                        "Serial %s: no data from JIG for %.0fs (port still open, listed by Windows: %s, "
                        "laptop power=%s); totals: %d bytes read, %d frames parsed",
                        self._port_name, silent_for, last_port_present, last_power,
                        bytes_read_total, frames_parsed_total,
                    )
                    self.data_stalled.emit(silent_for)
                elif stalled and mono - last_stall_log >= self.STALL_REPEAT_SECONDS:
                    last_stall_log = last_port_check = mono
                    present = port_present(self._port_name)
                    logger.warning(
                        "Serial %s: still no data from JIG after %.0fs (listed by Windows: %s, laptop power=%s)",
                        self._port_name, silent_for, present, last_power,
                    )
                    last_port_present = present
                elif stalled and mono - last_port_check >= self.POWER_CHECK_SECONDS:
                    last_port_check = mono
                    # Catches the moment the USB cable is pulled during a
                    # stall: Windows drops the port even if read() keeps
                    # returning empty instead of raising.
                    present = port_present(self._port_name)
                    if present is not None and present != last_port_present:
                        logger.warning(
                            "Serial %s: port %s by Windows after %.0fs of silence",
                            self._port_name, "is listed again" if present else "is no longer listed", silent_for,
                        )
                        last_port_present = present
                continue

            now = time.monotonic()
            if stalled:
                stalled = False
                logger.info("Serial %s: data resumed after %.0fs of silence", self._port_name, now - last_data_time)
                self.data_resumed.emit(now - last_data_time)
            last_data_time = now
            bytes_read_total += len(data)

            try:
                frames = framer.feed(data)
            except Exception as exc:  # noqa: BLE001
                self.parse_error.emit(str(exc))
                continue

            frames_parsed_total += len(frames)
            for frame in frames:
                self._dispatch(frame)

            now = time.monotonic()
            if now - last_log_time >= 5.0:
                logger.info(
                    "Serial %s: %d bytes read, %d frames parsed so far",
                    self._port_name, bytes_read_total, frames_parsed_total,
                )
                last_log_time = now

        logger.info(
            "Serial worker for %s stopping; totals: %d bytes read, %d frames parsed",
            self._port_name, bytes_read_total, frames_parsed_total,
        )
        with self._lock:
            if self._ser is not None:
                self._ser.close()

    def _dispatch(self, frame: ParsedFrame) -> None:
        # Any well-formed frame proves the JIG is alive on this port, not just
        # the baudrate-set ack: some JIG firmware (seen on FW 1.2) streams CAN
        # frames without ever echoing the ack, and requiring it specifically
        # made connect_to() tear down a perfectly working link.
        if frame.mld == MLD_BAUDRATE_ACK:
            logger.info("Serial %s: baudrate-set ack received", self._port_name)
        self.handshake_ack.emit()
        self.frame_received.emit(frame)

    def stop(self) -> None:
        self._running = False


class SerialLink:
    """Owns the worker thread lifecycle for a real serial connection."""

    # How long to wait for the worker thread to actually open the port
    # before giving up and reporting failure to the caller.
    CONNECT_TIMEOUT = 3.0

    # How long, after the port opens, to wait for the first valid frame
    # before warning that nothing has arrived yet. It's only a warning - the
    # port stays open. The JIG (STM32 USB) can take several seconds to start
    # streaming after the port opens; closing it after a short timeout (as
    # v1.0.1-v1.0.8 did) left it silent, and every retry restarted the delay.
    HANDSHAKE_TIMEOUT = 3.0

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._worker: SerialWorker | None = None

        self.frame_received = Signal()
        self.parse_error = Signal()
        self.connection_lost = Signal()
        self.connected = Signal()
        self.data_stalled = Signal()
        self.data_resumed = Signal()

    def connect_to(self, port: str, baudrate: int = 115200) -> tuple[bool, str]:
        """Starts the worker thread and blocks until the serial port has
        actually been opened and (up to HANDSHAKE_TIMEOUT) the first JIG
        frame has arrived, so callers get a real success/failure result instead of an
        optimistic 'thread started' ack. Returns (ok, message): on failure
        the error, on success an optional warning (no JIG data yet)."""
        self.disconnect()

        outcome: dict[str, str | None] = {"error": None}
        port_opened = threading.Event()
        handshake_done = threading.Event()

        self._worker = SerialWorker(port, baudrate)
        self._worker.frame_received.connect(self.frame_received.emit)
        self._worker.parse_error.connect(self.parse_error.emit)
        self._worker.data_stalled.connect(self.data_stalled.emit)
        self._worker.data_resumed.connect(self.data_resumed.emit)

        def _on_connected() -> None:
            port_opened.set()

        def _on_connection_lost(reason: str) -> None:
            outcome["error"] = reason
            port_opened.set()
            handshake_done.set()

        def _on_handshake_ack() -> None:
            handshake_done.set()

        self._worker.connected.connect(_on_connected)
        self._worker.connected.connect(self.connected.emit)
        self._worker.connection_lost.connect(_on_connection_lost)
        self._worker.connection_lost.connect(self.connection_lost.emit)
        self._worker.handshake_ack.connect(_on_handshake_ack)

        self._thread = threading.Thread(target=self._worker.run, daemon=True)
        self._thread.start()

        if not port_opened.wait(timeout=self.CONNECT_TIMEOUT):
            self.disconnect()
            return False, f"Timed out opening {port}"

        if outcome["error"] is not None:
            self._thread = None
            self._worker = None
            return False, outcome["error"]

        if not handshake_done.wait(timeout=self.HANDSHAKE_TIMEOUT):
            # Keep the port open - data usually starts shortly after. The
            # second element is a non-fatal warning for the UI to show.
            logger.warning("Serial %s: no data from JIG yet after %.0fs; keeping port open", port, self.HANDSHAKE_TIMEOUT)
            return True, (
                f"Connected to {port}, but no data from the JIG yet - "
                "if it doesn't appear, check this is the correct port and the JIG is powered on"
            )

        if outcome["error"] is not None:
            # connection dropped while we were waiting on the handshake
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
