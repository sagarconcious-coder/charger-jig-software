from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import webview

from .core.can_bus import CanBus
from .core.config_auth import ConfigAuth
from .core.dbc_store import DbcLoadError, DbcStore
from .core.logging_store import list_serial_ports
from .core.models import LogEntry
from .core.packet import MLD_CAN_FRAME
from .core.report_export import export_csv, export_pdf
from .core.serial_link import SerialLink
from .core.server_client import (
    ServerClientError,
    ServerConfig,
    ServerSession,
    create_lot as _create_lot,
    generate_serial as _generate_serial,
    get_lot_options as _get_lot_options,
    list_lots as _list_lots,
    submit_charger_report as _submit_charger_report,
)
from .core.test_engine import TestEngine


def bundled_root() -> Path:
    """Read-only resource root: PyInstaller's extraction dir when frozen (recreated
    on every launch - never write here), else the repo root."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def writable_root() -> Path:
    """Root for anything the app needs to persist across restarts: the folder
    containing the .exe when frozen, else the repo root (same as bundled_root)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[1]


ROOT = bundled_root()
WRITABLE_ROOT = writable_root()
DEFAULT_JIG_DBC = ROOT / "can_jig_busmaster.dbc"
DEFAULT_DUT_DBC = ROOT / "EV Battery Charger CAN DBC v1.4.dbc"
DEFAULT_PROFILE_PATH = ROOT / "backend" / "config" / "test_profile.json"
PROFILE_PATH = WRITABLE_ROOT / "backend" / "config" / "test_profile.json"
SERVER_CONFIG_PATH = WRITABLE_ROOT / "backend" / "config" / "server_config.json"
CONFIG_AUTH_PATH = WRITABLE_ROOT / "backend" / "config" / "app_auth.json"
REPORTS_DIR = WRITABLE_ROOT / "reports"

# Calibration_Comm_OverCAN command bytes (see DBC comment on message 2432505162).
CALIBRATION_COMMANDS = {"Battery Voltage": ord("A"), "Battery Current": ord("B")}


