from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Source(str, Enum):
    JIG = "JIG"
    DUT = "DUT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CanFrame:
    timestamp: float
    can_id: int
    source: Source
    message_name: str
    dlc: int
    payload: bytes
    signals: dict[str, float]

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "can_id": self.can_id,
            "can_id_hex": f"0x{self.can_id:03X}",
            "source": self.source.value,
            "message_name": self.message_name,
            "dlc": self.dlc,
            "payload_hex": self.payload.hex(" ").upper(),
            "signals": self.signals,
        }


class ParamStatus(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


@dataclass
class TestParameter:
    name: str
    unit: str
    expected_value: float
    tolerance: float
    source: Source
    signal_name: str
    measured_source: Source
    measured_signal_name: str
    measured_value: float | None = None
    status: ParamStatus = ParamStatus.PENDING
    # When True, expected_value tracks the live JIG signal (source/signal_name)
    # instead of the static value loaded from test_profile.json.
    live_expected: bool = False
    # When set, measured_value is the max of these signal names (all read from
    # measured_source) instead of the single measured_signal_name lookup -
    # e.g. Temperature 1's Measured = max(DUT Temperature2, DUT TemperatureIn).
    measured_max_of: list[str] = field(default_factory=list)

    @property
    def deviation_value(self) -> float | None:
        if self.measured_value is None:
            return None
        return self.measured_value - self.expected_value

    @property
    def deviation_pct(self) -> float | None:
        if self.measured_value is None or self.expected_value == 0:
            return None
        return (self.measured_value - self.expected_value) / self.expected_value * 100.0

    def evaluate(self) -> None:
        if self.measured_value is None:
            self.status = ParamStatus.PENDING
            return
        dev = abs(self.measured_value - self.expected_value)
        self.status = ParamStatus.PASS if dev <= self.tolerance else ParamStatus.FAIL

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "unit": self.unit,
            "expected_value": self.expected_value,
            "tolerance": self.tolerance,
            "measured_value": self.measured_value,
            "deviation_value": self.deviation_value,
            "deviation_pct": self.deviation_pct,
            "status": self.status.value,
        }


@dataclass
class TestRun:
    run_id: str
    start_time: float
    end_time: float | None = None
    phase: str = ""
    parameters: list[TestParameter] = field(default_factory=list)
    jig_firmware_version: str = "--"
    jig_hardware_version: str = "--"
    dut_firmware_version: str = "--"
    dut_hardware_version: str = "--"
    locked: bool = False
    charger_part_number: str = ""
    model_no: str = ""  # voltage_amp_code from the selected lot, e.g. "5825"/"7325"
    ambient_temperature: str = "--"  # JIG temp2_c (ADC_BROADCAST_TEMP1_TEMP2) at lock time
    qr_values: dict = field(default_factory=dict)
    serial_number: str = ""
    # Server-assigned sequential Report No. ("ADCCTJR000123"), set once the
    # report is submitted; falls back to run_id (see report_export.py) if a
    # CSV/PDF is exported before submission, since no server ID exists yet.
    report_id: str = ""

    @property
    def overall_pass(self) -> bool | None:
        if not self.parameters:
            return None
        if any(p.status == ParamStatus.PENDING for p in self.parameters):
            return None
        return all(p.status == ParamStatus.PASS for p in self.parameters)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "phase": self.phase,
            "overall_pass": self.overall_pass,
            "parameters": [p.to_dict() for p in self.parameters],
            "jig_firmware_version": self.jig_firmware_version,
            "jig_hardware_version": self.jig_hardware_version,
            "dut_firmware_version": self.dut_firmware_version,
            "dut_hardware_version": self.dut_hardware_version,
            "locked": self.locked,
            "charger_part_number": self.charger_part_number,
            "model_no": self.model_no,
            "ambient_temperature": self.ambient_temperature,
            "qr_values": self.qr_values,
            "serial_number": self.serial_number,
            "report_id": self.report_id,
        }


@dataclass(frozen=True)
class LogEntry:
    timestamp: float
    level: str  # INFO, RECV, WARN, ERROR
    message: str

    @staticmethod
    def now(level: str, message: str) -> "LogEntry":
        return LogEntry(timestamp=time.time(), level=level, message=message)

    def to_dict(self) -> dict:
        return {"timestamp": self.timestamp, "level": self.level, "message": self.message}
