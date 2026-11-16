"""SUMO lifecycle and one-second sampling for the RL environment."""

import math
import shutil
import sys
import uuid
from pathlib import Path

import traci

from .metrics import InvalidRun, TrafficMetrics
from .scenario import LANES, read_settings, validate_settings
from .signal import SignalController


class FourPhaseRuntime:
    def __init__(self, case_folder, *, settings=None, connection=None, tripinfo=None, sample_sink=None, error_log=None,
                 route_file_override=None, max_drain_seconds=0):
        """`connection` is normally None (SUMO is started here); tests may inject a fake TraCI connection."""
        self.case_folder = Path(case_folder).resolve()
        self.settings = dict(settings or read_settings())
        validate_settings(self.settings)
        self.route_file = Path(route_file_override).resolve() if route_file_override else self.case_folder / "demand.rou.xml"
        if type(max_drain_seconds) is not int or max_drain_seconds < 0 or max_drain_seconds % 15:
            raise ValueError("Drain limit must be a nonnegative multiple of 15 seconds")
        self.max_drain_seconds = max_drain_seconds
        self.draining = False
        self.connection = connection
        self.owns_connection = connection is None
        self.sample_sink = sample_sink
        self.tripinfo = str(Path(tripinfo).resolve()) if tripinfo else None
        self.error_log = str(Path(error_log).resolve()) if error_log else None
        if not self.owns_connection and (tripinfo or error_log):
            raise ValueError("Output paths cannot be passed to an injected connection")
        self.sumo_config = (str(self.case_folder / "run.sumocfg") if self.owns_connection
                            else connection.simulation.getOption("configuration-file"))
        self.label = f"fourphase_{uuid.uuid4().hex}"
        self.controller = self.metrics = None
        self.ready = False

    def reset(self, seed):
        self.ready = False
        self.draining = False
        if not self.route_file.is_file():
            raise FileNotFoundError(f"Build the fourphase scenario first: {self.route_file}")
        if type(seed) is not int or not 0 <= seed < 2**31:
            raise ValueError("SUMO seed must be an integer in [0, 2**31)")
        arguments = ["-c", self.sumo_config, "--seed", str(seed), "--begin", "0", "--step-length", "1",
                     "--route-steps", "0", "--max-depart-delay", "-1", "--time-to-teleport", "-1",
                     "--collision.action", "warn", "--collision.check-junctions", "true",
                     "--no-step-log", "true", "--duration-log.disable", "true"]
        if self.max_drain_seconds:
            arguments += ["--route-files", str(self.route_file), "--end",
                          str(self.settings["duration_seconds"] + self.max_drain_seconds)]
        if self.tripinfo:
            Path(self.tripinfo).parent.mkdir(parents=True, exist_ok=True)
            arguments += ["--tripinfo-output", self.tripinfo, "--tripinfo-output.write-unfinished", "true"]
        if self.error_log:
            arguments += ["--error-log", self.error_log]
        if not self.owns_connection:
            arguments += ["--start"]
        if self.connection is None:
            candidate = Path(sys.executable).parent / "sumo"
            binary = str(candidate) if candidate.is_file() else shutil.which("sumo")
            if not binary:
                raise FileNotFoundError("SUMO is missing from the project environment")
            traci.start([binary, *arguments], label=self.label, doSwitch=False, numRetries=2)
            self.connection = traci.getConnection(self.label)
        else:
            self.connection.load(arguments)
        if not math.isclose(self.connection.simulation.getDeltaT(), 1) or not math.isclose(self.connection.simulation.getTime(), 0):
            raise ValueError("Expected a reset to time 0 with 1-second SUMO steps")
        self.controller = SignalController(self.connection, self.settings)
        vehicle_space = self.settings["vehicle_length_m"] + self.settings["vehicle_min_gap_m"]
        self.capacities = {lane: max(1.0, self.connection.lane.getLength(lane) / vehicle_space) for lane in LANES}
        self.metrics = TrafficMetrics(self.route_file, self.settings["duration_seconds"])
        self.seed = seed
        self.ready = True

    @property
    def now(self):
        return self.connection.simulation.getTime()

    def queues(self):
        """차로별 정지 차량 수 (SUMO: 0.1 m/s 미만)."""
        return {lane: self.connection.lane.getLastStepHaltingNumber(lane) for lane in LANES}

    def moving(self):
        """차로별 주행 차량 수: SUMO 전체 차량 수에서 정지(0.1 m/s 미만) 차량 수를 뺀 값."""
        lane = self.connection.lane
        return {name: lane.getLastStepVehicleNumber(name) - lane.getLastStepHaltingNumber(name) for name in LANES}

    def advance_second(self):
        if not self.ready:
            raise RuntimeError("Reset the runtime before advancing")
        previous = self.now
        if previous >= self.settings["duration_seconds"] and not self.draining:
            raise RuntimeError("Observation window ended; reset before advancing again")
        if self.draining and previous >= self.settings["duration_seconds"] + self.max_drain_seconds:
            raise InvalidRun({"reason": "ATT_cohort_did_not_finish_before_drain_limit", "time_s": previous})
        try:
            self.controller.before_second()
            self.connection.simulationStep()
            if not math.isclose(self.now - previous, 1.0, abs_tol=1e-7):
                raise RuntimeError("SUMO did not advance exactly one second")
            self.controller.after_second()
            try:
                sample = self.metrics.collect(self.connection, self.controller, observation_window=not self.draining)
            except InvalidRun:
                if self.sample_sink is not None and self.metrics.last_sample is not None:
                    self.sample_sink(self.metrics.last_sample)
                raise
            if self.sample_sink is not None:
                self.sample_sink(sample)
            return sample
        except Exception:
            self.ready = False
            raise

    def start_drain(self):
        """Continue evaluation only; the original observation-window accounting stays frozen."""
        if not self.ready or not self.max_drain_seconds or self.now != self.settings["duration_seconds"]:
            raise RuntimeError("Drain must begin at the observation cutoff with a positive limit")
        if set(self.metrics.scheduled) != self.metrics.due:
            raise RuntimeError("Evaluation must exclude all departures scheduled at/after the cutoff")
        self.draining = True

    def summary(self, **kwargs):
        return self.metrics.summary(self.connection, controller=self.controller, **kwargs)

    def close(self):
        self.ready = False
        if self.owns_connection and self.connection is not None:
            try:
                self.connection.close()
            finally:
                self.connection = None