def _ensure_writable_profile() -> None:
    """Copies the bundled default test profile to the writable location on first run."""
    if PROFILE_PATH.exists():
        return
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(DEFAULT_PROFILE_PATH.read_text())


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

        _ensure_writable_profile()
        self.can_bus = CanBus(self.dbc_store)
        self.test_engine = TestEngine(PROFILE_PATH)
        self.can_bus.frame_decoded.connect(self.test_engine.on_frame)

        self.server_config = ServerConfig(SERVER_CONFIG_PATH)
        self.server_session = ServerSession(self.server_config)
        self.config_auth = ConfigAuth(CONFIG_AUTH_PATH)

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
        self.can_bus.disconnected.connect(self._on_can_disconnected)

        self.test_engine.parameters_updated.connect(
            lambda params: self._push("parameters", [p.to_dict() for p in params])
        )
        self.test_engine.run_started.connect(lambda run: self._push("run_started", run.to_dict()))
        self.test_engine.run_stopped.connect(self._on_run_stopped)
        self.test_engine.run_locked.connect(lambda run: self._push("run_locked", run.to_dict()))
        self.test_engine.phase_changed.connect(lambda phase: self._push("phase", {"phase": phase}))

    def _on_can_disconnected(self, reason: str) -> None:
        self._push("connection", {"connected": False, "reason": reason})
        # An unexpected link drop (cable pulled, serial error) needs the same
        # stale-data cleanup as the explicit Disconnect button.
        self.test_engine.reset_live_data()

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
        ok, error = self._link.connect_to(port, baudrate)

        if not ok:
            self.can_bus.detach()
            self._link = None
            self._connected_port = "--"
            self._connected_baud = "--"
            return {"ok": False, "error": error or f"Failed to open {port}"}

        self._connected_port = port
        self._connected_baud = f"{baudrate // 1000} kbps" if baudrate >= 1000 else str(baudrate)
        return {"ok": True, "port": self._connected_port, "baudrate": self._connected_baud}

    def disconnect(self) -> dict:
        self.can_bus.detach()
        self._link = None
        self._connected_port = "--"
        self._connected_baud = "--"
        # Clear cached CAN signals and live measured/expected values so the
        # comparison table doesn't keep showing readings from before the link
        # dropped (they'd otherwise sit stale until new frames arrive).
        self.test_engine.reset_live_data()
        return {"ok": True}

    def get_connection_info(self) -> dict:
        connected = self._link is not None and self._link.is_connected
        return {"port": self._connected_port, "baudrate": self._connected_baud, "connected": connected}

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

    def set_compare(self, active: bool) -> list[dict]:
        params = self.test_engine.set_compare(active)
        return [p.to_dict() for p in params]

    def lock_test(self) -> dict | None:
        run = self.test_engine.lock()
        return run.to_dict() if run else None

    # ---- Calibration ---------------------------------------------
    def send_calibration(self, param_name: str, run_dict: dict | None = None) -> dict:
        """CR-03/4.3: sends the Calibration_Comm_OverCAN command for Battery
        Voltage/Current, using the current measured value. Refuses if the
        parameter isn't currently within tolerance (guards against a
        hidden/ineligible control being triggered via stale UI state)."""
        command = CALIBRATION_COMMANDS.get(param_name)
        if command is None:
            return {"ok": False, "error": f"'{param_name}' is not calibratable"}

        if not self.test_engine.is_calibration_eligible(param_name):
            return {"ok": False, "error": f"{param_name} is not within tolerance"}

        param = next((p for p in self.test_engine.parameters if p.name == param_name), None)
        if param is None or param.measured_value is None:
            return {"ok": False, "error": f"No measured value for {param_name}"}

        if self._link is None or not self._link.is_connected:
            return {"ok": False, "error": "Not connected to the JIG"}

        dut_db = self.dbc_store.dut_db
        if dut_db is None:
            return {"ok": False, "error": "DUT DBC not loaded"}

        try:
            message = dut_db.get_message_by_name("Calibration_Comm_OverCAN")
            payload = message.encode({"Comm_Char": command, "Actual_Value": param.measured_value})
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Failed to encode calibration frame: {exc}"}

        self._link.write_frame(MLD_CAN_FRAME, message.frame_id, payload)
        return {"ok": True, "value": param.measured_value}

    # ---- Configuration password (4.8) ---------------------------------------------
    def verify_config_password(self, password: str) -> dict:
        return {"ok": self.config_auth.verify(password)}

    def change_config_password(self, old_password: str, new_password: str) -> dict:
        if not self.config_auth.verify(old_password):
            return {"ok": False, "error": "Current password is incorrect"}
        self.config_auth.set_password(new_password)
        return {"ok": True}

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
            jig_firmware_version=run_dict.get("jig_firmware_version", "--"),
            jig_hardware_version=run_dict.get("jig_hardware_version", "--"),
            locked=run_dict.get("locked", False),
            charger_part_number=run_dict.get("charger_part_number", ""),
            qr_values=run_dict.get("qr_values", {}),
            serial_number=run_dict.get("serial_number", ""),
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

    # ---- Server integration ---------------------------------------------
    def get_server_config(self) -> dict:
        return {"base_url": self.server_config.base_url, "email": self.server_config.email}

    def save_server_config(self, base_url: str, email: str = "", password: str = "") -> dict:
        # keep the existing password if the UI didn't resend one (e.g. left blank on edit)
        password = password or self.server_config.password
        self.server_config.save(base_url, email, password)
        self.server_session = ServerSession(self.server_config)
        return {"ok": True, "base_url": self.server_config.base_url, "email": self.server_config.email}

    def get_lot_options(self) -> dict:
        try:
            options = _get_lot_options(self.server_session)
            return {"ok": True, **options}
        except ServerClientError as exc:
            return {"ok": False, "error": str(exc)}

    def create_lot(self, codes: dict) -> dict:
        try:
            lot = _create_lot(self.server_session, codes)
            return {"ok": True, "lot": lot}
        except ServerClientError as exc:
            return {"ok": False, "error": str(exc)}

    def list_lots(self) -> dict:
        try:
            lots = _list_lots(self.server_session)
            return {"ok": True, "lots": lots}
        except ServerClientError as exc:
            return {"ok": False, "error": str(exc)}

    def generate_serial_number(self, lot_id) -> dict:
        try:
            result = _generate_serial(self.server_session, lot_id)
            return {"ok": True, **result}
        except ServerClientError as exc:
            return {"ok": False, "error": str(exc)}

    def submit_charger_report(self, lot_id, qr_values: dict, run_dict: dict) -> dict:
        """Report page's Generate Serial Number button (CR): submits the
        locked run to the server, which atomically mints the serial number
        and stores the report, then returns that same report back. The
        returned report (server's copy of record, serial included) is what
        gets auto-saved locally - never the pre-submit run_dict - so the
        local file always matches what the server actually persisted."""
        try:
            report = _submit_charger_report(self.server_session, lot_id, qr_values, run_dict)
        except ServerClientError as exc:
            return {"ok": False, "error": str(exc)}

        saved_path = self._save_report_locally(report)
        return {"ok": True, "report": report, "saved_path": saved_path}

    def _save_report_locally(self, report: dict) -> str | None:
        """Auto-saves the server's returned report as JSON under REPORTS_DIR,
        keyed by serial number - no dialog, so every generated report is
        guaranteed to land on disk without an extra click."""
        try:
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            serial = report.get("serial_number") or report.get("run_id") or "report"
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(serial))
            path = REPORTS_DIR / f"{safe_name}.json"
            path.write_text(json.dumps(report, indent=2, default=str))
            return str(path)
        except OSError as exc:
            print(f"Failed to save report locally: {exc}", file=sys.stderr)
            return None
