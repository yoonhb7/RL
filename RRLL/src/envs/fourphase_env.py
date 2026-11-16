"""21-observation continuing task, masked actions and external time-limit truncation."""

import gymnasium as gym
import numpy as np
from gymnasium import spaces
from gymnasium.error import ResetNeeded

from src.traffic.fourphase.runtime import FourPhaseRuntime
from src.traffic.fourphase.scenario import LANES, OBSERVATION_SIZE


class FourPhaseTrafficEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, case_folder, **runtime_kwargs):
        super().__init__()
        self.runtime = FourPhaseRuntime(case_folder, **runtime_kwargs)
        self.action_space = spaces.Discrete(2)
        self.observation_space = spaces.Box(
            low=np.zeros(OBSERVATION_SIZE, dtype=np.float32),
            high=np.asarray([np.inf] * (2 * len(LANES)) + [1.0] * 5, dtype=np.float32), dtype=np.float32,
        )
        self._needs_reset = True
        self.raw_return = 0.0
        self.decisions = 0
        self._pending_action = None
        self._action_seconds = self._action_stopped = 0

    @property
    def action_in_progress(self):
        return self._pending_action is not None

    def _observation(self):
        runtime, controller = self.runtime, self.runtime.controller
        if not controller.in_green:
            raise RuntimeError("Agent observation requested during a clearance phase")
        queues = runtime.queues()
        moving = runtime.moving()
        values = [queues[lane] / runtime.capacities[lane] for lane in LANES]
        values += [moving[lane] / runtime.capacities[lane] for lane in LANES]  # 주행 차량 밀도
        values += [float(p == controller.green) for p in range(4)]
        values += [controller.elapsed / runtime.settings["max_green_seconds"]]
        state = np.asarray(values, dtype=np.float32)  # Deliberately no clipping.
        if not np.isfinite(state).all() or not self.observation_space.contains(state) or sum(state[16:20]) != 1:
            raise RuntimeError(f"Invalid observation: {values}")
        info = {"time_s": runtime.now, "queues_raw": queues, "moving_raw": moving,
                "capacity_scales": runtime.capacities, "green_phase": controller.green,
                "green_elapsed_s": controller.elapsed, "tls_phase": controller.phase,
                "action_mask": np.asarray(controller.valid_actions(), dtype=bool),
                "sumo_seed": runtime.seed, "raw_reward_sum": self.raw_return, "decision_count": self.decisions}
        return state, info

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._needs_reset = True
        sumo_seed = int(seed) if seed is not None else int(self.np_random.integers(0, 2**31 - 1))
        self.runtime.reset(sumo_seed)
        self.raw_return, self.decisions = 0.0, 0
        self._pending_action = None
        self._action_seconds = self._action_stopped = 0
        self.action_space.seed(sumo_seed)
        state, info = self._observation()
        self._needs_reset = False
        return state, info

    def begin_action(self, action):
        """Start one decision; the viewer may pause between its physical seconds."""
        if self._needs_reset:
            raise ResetNeeded("reset() is required before the next action")
        if self.action_in_progress:
            raise RuntimeError("Finish the current 15-second decision before selecting another action")
        if isinstance(action, (bool, np.bool_)) or not self.action_space.contains(action):
            raise ValueError("Action must be integer 0 or 1")
        # Reject invalid actions before mutation; never record a requested hold
        # while silently executing a forced switch.
        self.runtime.controller.apply(int(action))
        self._pending_action = int(action)
        self._action_seconds = self._action_stopped = 0

    def advance_action_second(self):
        """Advance exactly one second; return a Gym transition only after 15."""
        if self._needs_reset or not self.action_in_progress:
            raise ResetNeeded("begin_action() is required before advancing an action")
        try:
            self._action_stopped += self.runtime.advance_second()["halting_incoming"]
            self._action_seconds += 1
            if self._action_seconds < 15:
                return None
            action, stopped = self._pending_action, self._action_stopped
            reward = -stopped / 15.0
            self.raw_return += reward
            self.decisions += 1
            self._pending_action = None
            state, info = self._observation()
        except Exception:
            self._needs_reset = True
            raise
        info.update(interval_seconds=15, interval_stop_vehicle_s=stopped, requested_action=action)
        truncated = self.runtime.now >= self.runtime.settings["duration_seconds"]
        if truncated:
            # The returned state and mask belong to the actual pre-reset traffic.
            self._needs_reset = True
            info["episode"] = self.runtime.summary(raw_return=self.raw_return, decisions=self.decisions)
        return state, reward, False, bool(truncated), info

    def step(self, action):
        """The training API still executes one complete, exactly 15-second action."""
        self.begin_action(action)
        for _ in range(15):
            transition = self.advance_action_second()
            if transition is not None:
                return transition
        raise RuntimeError("Missing transition at the end of a decision interval")

    def close(self):
        self._needs_reset = True
        self.runtime.close()
