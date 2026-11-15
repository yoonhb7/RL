"""One central Gymnasium agent controlling two straight-only intersections."""

import math
from pathlib import Path

import gymnasium as gym
import numpy as np
from gymnasium import spaces
from gymnasium.error import ResetNeeded

from src.envs.toy_env import ROOT, ToyTrafficEnv
from src.traffic.corridor import DIRECTIONS, INCOMING, SIGNALS, decode_action, read_settings
from src.traffic.safety_controller import SafetyController


class CorridorTrafficEnv(ToyTrafficEnv):
    """31 observations, Discrete(4) joint action; inherited backend ownership."""

    console_help = """action 0: A 유지 / B 유지
action 1: A 전환 / B 유지
action 2: A 유지 / B 전환
action 3: A 전환 / B 전환
step [N], resume, pause, reset, status, reload, delay 0.1, quit
view overview / view A / view B
colors fleet / colors waiting / colors speed
screenshot [Mac 절대 경로]
각 행동은 기본 5초. Ctrl+C는 연결을 유지하고 일시정지합니다."""

    def __init__(self, *, settings=None, sumo_config=None, **kwargs):
        settings = settings or read_settings()
        super().__init__(settings=settings, sumo_config=sumo_config or ROOT / "sumo/corridor2/corridor2.sumocfg", **kwargs)
        self.action_space = spaces.Discrete(4)
        self.observation_space = spaces.Box(low=0, high=1, shape=(31,), dtype=np.float32)
        self.controllers = {}

    def _observation(self):
        lights, lane = self.connection.trafficlight, self.connection.lane
        values, junctions = [], {}
        now = self.connection.simulation.getTime()
        for j in SIGNALS:
            phase, elapsed = lights.getPhase(j), lights.getSpentDuration(j)
            queues = {d: lane.getLastStepHaltingNumber(f"{edge}_0") for d, edge in zip(DIRECTIONS, INCOMING[j])}
            cars = {d: lane.getLastStepVehicleNumber(f"{edge}_0") for d, edge in zip(DIRECTIONS, INCOMING[j])}
            values.extend(float(index == phase) for index in range(6))
            values.append(elapsed / self.settings["max_green_seconds"])
            values.extend(queues[d] / self.capacities[j, d] for d in DIRECTIONS)
            values.extend(cars[d] / self.capacities[j, d] for d in DIRECTIONS)
            junctions[j] = {"phase_index": phase, "phase_elapsed_s": elapsed, "queues": queues,
                            "vehicles": cars, "signal_state": lights.getRedYellowGreenState(j)}
        values.append((self.horizon - now) / (self.horizon - self.warmup))
        raw = {"time_s": now, "junctions": junctions, "phase_index": {j: junctions[j]["phase_index"] for j in SIGNALS},
               "queues": {j: junctions[j]["queues"] for j in SIGNALS}}
        return np.clip(np.asarray(values, dtype=np.float32), 0, 1), raw

    def _info(self, raw, **kwargs):
        info = super()._info(raw, **kwargs)
        info["queue_hysteresis_vehicles"] = self.settings["queue_hysteresis_vehicles"]
        return info

    def reset(self, *, seed=None, options=None):
        gym.Env.reset(self, seed=seed)
        self._needs_reset, self._episode_done = True, False
        if self.route_files:
            self.route_file = self.route_files[int(self.np_random.integers(len(self.route_files)))]
            if not Path(self.route_file).is_file():
                raise FileNotFoundError(self.route_file)
        self.sumo_seed = int(seed) if seed is not None else int(self.np_random.integers(0, 2**31 - 1))
        if seed is not None:
            self.action_space.seed(seed)
        self._load_simulation(self.sumo_seed)
        if set(self.connection.trafficlight.getIDList()) != set(SIGNALS):
            raise ValueError("corridor2 네트워크에는 A와 B 신호등이 필요합니다")
        if not math.isclose(self.connection.simulation.getDeltaT(), 1):
            raise ValueError("Use a one-second SUMO step")
        self.controllers = {j: SafetyController(self.connection, self.settings["min_green_seconds"],
                            self.settings["max_green_seconds"], signal_id=j,
                            incoming_lanes=[f"{edge}_0" for edge in INCOMING[j]]) for j in SIGNALS}
        for j in SIGNALS:
            lights = self.connection.trafficlight
            plan = next(p for p in lights.getAllProgramLogics(j) if p.programID == lights.getProgram(j))
            if any(not self.settings["min_green_seconds"] <= plan.phases[i].duration <= self.settings["max_green_seconds"]
                   for i in (0, 3)):
                raise ValueError("Native fixed green lies outside the common safety constraints")
        self.all_lanes = tuple(self.connection.lane.getIDList())
        self.capacities = {(j, d): max(1, self.connection.lane.getLength(f"{edge}_0") / self.settings["vehicle_space_meters"])
                           for j in SIGNALS for d, edge in zip(DIRECTIONS, INCOMING[j])}
        self._departed = self._arrived = self._decisions = 0
        self._return = 0.0
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
            raise ResetNeeded("reset() before step()")
        if isinstance(action, (bool, np.bool_)) or not self.action_space.contains(action):
            raise ValueError("action은 정수 0–3이어야 합니다")
        bits = decode_action(int(action))
        before = sum(controller.forced_switches for controller in self.controllers.values())
        actions = {j: controller.apply_action(bit) if self.control_mode == "agent" else
                   {"requested": None, "accepted": False, "reason": "fixed_time", "forced": False}
                   for (j, controller), bit in zip(self.controllers.items(), bits)}
        if self.observer is not None:
            self.observer("action", self, action=int(action), result=actions)
        samples, integral = [], 0
        try:
            for _ in range(self.decision_interval):
                if self.connection.simulation.getTime() >= self.horizon:
                    break
                if self.control_mode == "agent":
                    for controller in self.controllers.values():
                        controller.before_step()
                self._advance_second()
                halted = sum(self.connection.lane.getLastStepHaltingNumber(lane) for lane in self.all_lanes)
                integral += halted
                sample = {"time_s": self.connection.simulation.getTime(), "halting_vehicles": halted}
                if self.record_signals:
                    for j in SIGNALS:
                        sample.update({f"{j}_phase_index": self.connection.trafficlight.getPhase(j),
                                       f"{j}_phase_elapsed_s": self.connection.trafficlight.getSpentDuration(j),
                                       f"{j}_signal_state": self.connection.trafficlight.getRedYellowGreenState(j)})
                samples.append(sample)
        except Exception:
            self._needs_reset = True
            raise
        reward = -float(integral)
        self._return += reward
        self._decisions += 1
        self._episode_done = self.connection.simulation.getTime() >= self.horizon
        observation, raw = self._observation()
        info = self._info(raw, action=actions, vehicle_seconds=integral, interval=len(samples), samples=samples,
                          forced_switches=sum(c.forced_switches for c in self.controllers.values()) - before)
        if self.observer is not None:
            self.observer("transition", self, reward=reward, info=info)
        return observation, reward, self._episode_done, False, info
