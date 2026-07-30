from __future__ import annotations

import time
from pathlib import Path

import cantools
from cantools.database import Database

from .models import CanFrame, Source


class DbcLoadError(Exception):
    pass


class DbcStore:
    """Holds the JIG and DUT DBC databases and decodes incoming CAN frames.

    Source attribution is purely by which database's frame-ID set the
    incoming CAN ID belongs to. The two DBC files are expected to have
    non-overlapping IDs; a collision is reported via id_collisions.
    """

    def __init__(self) -> None:
        self.jig_db: Database | None = None
        self.dut_db: Database | None = None
        self.jig_path: Path | None = None
        self.dut_path: Path | None = None
        self.id_collisions: list[int] = []

    def load_jig(self, path: str | Path) -> None:
        self.jig_db = self._load(path)
        self.jig_path = Path(path)
        self._check_collisions()

    def load_dut(self, path: str | Path) -> None:
        self.dut_db = self._load(path)
        self.dut_path = Path(path)
        self._check_collisions()

    @staticmethod
    def _load(path: str | Path) -> Database:
        try:
            return cantools.database.load_file(str(path))
        except Exception as exc:  # noqa: BLE001 - surface any parse failure uniformly
            raise DbcLoadError(f"failed to load DBC '{path}': {exc}") from exc

    def _check_collisions(self) -> None:
        self.id_collisions = []
        if self.jig_db is None or self.dut_db is None:
            return
        jig_ids = {m.frame_id for m in self.jig_db.messages}
        dut_ids = {m.frame_id for m in self.dut_db.messages}
        self.id_collisions = sorted(jig_ids & dut_ids)

    def decode(self, can_id: int, payload: bytes) -> CanFrame | None:
        """Try JIG db first, then DUT db. Returns None if the ID is unknown to both."""
        for source, db in ((Source.JIG, self.jig_db), (Source.DUT, self.dut_db)):
            if db is None:
                continue
            try:
                message = db.get_message_by_frame_id(can_id)
            except KeyError:
                continue
            try:
                signals = message.decode(payload, allow_truncated=True)
            except Exception:  # noqa: BLE001
                signals = {}
            # keep only numeric-convertible values (drop NamedSignalValue objects as raw)
            clean_signals: dict[str, float] = {}
            for k, v in signals.items():
                try:
                    clean_signals[k] = float(v)
                except (TypeError, ValueError):
                    clean_signals[k] = float(getattr(v, "value", 0))
            return CanFrame(
                timestamp=time.time(),
                can_id=can_id,
                source=source,
                message_name=message.name,
                dlc=len(payload),
                payload=payload,
                signals=clean_signals,
            )
        return None

    @property
    def is_ready(self) -> bool:
        return self.jig_db is not None and self.dut_db is not None
