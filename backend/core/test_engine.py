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
# ac_power_factor_pct is used as-is (DBC-scaled 0-100 percentage, no further
# scaling) so the comparison table's Expected column matches the JIG live tile.
# DUT PowerFactor is raw byte 7 of ACDCParameters_1; divide by 100 to match
# the JIG's power factor scale for comparison.
_PERCENT_SIGNALS: set[str] = {"PowerFactor"}
# The JIG's battery-current sense reads 10x low against the actual current
# (hardware/scaling quirk on that channel) - correct it here to match the DUT.
_TIMES_TEN_SIGNALS = {"batt_curr_sense_mv"}
_DIVIDE_TEN_SIGNALS: set[str] = set()


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
                    measured_max_of=p.get("measured_max_of", []),
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

    def _version_str(self, source: Source, signal_name: str) -> str:
        """firmware_version/hardware_version from JIG_DETAILS, or
        FirmwareVersion/HardwareVersion from the DUT's ChargerDetails,
        formatted to match the dashboard's live tile (1 decimal place);
        "--" if no such frame has arrived yet."""
        val = self._latest_signals.get(source, {}).get(signal_name)
        return f"{val:.1f}" if val is not None else "--"

    def _value_for(self, source: Source, signal_name: str) -> float | None:
        val = self._latest_signals.get(source, {}).get(signal_name)
        if val is None:
            return None
        if signal_name in _PERCENT_SIGNALS:
            val = val / 100.0
        elif signal_name in _TIMES_TEN_SIGNALS:
            val = val * 10.0
        elif signal_name in _DIVIDE_TEN_SIGNALS:
            val = val / 10.0
        return val

    def _recompute(self) -> None:
        for param in self.parameters:
            if param.live_expected:
                live = self._value_for(param.source, param.signal_name)
                if live is not None:
                    param.expected_value = live

            if param.measured_max_of:
                values = [
                    v for v in (
                        self._value_for(param.measured_source, name)
                        for name in param.measured_max_of
                    )
                    if v is not None
                ]
                param.measured_value = max(values) if values else None
            else:
                param.measured_value = self._value_for(param.measured_source, param.measured_signal_name)

            param.evaluate()
        self.parameters_updated.emit(self.parameters)

    def reset_live_data(self) -> list[TestParameter]:
        """Clears cached CAN signals and live measured/expected values so a
        disconnect doesn't leave the comparison table showing stale readings
        from before the link dropped."""
        self._latest_signals = {Source.JIG: {}, Source.DUT: {}}
        for param in self.parameters:
            param.measured_value = None
            if param.live_expected:
                param.expected_value = None
            param.status = ParamStatus.PENDING
        self.parameters_updated.emit(self.parameters)
        return self.parameters

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
        # The JIG never sends an explicit "test stopped" signal in practice,
        # so end_time normally stays None all the way to submission (see
        # stop_run() - the only other place that sets it). Lock is the real
        # "operator is done" moment, so stamp end_time here if stop_run()
        # hasn't already set one - never overwrite a real stop timestamp.
        if self.current_run.end_time is None:
            self.current_run.end_time = time.time()
        self.current_run.parameters = [
            TestParameter(**{**p.__dict__}) for p in self.parameters
        ]
        # JIG_DETAILS / ChargerDetails are both broadcast continuously, so the
        # latest cached reading is each side's version as of lock time - same
        # values the dashboard's firmware/hardware tiles show.
        self.current_run.jig_firmware_version = self._version_str(Source.JIG, "firmware_version")
        self.current_run.jig_hardware_version = self._version_str(Source.JIG, "hardware_version")
        self.current_run.dut_firmware_version = self._version_str(Source.DUT, "FirmwareVersion")
        self.current_run.dut_hardware_version = self._version_str(Source.DUT, "HardwareVersion")
        # Ambient Temperature (report section 3) - JIG's temp2_c from the same
        # ADC_BROADCAST_TEMP1_TEMP2 frame that feeds temp1_c (JIG's compared
        # "Temperature" parameter); temp2_c itself isn't used elsewhere.
        self.current_run.ambient_temperature = self._version_str(Source.JIG, "temp2_c")
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
