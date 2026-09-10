from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import requests

GITHUB_REPO = "sagarconcious-coder/charger-jig-software"
EXE_NAME = "ChargerTestingJIG.exe"

_DOWNLOAD_TIMEOUT = 30  # seconds, for the initial connection only (see stream loop below)


class UpdateError(Exception):
    pass


def get_latest_release() -> dict | None:
    """Full GitHub release JSON (tag_name + assets), or None on failure."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def get_latest_version() -> str | None:
    """Return the latest release tag from GitHub (e.g. 'v1.0.0'), or None on failure."""
    release = get_latest_release()
    return release.get("tag_name") if release else None


def is_newer(remote_version: str, local_version: str) -> bool:
    """Compare two version strings like '1.2.0', stripping a leading 'v' if present."""
    def parse(v: str) -> tuple[int, ...]:
        v = v.lstrip("vV")
        return tuple(int(part) for part in v.split("."))

    return parse(remote_version) > parse(local_version)


def _find_exe_asset_url(release: dict) -> str | None:
    """Pick out the .exe asset's direct download URL from a release's asset list."""
    for asset in release.get("assets", []):
        if asset.get("name") == EXE_NAME:
            return asset.get("browser_download_url")
    return None


def download_update(release: dict, dest_dir: Path) -> Path:
    """Stream the release's .exe asset to dest_dir, returning the downloaded path.

    Streamed (not requests.get(...).content) so a ~50MB exe doesn't sit
    entirely in memory at once. Raises UpdateError on any failure - callers
    treat a failed download as "no update available right now", never fatal.
    """
    url = _find_exe_asset_url(release)
    if not url:
        raise UpdateError(f"Release {release.get('tag_name')} has no {EXE_NAME} asset")

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{EXE_NAME}.new"

    try:
        with requests.get(url, stream=True, timeout=_DOWNLOAD_TIMEOUT) as response:
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    f.write(chunk)
    except requests.RequestException as exc:
        dest_path.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc}") from exc

    return dest_path


def apply_update_and_relaunch(new_exe_path: Path, current_exe_path: Path, window) -> None:
    """Replace current_exe_path with new_exe_path and relaunch.

    A running .exe can't overwrite itself (Windows keeps it locked while it's
    executing) - so this writes a tiny batch script and hands off to it, then
    closes the pywebview window so the app shuts down through its normal exit
    path (this fires window.events.closing -> Api.shutdown, same as the user
    clicking the close button).

    PyInstaller's --onefile build actually runs as TWO processes: a launcher
    that unpacks itself into a temp dir and holds the .exe file handle, and a
    child that runs this Python code (os.getpid() only ever sees the child).
    So instead of tracking a specific PID to wait for, the script just
    RETRIES the move every second - it succeeds the moment whichever process
    is holding the file finally lets go, regardless of which one that was.
    30 retries gives both processes a generous 30s to fully exit.

    PyInstaller 6.22.1+ added a bootloader security check (CVE-2025-59042):
    a launched onefile exe that still has _MEIPASS2/_PYI_* env vars lying
    around from a just-exited process treats itself as a "child" process and
    verifies its parent is a copy of itself - which fails here because the
    relaunch's real OS parent is cmd.exe, not another ChargerTestingJIG.exe,
    producing "Security validation failure: failed to obtain executable path
    for parent process!". Clearing those vars with `set NAME=` (an empty
    assignment - cmd's way of unsetting a variable) before `start` makes
    Windows not pass them down to the new process at all, so the bootloader
    sees a clean top-level launch and skips that check entirely.
    """
    script_path = Path(tempfile.gettempdir()) / "charger_jig_update.bat"
    script_path.write_text(
        "@echo off\r\n"
        "setlocal enabledelayedexpansion\r\n"
        "set attempts=0\r\n"
        ":retry\r\n"
        f"move /Y \"{new_exe_path}\" \"{current_exe_path}\" >NUL 2>&1\r\n"
        "if not errorlevel 1 goto done\r\n"
        "set /a attempts+=1\r\n"
        "if !attempts! GEQ 30 goto done\r\n"
        "timeout /t 1 /nobreak >NUL\r\n"
        "goto retry\r\n"
        ":done\r\n"
        "set _MEIPASS2=\r\n"
        "set _PYI_ONEFILE_TEMP_TIMESTAMP=\r\n"
        "set _PYI_ARCHIVE_FILE=\r\n"
        "set _PYI_PARENT_PROCESS_LEVEL=\r\n"
        # Belt-and-suspenders: also clear any other PyInstaller-internal var
        # we didn't name above by exact name - `set VAR=` unsets VAR, and
        # this loop runs that for every currently-set _PYI*/_MEI* name.
        "for /f \"tokens=1 delims==\" %%v in ('set _PYI 2^>NUL') do set %%v=\r\n"
        "for /f \"tokens=1 delims==\" %%v in ('set _MEI 2^>NUL') do set %%v=\r\n"
        f"start \"\" \"{current_exe_path}\"\r\n"
        "del \"%~f0\"\r\n"
    )

    subprocess.Popen(
        ["cmd.exe", "/c", str(script_path)],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    window.destroy()
