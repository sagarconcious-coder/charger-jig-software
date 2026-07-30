from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import webview

from .core.can_bus import CanBus
from .core.dbc_store import DbcLoadError, DbcStore
from .core.logging_store import list_serial_ports
from .core.models import LogEntry
from .core.report_export import export_csv, export_pdf
from .core.serial_link import SerialLink
from .core.test_engine import TestEngine


def bundled_root() -> Path:
    """Resource root: PyInstaller's extraction dir when frozen, else the repo root."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


ROOT = bundled_root()
DEFAULT_JIG_DBC = ROOT / "can_jig_busmaster.dbc"
DEFAULT_DUT_DBC = ROOT / "EV Battery Charger CAN DBC v1.4.dbc"
PROFILE_PATH = ROOT / "backend" / "config" / "test_profile.json"


def _js(payload) -> str:
    """Safely serialize a Python value for embedding in a JS call."""
    return json.dumps(payload, default=str)


class Api:
    """The single object exposed to JS as `window.pywebview.api`.

    Two directions of traffic:
      - JS -> Python: methods below, called as `pywebview.api.method_name(args)`,
        return plain JSON-serializable values (pywebview handles that automatically).
      - Python -> JS: `_push(event, data)` calls a JS-side dispatcher
        (`window.__onBackendEvent`) via evaluate_js, for anything that happens
        asynchronously (incoming CAN frames, connection state, test updates).
    """

    def __init__(self) -> None:
        self._window: webview.Window | None = None

        self.dbc_store = DbcStore()
        self._load_default_dbcs()

        self.can_bus = CanBus(self.dbc_store)
        self.test_engine = TestEngine(PROFILE_PATH)
        self.can_bus.frame_decoded.connect(self.test_engine.on_frame)

        self._link = None
        self._connected_port = "--"
        self._connected_baud = "--"

        self._wire_events()

    def set_window(self, window: webview.Window) -> None:
        self._window = window

    # ---- Python -> JS push ---------------------------------------------
    def _push(self, event: str, data) -> None:
        if self._window is None:
            return
        try:
            self._window.evaluate_js(f"window.__onBackendEvent({_js(event)}, {_js(data)})")
        except Exception:  # noqa: BLE001 - window may be closing
            pass

    def _wire_events(self) -> None:
        self.can_bus.frame_decoded.connect(lambda f: self._push("frame", f.to_dict()))
        self.can_bus.log_entry.connect(lambda e: self._push("log", e.to_dict()))
        self.can_bus.connected.connect(lambda: self._push("connection", {"connected": True}))
        self.can_bus.disconnected.connect(lambda reason: self._push("connection", {"connected": False, "reason": reason}))

        self.test_engine.parameters_updated.connect(
            lambda params: self._push("parameters", [p.to_dict() for p in params])
        )
        self.test_engine.run_started.connect(lambda run: self._push("run_started", run.to_dict()))
        self.test_engine.run_stopped.connect(self._on_run_stopped)
        self.test_engine.phase_changed.connect(lambda phase: self._push("phase", {"phase": phase}))

    def _on_run_stopped(self, run) -> None:
        run.parameters = [p for p in self.test_engine.parameters]
        self._push("run_stopped", run.to_dict())

    # ---- DBC ---------------------------------------------
    def _load_default_dbcs(self) -> None:
        try:
            if DEFAULT_JIG_DBC.exists():
                self.dbc_store.load_jig(DEFAULT_JIG_DBC)
            if DEFAULT_DUT_DBC.exists():
                self.dbc_store.load_dut(DEFAULT_DUT_DBC)
        except DbcLoadError as exc:
            print(f"DBC load warning: {exc}", file=sys.stderr)

    def get_dbc_status(self) -> dict:
        return {
            "jig_path": self.dbc_store.jig_path.name if self.dbc_store.jig_path else None,
            "dut_path": self.dbc_store.dut_path.name if self.dbc_store.dut_path else None,
            "is_ready": self.dbc_store.is_ready,
            "id_collisions": self.dbc_store.id_collisions,
            "jig_messages": self._message_summary(self.dbc_store.jig_db),
            "dut_messages": self._message_summary(self.dbc_store.dut_db),
        }

    @staticmethod
    def _message_summary(db) -> list[dict]:
        if db is None:
            return []
        out = []
        for m in db.messages:
            out.append({
                "name": m.name,
                "frame_id": m.frame_id,
                "frame_id_hex": f"0x{m.frame_id:03X}",
                "length": m.length,
                "signals": [s.name for s in m.signals],
            })
        return out

    # ---- Connection ---------------------------------------------
    def list_ports(self) -> list[str]:
        return list_serial_ports()

    def connect(self, port: str, baudrate: int) -> dict:
        if self._link is not None:
            self.can_bus.detach()
            self._link = None

        self._link = SerialLink()
        self.can_bus.attach(self._link)
        self._link.connect_to(port, baudrate)

        self._connected_port = port
        self._connected_baud = f"{baudrate // 1000} kbps" if baudrate >= 1000 else str(baudrate)
        return {"ok": True, "port": self._connected_port, "baudrate": self._connected_baud}

    def disconnect(self) -> dict:
        self.can_bus.detach()
        self._link = None
        self._connected_port = "--"
        self._connected_baud = "--"
        return {"ok": True}

    def get_connection_info(self) -> dict:
        return {"port": self._connected_port, "baudrate": self._connected_baud}

    # ---- Test engine ---------------------------------------------
    def start_test(self) -> dict:
        run = self.test_engine.start_run()
        return run.to_dict()

    def stop_test(self) -> dict | None:
        run = self.test_engine.stop_run()
        return run.to_dict() if run else None

    def get_parameters(self) -> list[dict]:
        return [p.to_dict() for p in self.test_engine.parameters]

    def update_parameters(self, updates: list[dict]) -> list[dict]:
        params = self.test_engine.update_parameters(updates)
        return [p.to_dict() for p in params]

    def get_phases(self) -> list[str]:
        return self.test_engine.phases

    def get_current_run(self) -> dict | None:
        run = self.test_engine.current_run
        if run is None:
            return None
        data = run.to_dict()
        data["elapsed"] = time.time() - run.start_time
        return data

    # ---- Recent frames (for pages that just opened and need backlog) ----
    def get_recent_frames(self, limit: int = 200) -> list[dict]:
        frames = list(self.can_bus.recent_frames)[-limit:]
        return [f.to_dict() for f in frames]

    # ---- Report export ---------------------------------------------
    def save_report(self, run_dict: dict, fmt: str) -> dict:
        from .core.models import ParamStatus, Source, TestParameter, TestRun

        params = [
            TestParameter(
                name=p["name"], unit=p["unit"], expected_value=p["expected_value"],
                tolerance=p["tolerance"], source=Source.JIG, signal_name="",
                measured_source=Source.JIG, measured_signal_name="",
                measured_value=p["measured_value"], status=ParamStatus(p["status"]),
            )
            for p in run_dict["parameters"]
        ]
        run = TestRun(
            run_id=run_dict["run_id"], start_time=run_dict["start_time"],
            end_time=run_dict.get("end_time"), phase=run_dict.get("phase", ""),
            parameters=params,
        )

        default_name = f"test_report_{run.run_id}.{fmt}"
        file_types = ("CSV Files (*.csv)",) if fmt == "csv" else ("PDF Files (*.pdf)",)
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG, save_filename=default_name, file_types=file_types
        )
        if not result:
            return {"ok": False, "error": "cancelled"}
        path = result if isinstance(result, str) else result[0]

        if fmt == "pdf":
            export_pdf(run, params, path)
        else:
            export_csv(run, params, path)
        return {"ok": True, "path": path}
