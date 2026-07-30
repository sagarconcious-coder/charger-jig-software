from __future__ import annotations

from typing import Callable


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
        for fn in list(self._listeners):
            fn(*args)
