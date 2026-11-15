"""SUMO lifecycle and one-second sampling; borrowed Mac connections remain open."""

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
    def __init__(self, case_folder, *, settings=None, connection=None, mode="agent", tripinfo=None,
                 sample_sink=None, error_log=None, use_subscriptions=False):
        self.case_folder = Path(case_folder).resolve()
        self.settings = dict(settings or read_settings())
        validate_settings(self.settings)
        self.route_file = self.case_folder / "demand.rou.xml"
        self.connection = connection
        self.owns_connection = connection is None
        self.mode, self.sample_sink = mode, sample_sink
        self.tripinfo = str(Path(tripinfo).resolve()) if tripinfo else None
        self.error_log = str(Path(error_log).resolve()) if error_log else None
        if not self.owns_connection and (tripinfo or error_log):
            raise ValueError("Output paths on Linux cannot be passed to the borrowed Mac SUMO process")
        self.sumo_config = (str(self.case_folder / "run.sumocfg") if self.owns_connection
                            else connection.simulation.getOption("configuration-file"))
        self.label = f"fourphase_{uuid.uuid4().hex}"
        self.controller = self.metrics = None
        self.use_subscriptions = use_subscriptions
        self.snapshot = None
        self.ready = False

    def reset(self, seed):
        self.ready = False
        self.snapshot = None
        if not self.route_file.is_file():
            raise FileNotFoundError(f"Build the fourphase scenario first: {self.route_file}")
        if type(seed) is not int or not 0 <= seed < 2**31:
            raise ValueError("SUMO seed must be an integer in [0, 2**31)")
        arguments = ["-c", self.sumo_config, "--seed", str(seed), "--begin", "0", "--step-length", "1",
                     "--route-steps", "0", "--max-depart-delay", "-1", "--time-to-teleport", "-1",
                     "--collision.action", "warn", "--collision.check-junctions", "true",
                     "--no-step-log", "true", "--duration-log.disable", "true"]
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
        self.controller = SignalController(self.connection, self.settings, self.mode)
        vehicle_space = self.settings["vehicle_length_m"] + self.settings["vehicle_min_gap_m"]
        self.capacities = {lane: max(1.0, self.connection.lane.getLength(lane) / vehicle_space) for lane in LANES}
        self.metrics = TrafficMetrics(self.route_file, self.settings["duration_seconds"])
        if self.use_subscriptions:
            from .telemetry import TrafficSnapshot
            self.snapshot = TrafficSnapshot(self.connection)
        self.seed = seed
        self.ready = True

    @property
    def now(self):
        return self.snapshot.time if self.snapshot is not None else self.connection.simulation.getTime()

    def queues(self):
        if self.snapshot is not None:
            return {lane: self.snapshot.queues[lane] for lane in LANES}
        return {lane: self.connection.lane.getLastStepHaltingNumber(lane) for lane in LANES}

    def advance_second(self):
        if not self.ready:
            raise RuntimeError("Reset the runtime before advancing")
        previous = self.now
        if previous >= self.settings["duration_seconds"]:
            raise RuntimeError("Observation window ended; reset before advancing again")
        try:
            self.controller.before_second(self.snapshot)
            self.connection.simulationStep()
            if self.snapshot is not None:
                self.snapshot.refresh()
            if not math.isclose(self.now - previous, 1.0, abs_tol=1e-7):
                raise RuntimeError("SUMO did not advance exactly one second")
            self.controller.after_second(self.snapshot)
            try:
                sample = self.metrics.collect(self.connection, self.controller, self.snapshot)
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

    def summary(self, **kwargs):
        return self.metrics.summary(self.connection, controller=self.controller, **kwargs)

    def close(self):
        self.ready = False
        if self.owns_connection and self.connection is not None:
            try:
                self.connection.close()
            finally:
                self.connection = None
