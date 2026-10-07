"""Small helpers that describe the machine / USB port for app.log, so a field
log from another laptop says enough on its own to diagnose "data stopped"
reports (which laptop, which USB port, on battery or mains) without having
to ask the operator afterwards."""
from __future__ import annotations

import ctypes
import platform
import sys


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


def power_source() -> str:
    """'mains', 'battery 73%' or 'unknown'. Whether the laptop's own charger
    is plugged in changes how bench noise couples into the USB cable (the
    battery-powered JIG's only ground reference is the laptop), so it's
    logged alongside every connect/stall."""
    if sys.platform != "win32":
        return "unknown"
    try:
        status = _SystemPowerStatus()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"
    if status.ACLineStatus == 1:
        return "mains"
    if status.ACLineStatus == 0:
        pct = status.BatteryLifePercent
        return f"battery {pct}%" if pct != 255 else "battery"
    return "unknown"


def port_details(port: str) -> str:
    """Windows' description of a COM port: driver name, USB VID:PID and the
    physical USB location (which socket / hub it's plugged into)."""
    try:
        import serial.tools.list_ports

        for p in serial.tools.list_ports.comports():
            if p.device == port:
                return f"{p.description} [{p.hwid}]"
    except Exception:  # noqa: BLE001
        pass
    return "not listed by Windows"


def port_present(port: str) -> bool | None:
    """True/False whether Windows currently lists the port, None if unknown."""
    try:
        import serial.tools.list_ports

        return any(p.device == port for p in serial.tools.list_ports.comports())
    except Exception:  # noqa: BLE001
        return None


def system_summary() -> str:
    return f"{platform.platform()}, python {platform.python_version()}, power={power_source()}"
