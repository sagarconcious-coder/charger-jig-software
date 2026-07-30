from __future__ import annotations

import time
from collections import deque

from .dbc_store import DbcStore
from .events import Signal
from .models import CanFrame, LogEntry, Source
from .packet import MLD_BAUDRATE_ACK, MLD_CAN_FRAME, ParsedFrame


class CanBus:
    """Glues a serial/mock link + DbcStore together: raw ParsedFrame events
    in, decoded CanFrame events out, plus system log entries.
    """

    RECENT_CAPACITY = 100

    def __init__(self, dbc_store: DbcStore) -> None:
        self.dbc_store = dbc_store
        self.recent_frames: deque[CanFrame] = deque(maxlen=self.RECENT_CAPACITY)
        self._link = None

        self.frame_decoded = Signal()  # CanFrame
        self.log_entry = Signal()  # LogEntry
        self.connected = Signal()
        self.disconnected = Signal()  # str reason

    def attach(self, link) -> None:
        self.detach()
        self._link = link
        link.frame_received.connect(self._on_frame)
        link.parse_error.connect(self._on_parse_error)
        link.connection_lost.connect(self._on_connection_lost)
        link.connected.connect(self._on_connected)

    def detach(self) -> None:
        if self._link is not None:
            try:
                self._link.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._link = None

    def _on_connected(self) -> None:
        self.log_entry.emit(LogEntry.now("INFO", "CAN Interface Connected"))
        self.connected.emit()

    def _on_connection_lost(self, reason: str) -> None:
        self.log_entry.emit(LogEntry.now("ERROR", f"Connection lost: {reason}"))
        self.disconnected.emit(reason)

    def _on_parse_error(self, message: str) -> None:
        self.log_entry.emit(LogEntry.now("WARN", f"Packet parse error: {message}"))

    def _on_frame(self, parsed: ParsedFrame) -> None:
        if parsed.mld == MLD_BAUDRATE_ACK:
            self.log_entry.emit(LogEntry.now("INFO", "Baudrate ack received"))
            return
        if parsed.mld != MLD_CAN_FRAME:
            self.log_entry.emit(LogEntry.now("WARN", f"Unknown mld={parsed.mld}"))
            return

        decoded = self.dbc_store.decode(parsed.can_id, parsed.payload)
        if decoded is None:
            decoded = CanFrame(
                timestamp=time.time(),
                can_id=parsed.can_id,
                source=Source.UNKNOWN,
                message_name="UNKNOWN",
                dlc=parsed.dlc,
                payload=parsed.payload,
                signals={},
            )

        self.recent_frames.append(decoded)
        self.frame_decoded.emit(decoded)
