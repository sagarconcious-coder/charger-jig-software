from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


class Signal:
    """Minimal stand-in for Qt's Signal: a list of callbacks, called in order.

    Replaces PySide6's QObject/Signal so core logic has no GUI framework
    dependency. Callbacks are plain Python callables (usually bridge methods
    that forward the payload to JS via webview.evaluate_js).
    """

    def __init__(self) -> None:
        self._listeners: list[Callable] = []

    def connect(self, fn: Callable) -> None:
        self._listeners.append(fn)

    def disconnect(self, fn: Callable | None = None) -> None:
        if fn is None:
            self._listeners.clear()
        elif fn in self._listeners:
            self._listeners.remove(fn)

    def emit(self, *args) -> None:
        # Each listener is isolated: emit() is frequently called from the
        # serial reader thread (see CanBus/_on_frame), so one misbehaving
        # listener raising must not prevent the remaining listeners - e.g. a
        # UI push listener throwing must never stop TestEngine.on_frame (or
        # vice versa) from running for that same frame.
        for fn in list(self._listeners):
            try:
                fn(*args)
            except Exception:  # noqa: BLE001
                logger.exception("Signal listener %r raised", fn)
