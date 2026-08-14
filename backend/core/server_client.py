from __future__ import annotations

import json
import re
from pathlib import Path

import requests

_DEFAULT_TIMEOUT = 8  # seconds

_LOT_OPTIONS_PATH = "/api/charger-lot-options"
_LOTS_PATH = "/api/charger-lots"
_SERIAL_PATH = "/api/charger-serial"
_REPORT_PATH = "/api/charger-report"
_LOGIN_PATH = "/bms/loginwithpassword"


class ServerClientError(Exception):
    pass


class ServerConfig:
    """Persists the server base URL + login credentials to a small JSON file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self.base_url: str = ""
        self.email: str = ""
        self.password: str = ""
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            data = json.loads(self._path.read_text())
            self.base_url = data.get("base_url", "")
            self.email = data.get("email", "")
            self.password = data.get("password", "")

    def save(self, base_url: str, email: str = "", password: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(
            {"base_url": self.base_url, "email": self.email, "password": self.password},
            indent=2,
        ))


class ServerSession:
    """Wraps a base URL + cached auth token, re-logging in on demand.

    The Django backend responds with an envelope: {"status", "message", "data"}
    with data keys in camelCase. This class handles login/token caching and
    unwraps that envelope so callers just get the inner `data` dict back.
    """

    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        self._token: str | None = None

    def _login(self) -> str:
        if not self._config.email or not self._config.password:
            raise ServerClientError("Server email/password is not configured")
        try:
            resp = requests.post(
                f"{self._config.base_url}{_LOGIN_PATH}",
                json={"email": self._config.email, "password": self._config.password},
                timeout=_DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ServerClientError(f"Login failed: {exc}") from exc

        data = _unwrap(resp)
        token = (data.get("auth") or {}).get("token")
        if not token:
            raise ServerClientError("Login response missing auth token")
        self._token = token
        return token

    def _headers(self) -> dict:
        if self._token is None:
            self._login()
        return {"Authorization": f"Bearer {self._token}"}

    def request(self, method: str, path: str, json_body: dict | None = None) -> dict:
        if not self._config.base_url:
            raise ServerClientError("Server URL is not configured")

        url = f"{self._config.base_url}{path}"
        for attempt in range(2):
            try:
                resp = requests.request(
                    method, url, json=json_body, headers=self._headers(), timeout=_DEFAULT_TIMEOUT,
                )
            except requests.RequestException as exc:
                raise ServerClientError(f"Request to {path} failed: {exc}") from exc

            if resp.status_code == 401 and attempt == 0:
                # token expired/invalid - force a fresh login and retry once
                self._token = None
                continue

            if not resp.ok:
                raise ServerClientError(f"{path} returned {resp.status_code}: {_error_message(resp)}")

            return _unwrap(resp)

        raise ServerClientError(f"Request to {path} failed after re-authenticating")


def _unwrap(resp: requests.Response) -> dict:
    try:
        body = resp.json()
    except ValueError:
        return {}
    return _camel_to_snake(body.get("data") or {})


def _camel_to_snake(value):
    """The Django backend camelCases every response key (see module docstring
    above); everything on this side - callers, the frontend's lot.js, etc. -
    is written snake_case, so convert recursively right at the unwrap seam."""
    if isinstance(value, dict):
        return {_camel_to_snake_key(k): _camel_to_snake(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_camel_to_snake(v) for v in value]
    return value


def _camel_to_snake_key(key: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()


def _error_message(resp: requests.Response) -> str:
    try:
        return resp.json().get("message", resp.text)
    except ValueError:
        return resp.text


def get_lot_options(session: ServerSession) -> dict:
    """Dropdown choice lists + today's default codes for the Lot page."""
    return session.request("GET", _LOT_OPTIONS_PATH)


def create_lot(session: ServerSession, codes: dict) -> dict:
    """codes: voltage_amp_code, variant_code, connector_code, ms_id_code,
    month_code, year_code. Returns the new lot record (id, lot_code, prefix, ...)."""
    return session.request("POST", _LOTS_PATH, json_body=codes)


def list_lots(session: ServerSession) -> list:
    """Existing lots for the Test Report page's lot dropdown."""
    data = session.request("GET", _LOTS_PATH)
    return data.get("lots") or []


def generate_serial(session: ServerSession, lot_id) -> dict:
    """Generates the next serial number for the given lot (its DB id, not
    the raw lot_code - lot_code alone is only unique within a month/year)."""
    return session.request("POST", _SERIAL_PATH, json_body={"lot_id": lot_id})


def submit_charger_report(session: ServerSession, lot_id, qr_values: dict, run: dict) -> dict:
    """Combined "generate serial + store report" call (CR: Report page's
    Generate Serial Number button). Atomically mints the next serial number
    for lot_id and stores the full locked run against it server-side.
    Returns the stored report, including the generated serial_number, so the
    caller never has to make a second round-trip to get it."""
    body = {
        "lot_id": lot_id,
        "qr_values": qr_values,
        "run_id": run.get("run_id", ""),
        "start_time": run.get("start_time"),
        "end_time": run.get("end_time"),
        "overall_result": run.get("overall_pass"),
        "jig_firmware_version": run.get("jig_firmware_version"),
        "jig_hardware_version": run.get("jig_hardware_version"),
        "parameters": run.get("parameters", []),
    }
    return session.request("POST", _REPORT_PATH, json_body=body)
