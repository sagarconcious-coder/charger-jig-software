from __future__ import annotations

import sys
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.bridge import Api, bundled_root

FRONTEND_INDEX = bundled_root() / "frontend" / "index.html"


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
    webview.start(debug=False)


if __name__ == "__main__":
    main()
