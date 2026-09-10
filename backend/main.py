from __future__ import annotations

import sys
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.bridge import Api, bundled_root

FRONTEND_DIR = bundled_root() / "frontend"
FRONTEND_INDEX = FRONTEND_DIR / "index.html"

DEV_MODE = "--dev" in sys.argv


def _start_dev_reloader(window) -> None:
    """Watch frontend/ and reload the webview window on any file change."""
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class ReloadHandler(FileSystemEventHandler):
        def on_any_event(self, event) -> None:
            if event.is_directory:
                return
            window.evaluate_js("location.reload()")

    observer = Observer()
    observer.schedule(ReloadHandler(), str(FRONTEND_DIR), recursive=True)
    observer.daemon = True
    observer.start()


def main() -> None:
    api = Api()
    window = webview.create_window(
        "Charger Testing JIG — CAN Monitor & Test System",
        str(FRONTEND_INDEX),
        js_api=api,
        width=1536,
        height=1024,
        min_size=(1100, 700),
        background_color="#0B1220",
    )
    api.set_window(window)
    window.events.closing += api.shutdown
    if DEV_MODE:
        window.events.loaded += lambda: _start_dev_reloader(window)
    webview.start(debug=DEV_MODE)


if __name__ == "__main__":
    main()
