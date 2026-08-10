from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .events import Signal
from .models import CanFrame, ParamStatus, Source, TestParameter, TestRun

# NOTE: batt_voltage_mv / batt_curr_sense_mv are named as if raw-milli, but
# their DBC scale factor (0.001) is already applied by DbcStore.decode() via
# cantools - the value handed to on_frame() is already in V/A. Do not re-scale here.
# Signals expressed as a 0-100 percentage in the dbc but compared as a 0-1 fraction by the profile.
_PERCENT_SIGNALS = {"ac_power_factor_pct"}
# The JIG's battery-current sense reads 10x low against the actual current
# (hardware/scaling quirk on that channel) - correct it here to match the DUT.
_TIMES_TEN_SIGNALS = {"batt_curr_sense_mv"}


class TestEngine:
    def __init__(self, profile_path: str | Path) -> None:
        self._profile_path = Path(profile_path)
        self.phases: list[str] = []
        self.parameters: list[TestParameter] = []
        self._latest_signals: dict[Source, dict[str, float]] = {Source.JIG: {}, Source.DUT: {}}
        self.current_run: TestRun | None = None
        self.compare_active = False
        self._load_profile()

        self.parameters_updated = Signal()  # list[TestParameter]
        self.run_started = Signal()  # TestRun
        self.run_stopped = Signal()  # TestRun
        self.run_locked = Signal()  # TestRun
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
                    live_expected=p.get("live_expected", False),
                )
            )

    def on_frame(self, frame: CanFrame) -> None:
        if frame.source not in (Source.JIG, Source.DUT):
            return
        self._latest_signals[frame.source].update(frame.signals)
        # Once a run is locked, incoming CAN data must not change the result.
        if self.current_run is not None and self.current_run.locked:
            return
        if not self.compare_active:
            return
        self._recompute()

    def _value_for(self, source: Source, signal_name: str) -> float | None:
        val = self._latest_signals.get(source, {}).get(signal_name)
        if val is None:
            return None
        if signal_name in _PERCENT_SIGNALS:
            val = val / 100.0
        elif signal_name in _TIMES_TEN_SIGNALS:
            val = val * 10.0
        return val

    def _recompute(self) -> None:
        for param in self.parameters:
            if param.live_expected:
                live = self._value_for(param.source, param.signal_name)
                if live is not None:
                    param.expected_value = live
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
        self.compare_active = False
        for param in self.parameters:
            param.measured_value = None
            param.status = ParamStatus.PENDING
        self.current_run = TestRun(run_id=str(uuid.uuid4())[:8], start_time=time.time(), phase=self.phases[0] if self.phases else "")
        self.run_started.emit(self.current_run)
        if self.phases:
            self.phase_changed.emit(self.phases[0])
        self.parameters_updated.emit(self.parameters)
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
        self.compare_active = False
        return finished

    def set_compare(self, active: bool) -> list[TestParameter]:
        """Enables/disables continuous comparison (CR-04). Turning it off does not
        clear existing measured values/statuses - it only stops further updates,
        since a locked run also relies on this same gate in on_frame()."""
        self.compare_active = active
        if active:
            self._recompute()
        return self.parameters

    def lock(self) -> TestRun | None:
        """Finalizes the current comparison (CR-04/4.5). Any parameter still
        PENDING at lock time is forced to FAIL so a locked test can never
        silently read as an incomplete PASS."""
        if self.current_run is None:
            return None
        for param in self.parameters:
            if param.status == ParamStatus.PENDING:
                param.status = ParamStatus.FAIL

        self.compare_active = False
        self.current_run.locked = True
        self.current_run.parameters = [
            TestParameter(**{**p.__dict__}) for p in self.parameters
        ]
        self.parameters_updated.emit(self.parameters)
        self.run_locked.emit(self.current_run)
        return self.current_run

    def is_calibration_eligible(self, param_name: str) -> bool:
        """CR-03: a calibration control is only eligible while the named
        parameter's measured value is within its configured tolerance."""
        for param in self.parameters:
            if param.name == param_name:
                return param.status == ParamStatus.PASS
        return False

    @property
    def is_running(self) -> bool:
        return self.current_run is not None
