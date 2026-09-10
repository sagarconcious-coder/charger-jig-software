from __future__ import annotations

import json
import queue
import sys
import threading
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
from .core.updater import (
    UpdateError,
    apply_update_and_relaunch,
    download_update,
    get_latest_release,
    is_newer,
)
from .__version__ import __version__


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
LAST_LOT_PATH = WRITABLE_ROOT / "backend" / "config" / "last_lot.json"
REPORTS_DIR = WRITABLE_ROOT / "reports"

# Calibration_Comm_OverCAN command bytes (see DBC comment on message 2432505162).
CALIBRATION_COMMANDS = {"Battery Voltage": ord("A"), "Battery Current": ord("B")}


def _ensure_writable_profile() -> None:
    """Copies the bundled default test profile to the writable location on first
    run, and re-syncs it on later app updates too - but only while the writable
    copy is untouched since the last sync. A stamp file records the hash of the
    bundled default that was last copied in; if the writable copy still matches
    that stamp, it's safe to overwrite with a newer bundled default (e.g. a
    signal_name/measured_signal_name fix shipped in this build). If the writable
    copy's hash no longer matches the stamp, the user edited it via the app's
    own Configuration page (update_parameters() persists there) - leave it alone
    so an upgrade can never silently discard real calibration/tolerance changes.
    """
    import hashlib

    stamp_path = PROFILE_PATH.with_suffix(".json.synced-hash")
    default_text = DEFAULT_PROFILE_PATH.read_text()
    default_hash = hashlib.sha256(default_text.encode("utf-8")).hexdigest()

    if not PROFILE_PATH.exists():
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_PATH.write_text(default_text)
        stamp_path.write_text(default_hash)
        return

    current_text = PROFILE_PATH.read_text()
    if current_text == default_text:
        stamp_path.write_text(default_hash)  # already in sync; keep stamp current
        return

    last_synced_hash = stamp_path.read_text().strip() if stamp_path.exists() else None
    current_hash = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
    if last_synced_hash is not None and current_hash == last_synced_hash:
        # Writable copy is stock (from a previous build), and the bundled
        # default has since changed - refresh it to pick up the new defaults.
        PROFILE_PATH.write_text(default_text)
        stamp_path.write_text(default_hash)
    # else: writable copy has local edits (or no stamp to compare against,
    # e.g. upgrading from a build predating this mechanism) - leave it as-is.


