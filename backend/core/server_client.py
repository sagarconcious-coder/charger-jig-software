from __future__ import annotations

import json
from pathlib import Path

import requests

_DEFAULT_TIMEOUT = 8  # seconds

_NEXT_SERIAL_PATH = "/api/next-serial"
_TEST_SNAPSHOT_PATH = "/api/test-snapshot"
_CONFIRM_SERIAL_PATH = "/api/confirm-serial"
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
    return body.get("data") or {}


def _error_message(resp: requests.Response) -> str:
    try:
        return resp.json().get("message", resp.text)
    except ValueError:
        return resp.text


def get_next_serial(session: ServerSession) -> str:
    data = session.request("GET", _NEXT_SERIAL_PATH)
    serial = data.get("serialNumber") or data.get("serial_number")
    if not serial:
        raise ServerClientError("Server response missing 'serialNumber'")
    return serial


def send_snapshot(session: ServerSession, snapshot: dict) -> dict:
    return session.request("POST", _TEST_SNAPSHOT_PATH, json_body=snapshot)


def confirm_serial(session: ServerSession, serial_number: str) -> dict:
    """Tells the server the snapshot for this serial was saved successfully,
    so the server can commit/assign the serial instead of leaving it reserved."""
    return session.request("POST", _CONFIRM_SERIAL_PATH, json_body={"serial_number": serial_number})
