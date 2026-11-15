"""Finite-horizon toy traffic MDP, usable with Linux SUMO or a Mac connection."""

import json
import math
import shutil
import sys
import time
import uuid
from pathlib import Path

import gymnasium as gym
import numpy as np
import traci
from gymnasium import spaces
from gymnasium.error import ResetNeeded

from src.traffic.safety_controller import DIRECTIONS, SafetyController


ROOT = Path(__file__).resolve().parents[2]


def read_settings(overrides=None):
    settings = json.loads((ROOT / "configs" / "toy.json").read_text(encoding="utf-8"))
    settings.update(json.loads((ROOT / "configs" / "toy_env.json").read_text(encoding="utf-8")))
    settings.update(overrides or {})
    for name in ("duration_seconds", "warmup_seconds", "decision_interval_seconds", "min_green_seconds", "max_green_seconds"):
        value = settings[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value:
            raise ValueError(f"{name}은 정수 초 단위여야 합니다")
        settings[name] = int(value)
    if not 0 <= settings["warmup_seconds"] < settings["duration_seconds"]:
        raise ValueError("0 <= warmup < duration이어야 합니다")
    if settings["step_length_seconds"] != 1 or settings["decision_interval_seconds"] <= 0:
        raise ValueError("현재 환경은 1초 시뮬레이션 스텝과 양의 의사결정 간격을 사용합니다")
    if not 0 < settings["min_green_seconds"] <= settings["max_green_seconds"]:
        raise ValueError("0 < min_green <= max_green이어야 합니다")
    if not math.isfinite(settings["vehicle_space_meters"]) or settings["vehicle_space_meters"] <= 0:
        raise ValueError("vehicle_space_meters는 양수여야 합니다")
    return settings


class ToyTrafficEnv(gym.Env):
    """Actions: 0=hold, 1=request switch. Reset always reloads the same scenario.

    An injected connection is borrowed: close() never closes it. The owner (the
    Mac console) closes it only on quit. Without an injected connection, reset()
    starts a local headless SUMO process and close() owns its shutdown.
    """

    metadata = {"render_modes": []}

    def __init__(self, *, connection=None, sumo_config=None, remote_config=None, settings=None, wall_delay=0.0,
                 route_files=None, control_mode="agent", tripinfo_path=None, record_signals=False, observer=None):
        super().__init__()
        self.settings = read_settings(settings)
        self.horizon = self.settings["duration_seconds"]
        self.warmup = self.settings["warmup_seconds"]
        self.decision_interval = self.settings["decision_interval_seconds"]
        if not math.isfinite(wall_delay) or wall_delay < 0:
            raise ValueError("wall_delay는 유한한 0 이상의 값이어야 합니다")
        self.wall_delay = wall_delay
        self.connection = connection
        self.owns_connection = connection is None
        if control_mode not in ("agent", "fixed"):
            raise ValueError("control_mode must be agent or fixed")
        self.control_mode = control_mode
        self.route_files = tuple(str(Path(path).resolve()) for path in (route_files or ()))
        if self.route_files and not self.owns_connection:
            raise ValueError("수요 풀 전환은 Linux headless 실행에서 사용합니다")
        self.route_file = None
        self.tripinfo_path = str(Path(tripinfo_path).resolve()) if tripinfo_path else None
        if self.tripinfo_path and not self.owns_connection:
            raise ValueError("TripInfo 파일 수집은 Linux headless 평가에서 사용합니다")
        self.record_signals = record_signals
        # Optional GUI observer. Training/evaluation do not attach one.
        self.observer = observer
        self.sumo_config = str(sumo_config or ROOT / "sumo" / "toy" / "toy.sumocfg")
        if not self.owns_connection:
            self.sumo_config = remote_config or connection.simulation.getOption("configuration-file")
        if not self.sumo_config:
            raise ValueError("Mac에서 사용하는 .sumocfg 경로가 필요합니다")
        self.label = f"toy_{uuid.uuid4().hex}"
        self.action_space = spaces.Discrete(2)
        # 6 phase indicators + elapsed + 4 normalized queues + 4 densities + time remaining.
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(16,), dtype=np.float32)
        self.controller = None
        self._needs_reset = True
        self._episode_done = False
        self._departed = 0
        self._arrived = 0
        self._return = 0.0
        self._decisions = 0

    def _load_simulation(self, seed):
        arguments = [
            "-c", self.sumo_config, "--seed", str(seed), "--begin", "0", "--step-length", "1",
            "--route-steps", "0", "--time-to-teleport", "-1", "--collision.check-junctions", "true",
            "--no-step-log", "true", "--duration-log.disable", "true",
        ]
        if not self.owns_connection:
            arguments.append("--start")
        if self.route_file:
            arguments += ["--route-files", self.route_file]
        if self.tripinfo_path:
            Path(self.tripinfo_path).parent.mkdir(parents=True, exist_ok=True)
            arguments += ["--tripinfo-output", self.tripinfo_path, "--tripinfo-output.write-unfinished", "true"]
        if self.connection is None:
            if not Path(self.sumo_config).is_file():
                raise FileNotFoundError("toy.sumocfg를 찾지 못했습니다. scripts/build_toy.py를 먼저 실행하세요")
            executable = Path(sys.executable).parent / "sumo"
            binary = str(executable) if executable.is_file() else shutil.which("sumo")
            if not binary:
                raise FileNotFoundError("SUMO가 없습니다. requirements.txt를 설치하세요")
            traci.start([binary, *arguments], label=self.label, doSwitch=False, numRetries=2)
            self.connection = traci.getConnection(self.label)
        else:
            self.connection.load(arguments)

    def _advance_second(self, *, paced=True):
        previous_time = self.connection.simulation.getTime()
        self.connection.simulationStep()
        now = self.connection.simulation.getTime()
        if not math.isclose(now - previous_time, 1.0, abs_tol=1e-7):
            raise RuntimeError("SUMO가 정확히 1초 진행하지 않았습니다")
        simulation = self.connection.simulation
        self._departed += simulation.getDepartedNumber()
        self._arrived += simulation.getArrivedNumber()
        if simulation.getCollidingVehiclesNumber() or simulation.getStartingTeleportNumber():
            self._needs_reset = True
            raise RuntimeError("충돌 또는 텔레포트가 감지되었습니다. reset 후 설정을 확인하세요")
        if paced and self.observer is not None:
            self.observer("second", self, now=now)
        if paced and self.wall_delay:
            time.sleep(self.wall_delay)

    def _observation(self):
        lights, lane = self.connection.trafficlight, self.connection.lane
        phase = lights.getPhase("center")
        elapsed = lights.getSpentDuration("center")
        queues = {d: lane.getLastStepHaltingNumber(f"{d}_in_0") for d in DIRECTIONS}
        vehicles = {d: lane.getLastStepVehicleNumber(f"{d}_in_0") for d in DIRECTIONS}
        densities = {d: vehicles[d] / self.capacities[d] for d in DIRECTIONS}
        now = self.connection.simulation.getTime()
        phase_vector = [float(index == phase) for index in range(6)]
        values = [*phase_vector, elapsed / self.settings["max_green_seconds"]]
        values.extend(queues[d] / self.capacities[d] for d in DIRECTIONS)
        values.extend(densities[d] for d in DIRECTIONS)
        values.append((self.horizon - now) / (self.horizon - self.warmup))
        observation = np.clip(np.asarray(values, dtype=np.float32), 0.0, 1.0)
        raw = {
            "time_s": now, "phase_index": phase, "phase_elapsed_s": elapsed,
            "signal_state": lights.getRedYellowGreenState("center"),
            "queues": queues, "vehicles": vehicles, "densities": densities,
        }
        return observation, raw

    def _info(self, raw, *, action=None, vehicle_seconds=0.0, interval=0, samples=None, forced_switches=0):
        return {
            "raw_observation": raw, "sumo_seed": self.sumo_seed, "sumo_config": self.sumo_config,
            "route_file": self.route_file, "control_mode": self.control_mode,
            "action": action, "interval_seconds": interval,
            "halted_vehicle_seconds": float(vehicle_seconds), "samples": samples or [],
            "forced_switches": forced_switches,
            "vehicles_running": self.connection.vehicle.getIDCount(),
            "vehicles_pending": len(self.connection.simulation.getPendingVehicles()),
            "departed_total": self._departed, "arrived_total": self._arrived,
            "episode_return": self._return, "decision_count": self._decisions,
        }

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._needs_reset = True
        self._episode_done = False
        if self.route_files:
            index = int(self.np_random.integers(len(self.route_files)))
            self.route_file = self.route_files[index]
            if not Path(self.route_file).is_file():
                raise FileNotFoundError(self.route_file)
        self.sumo_seed = int(seed) if seed is not None else int(self.np_random.integers(0, 2**31 - 1))
        if seed is not None:
            self.action_space.seed(seed)
        self._load_simulation(self.sumo_seed)
        if not math.isclose(self.connection.simulation.getDeltaT(), 1.0):
            raise ValueError("SUMO step-length는 1초여야 합니다")
        self.controller = SafetyController(
            self.connection, self.settings["min_green_seconds"], self.settings["max_green_seconds"],
        )
        if self.control_mode == "fixed":
            lights = self.connection.trafficlight
            program = next(p for p in lights.getAllProgramLogics("center") if p.programID == lights.getProgram("center"))
            if any(not self.controller.min_green <= program.phases[index].duration <= self.controller.max_green for index in (0, 3)):
                raise ValueError("고정신호의 녹색시간이 비교 실험의 최소/최대 제약을 벗어났습니다")
        self.all_lanes = tuple(self.connection.lane.getIDList())
        self.capacities = {
            d: max(1.0, self.connection.lane.getLength(f"{d}_in_0") / self.settings["vehicle_space_meters"])
            for d in DIRECTIONS
        }
        self._departed = self._arrived = self._decisions = 0
        self._return = 0.0
        # Warm-up uses the native fixed plan, without collecting learning rewards.
        while self.connection.simulation.getTime() < self.warmup:
            self._advance_second(paced=False)
        self._needs_reset = False
        observation, raw = self._observation()
        info = self._info(raw)
        if self.observer is not None:
            self.observer("reset", self, info=info)
        return observation, info

    def step(self, action):
        if self._needs_reset or self._episode_done:
            raise ResetNeeded("step 전에 reset()이 필요합니다")
        if isinstance(action, (bool, np.bool_)) or not self.action_space.contains(action):
            raise ValueError("action은 정수 0(유지) 또는 1(전환 요청)이어야 합니다")
        forced_before = self.controller.forced_switches
        action_info = self.controller.apply_action(int(action)) if self.control_mode == "agent" else {
            "requested": None, "accepted": False, "reason": "fixed_time", "forced": False,
        }
        if self.observer is not None:
            self.observer("action", self, action=int(action), result=action_info)
        samples = []
        vehicle_seconds = 0.0
        try:
            for _ in range(self.decision_interval):
                if self.connection.simulation.getTime() >= self.horizon:
                    break
                if self.control_mode == "agent":
                    self.controller.before_step()
                self._advance_second()
                halted = sum(self.connection.lane.getLastStepHaltingNumber(lane) for lane in self.all_lanes)
                vehicle_seconds += halted  # dt=1 second, including yellow/all-red intervals.
                sample = {"time_s": self.connection.simulation.getTime(), "halting_vehicles": halted}
                if self.record_signals:
                    sample.update(phase_index=self.connection.trafficlight.getPhase("center"),
                                  phase_elapsed_s=self.connection.trafficlight.getSpentDuration("center"),
                                  signal_state=self.connection.trafficlight.getRedYellowGreenState("center"))
                samples.append(sample)
        except Exception:
            self._needs_reset = True
            raise
        reward = -float(vehicle_seconds)
        self._return += reward
        self._decisions += 1
        self._episode_done = self.connection.simulation.getTime() >= self.horizon
        observation, raw = self._observation()
        info = self._info(
            raw, action=action_info, vehicle_seconds=vehicle_seconds, interval=len(samples), samples=samples,
            forced_switches=self.controller.forced_switches - forced_before,
        )
        if self.observer is not None:
            self.observer("transition", self, reward=reward, info=info)
        # A fixed-horizon task: remaining time is included in the state, so this is
        # an MDP terminal state, not an external time-limit truncation.
        return observation, reward, bool(self._episode_done), False, info

    def close(self):
        self._needs_reset = True
        if self.owns_connection and self.connection is not None:
            try:
                self.connection.close()
            finally:
                self.connection = None
