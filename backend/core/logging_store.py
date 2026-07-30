from __future__ import annotations

from collections import deque

from .models import CanFrame, LogEntry


class LoggingStore:
    """In-memory ring buffers for system logs and recent CAN messages."""

    def __init__(self, log_capacity: int = 2000, frame_capacity: int = 2000) -> None:
        self.logs: deque[LogEntry] = deque(maxlen=log_capacity)
        self.frames: deque[CanFrame] = deque(maxlen=frame_capacity)

    def add_log(self, entry: LogEntry) -> None:
        self.logs.append(entry)

    def add_frame(self, frame: CanFrame) -> None:
        self.frames.append(frame)

    def clear_logs(self) -> None:
        self.logs.clear()

    def clear_frames(self) -> None:
        self.frames.clear()


def list_serial_ports() -> list[str]:
    import serial.tools.list_ports

    return [p.device for p in serial.tools.list_ports.comports()]
