from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .events import Signal
from .models import CanFrame, Source, TestParameter, TestRun

# Signals expressed in mV in the JIG dbc but compared in V by the profile.
_MILLI_SIGNALS = {"batt_voltage_mv", "batt_curr_sense_mv"}
# Signals expressed as a 0-100 percentage in the dbc but compared as a 0-1 fraction by the profile.
_PERCENT_SIGNALS = {"ac_power_factor_pct"}


class TestEngine:
    def __init__(self, profile_path: str | Path) -> None:
        self._profile_path = Path(profile_path)
        self.phases: list[str] = []
        self.parameters: list[TestParameter] = []
        self._latest_signals: dict[Source, dict[str, float]] = {Source.JIG: {}, Source.DUT: {}}
        self.current_run: TestRun | None = None
        self._load_profile()

        self.parameters_updated = Signal()  # list[TestParameter]
        self.run_started = Signal()  # TestRun
        self.run_stopped = Signal()  # TestRun
        self.phase_changed = Signal()  # str

    def _load_profile(self) -> None:
        data = json.loads(self._profile_path.read_text())
        self.phases = data.get("phases", [])
        self.parameters = []
        for p in data.get("parameters", []):
            self.parameters.append(
                TestParameter(
                    name=p["name"],
                    unit=p["unit"],
                    expected_value=p["expected_value"],
                    tolerance=p["tolerance"],
                    source=Source(p["source"]),
                    signal_name=p["signal_name"],
                    measured_source=Source(p["measured_source"]),
                    measured_signal_name=p["measured_signal_name"],
                )
            )

    def on_frame(self, frame: CanFrame) -> None:
        if frame.source not in (Source.JIG, Source.DUT):
            return
        self._latest_signals[frame.source].update(frame.signals)
        self._recompute()

    def _value_for(self, source: Source, signal_name: str) -> float | None:
        val = self._latest_signals.get(source, {}).get(signal_name)
        if val is None:
            return None
        if signal_name in _MILLI_SIGNALS:
            val = val / 1000.0
        elif signal_name in _PERCENT_SIGNALS:
            val = val / 100.0
        return val

    def _recompute(self) -> None:
        for param in self.parameters:
            param.measured_value = self._value_for(param.measured_source, param.measured_signal_name)
            param.evaluate()
        self.parameters_updated.emit(self.parameters)

    def update_parameters(self, updates: list[dict]) -> list[TestParameter]:
        """Applies {name, expected_value, tolerance} updates and persists them to disk."""
        by_name = {u["name"]: u for u in updates}
        for param in self.parameters:
            update = by_name.get(param.name)
            if update is None:
                continue
            param.expected_value = update["expected_value"]
            param.tolerance = update["tolerance"]
            param.evaluate()

        data = json.loads(self._profile_path.read_text())
        for p in data.get("parameters", []):
            update = by_name.get(p["name"])
            if update is None:
                continue
            p["expected_value"] = update["expected_value"]
            p["tolerance"] = update["tolerance"]
        self._profile_path.write_text(json.dumps(data, indent=2))

        self.parameters_updated.emit(self.parameters)
        return self.parameters

    def start_run(self) -> TestRun:
        self.current_run = TestRun(run_id=str(uuid.uuid4())[:8], start_time=time.time(), phase=self.phases[0] if self.phases else "")
        self.run_started.emit(self.current_run)
        if self.phases:
            self.phase_changed.emit(self.phases[0])
        return self.current_run

    def stop_run(self) -> TestRun | None:
        if self.current_run is None:
            return None
        self.current_run.end_time = time.time()
        self.current_run.parameters = [
            TestParameter(**{**p.__dict__}) for p in self.parameters
        ]
        finished = self.current_run
        self.run_stopped.emit(finished)
        self.current_run = None
        return finished

    @property
    def is_running(self) -> bool:
        return self.current_run is not None