def _load_last_lot() -> dict:
    """Reads the last-selected lot (id + display label) persisted on this
    machine, so the Report page can default to it on every new report
    instead of forcing a re-selection each time. Survives app restarts and
    updates since it lives next to the .exe under WRITABLE_ROOT, same as
    server_config.json / app_auth.json."""
    if not LAST_LOT_PATH.exists():
        return {}
    try:
        return json.loads(LAST_LOT_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_last_lot(lot_id, label: str = "") -> None:
    LAST_LOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_LOT_PATH.write_text(json.dumps({"lot_id": lot_id, "label": label}, indent=2))


def _js(payload) -> str:
    """Safely serialize a Python value for embedding in a JS call."""
    return json.dumps(payload, default=str)


class UiPump:
    """Runs every webview.evaluate_js() push on a single dedicated thread,
    decoupled from whatever thread produced the event.

    pywebview's evaluate_js() is synchronous: it blocks the calling thread on
    a semaphore until the JS side round-trips a result back into Python (see
    webview/window.py's evaluate_js). CAN frames arrive on SerialWorker's
    background read thread (see serial_link.py) at up to hundreds of Hz -
    calling evaluate_js directly from there would mean the serial *read loop*
    itself stalls on the UI/renderer every time the page is busy, backing up
    the OS serial buffer and making the whole app hang or drop frames under
    real bus load. Producers just call enqueue(); this pump drains the queue
    on its own thread at a fixed tick, batching same-tick events into a
    single evaluate_js call so a burst of frames costs one round-trip instead
    of one per frame.
    """

    TICK_SECONDS = 0.05  # 20 Hz UI refresh - fast enough to feel live, slow enough to batch bursts
    MAX_QUEUE = 20_000  # backpressure valve; see _drain_once's overflow handling

    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=self.MAX_QUEUE)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._dropped = 0

    def set_window(self, window: webview.Window) -> None:
        self._window = window

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="UiPump", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def enqueue(self, event: str, data) -> None:
        """Safe to call from any thread, including the serial reader thread.
        Never blocks on the UI: if the queue is full (pump can't keep up, or
        the window is gone), the oldest-in-line event is dropped rather than
        stalling the caller - a dropped log/frame push is far cheaper than a
        stalled CAN read loop."""
        try:
            self._queue.put_nowait((event, data))
        except queue.Full:
            self._dropped += 1
            try:
                self._queue.get_nowait()  # make room by dropping the oldest
                self._queue.put_nowait((event, data))
            except queue.Empty:
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            self._drain_once()
            self._stop.wait(self.TICK_SECONDS)
        self._drain_once()  # flush anything left on shutdown, best-effort

    def _drain_once(self) -> None:
        if self._window is None:
            # Nothing can be delivered yet; avoid growing unbounded before
            # set_window() is called during startup.
            return

        batch: list[tuple[str, object]] = []
        while True:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break

        if not batch:
            return

        # One evaluate_js call for the whole batch: cheaper than one round
        # trip per event, and the JS-side dispatcher just runs them in order.
        calls = "".join(
            f"window.__onBackendEvent({_js(event)}, {_js(data)});" for event, data in batch
        )
        try:
            self._window.evaluate_js(calls)
        except Exception:  # noqa: BLE001 - window may be closing/gone
            pass


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
        self._ui_pump = UiPump()
        self._ui_pump.start()

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

        self._pending_update: dict | None = None  # set once a newer .exe has been downloaded

        self._wire_events()
        self._start_update_check()

    def set_window(self, window: webview.Window) -> None:
        self._window = window
        self._ui_pump.set_window(window)

    def shutdown(self) -> None:
        """Called from window.events.closing so the serial port is actually
        released and the pump thread stops instead of both being left to the
        mercy of daemon-thread process teardown (which, for the serial port
        specifically, isn't guaranteed to run pyserial's close() promptly)."""
        self.can_bus.detach()
        self._link = None
        self._ui_pump.stop()

    # ---- Self-update -----------------------------------------------------
    def _start_update_check(self) -> None:
        """Only meaningful for the packaged .exe - running from source has no
        exe for GitHub's release asset to replace, and no stable pid/relaunch
        target either. Runs on a daemon thread so a slow/offline GitHub call
        never delays window startup."""
        if not getattr(sys, "frozen", False):
            return
        threading.Thread(target=self._check_and_download_update, daemon=True).start()

    def _check_and_download_update(self) -> None:
        release = get_latest_release()
        if not release:
            return  # offline, rate-limited, or GitHub unreachable - silently skip
        latest_tag = release.get("tag_name", "")
        if not latest_tag or not is_newer(latest_tag, __version__):
            return

        try:
            new_exe = download_update(release, dest_dir=WRITABLE_ROOT)
        except UpdateError as exc:
            print(f"Update download failed: {exc}", file=sys.stderr)
            return

        self._pending_update = {"path": str(new_exe), "version": latest_tag}
        self._push("update_ready", {"version": latest_tag, "current": __version__})

    def apply_update(self) -> dict:
        """Called from the frontend's 'Restart now' button. Hands off to a
        detached helper script and exits this process - see
        apply_update_and_relaunch's docstring for why a running exe can't
        just overwrite itself directly."""
        if not self._pending_update:
            return {"ok": False, "error": "No update has been downloaded"}
        new_exe = Path(self._pending_update["path"])
        current_exe = Path(sys.executable)
        apply_update_and_relaunch(new_exe, current_exe)
        return {"ok": True}  # unreachable - apply_update_and_relaunch calls sys.exit(0)

    # ---- Python -> JS push ---------------------------------------------
    def _push(self, event: str, data) -> None:
        # Never touches evaluate_js directly - just hands off to UiPump's
        # queue, so this is safe (and non-blocking) to call from the serial
        # reader thread via CanBus/TestEngine's Signal callbacks. See
        # UiPump's docstring for why that separation matters.
        self._ui_pump.enqueue(event, data)

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
        Voltage/Current, using the JIG's live (trusted-reference) reading as
        Actual_Value - that's the whole point of calibration: teach the
        charger's own sensor to match the JIG's true measurement. Sending the
        DUT's own measured_value back to itself would be circular and either
        no-op or reinforce its existing drift. Refuses if the parameter isn't
        currently within tolerance (guards against a hidden/ineligible
        control being triggered via stale UI state)."""
        command = CALIBRATION_COMMANDS.get(param_name)
        if command is None:
            return {"ok": False, "error": f"'{param_name}' is not calibratable"}

        if not self.test_engine.is_calibration_eligible(param_name):
            return {"ok": False, "error": f"{param_name} is not within tolerance"}

        param = next((p for p in self.test_engine.parameters if p.name == param_name), None)
        if param is None or param.expected_value is None:
            return {"ok": False, "error": f"No JIG reference value for {param_name}"}

        if self._link is None or not self._link.is_connected:
            return {"ok": False, "error": "Not connected to the JIG"}

        dut_db = self.dbc_store.dut_db
        if dut_db is None:
            return {"ok": False, "error": "DUT DBC not loaded"}

        try:
            message = dut_db.get_message_by_name("Calibration_Comm_OverCAN")
            payload = bytearray(
                message.encode({"Comm_Char": command, "Actual_Value": param.expected_value})
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Failed to encode calibration frame: {exc}"}

        # Firmware quirk: the DBC marks Actual_Value (bytes 1-2) as big-endian,
        # but the charger's calibration parser actually reads those two bytes
        # little-endian - confirmed on hardware (48.2V/0x12D4 was being read
        # back as ~542.9V/0xD412). Swap them post-encode rather than changing
        # the DBC's byte-order annotation, since every other big-endian signal
        # in this file decodes correctly as-is (e.g. ACMains, BatteryVoltage).
        payload[1], payload[2] = payload[2], payload[1]
        payload = bytes(payload)

        # Logged both to stderr (visible when run from source) and to the
        # app's own log panel (visible in the built .exe, which has no
        # console attached) so the exact outgoing packet can always be
        # inspected without extra tooling.
        log_line = (
            f"Calibration sent - {param_name}: Comm_Char={chr(command)!r} (0x{command:02X}) "
            f"Actual_Value={param.expected_value} "
            f"frame_id=0x{message.frame_id:X} payload={payload.hex(' ').upper()}"
        )
        print(log_line, file=sys.stderr)
        self.can_bus.log_entry.emit(LogEntry.now("INFO", log_line))

        self._link.write_frame(MLD_CAN_FRAME, message.frame_id, payload)
        return {"ok": True, "value": param.expected_value}

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
            dut_firmware_version=run_dict.get("dut_firmware_version", "--"),
            dut_hardware_version=run_dict.get("dut_hardware_version", "--"),
            locked=run_dict.get("locked", False),
            charger_part_number=run_dict.get("charger_part_number", ""),
            model_no=run_dict.get("model_no", ""),
            ambient_temperature=run_dict.get("ambient_temperature", "--"),
            qr_values=run_dict.get("qr_values", {}),
            serial_number=run_dict.get("serial_number", ""),
            report_id=run_dict.get("report_id", ""),
        )

        # Date-prefixed so a plain filename listing (Explorer, `ls`, ...)
        # sorts chronologically without opening each file. Falls back to
        # run_id if saved before a serial number has been generated.
        date_str = time.strftime("%Y-%m-%d", time.localtime(run.start_time))
        ident = run.serial_number or run.run_id
        default_name = f"charger_test_report_{date_str}_{ident}.{fmt}"
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
            result = _list_lots(self.server_session)
            return {"ok": True, **result}
        except ServerClientError as exc:
            return {"ok": False, "error": str(exc)}

    def get_last_lot(self) -> dict:
        """The lot last selected on the Report page, persisted on this
        machine - lets the page default to it instead of forcing a
        re-selection on every new report."""
        return {"ok": True, **_load_last_lot()}

    def set_last_lot(self, lot_id, label: str = "") -> dict:
        _save_last_lot(lot_id, label)
        return {"ok": True}

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
