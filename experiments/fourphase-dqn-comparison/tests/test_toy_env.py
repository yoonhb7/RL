"""Check MDP semantics using a fake TraCI connection, without starting SUMO."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from gymnasium.error import ResetNeeded

from src.envs.toy_console import ToyEnvSession
from src.envs.toy_env import ToyTrafficEnv
from src.traffic.safety_controller import DIRECTIONS, EXPECTED_STATES


ROOT = Path(__file__).resolve().parents[1]


class ToySumo:
    """A clock and six-phase signal; traffic counts are supplied by each test."""
    DURATIONS = (30, 3, 1, 30, 3, 1)

    def __init__(self, queues=None):
        self.time, self.phase_index, self.phase_started, self.switch_at = 0.0, 0, 0.0, 30.0
        self.queues = queues or (lambda time: 1)
        self.collisions = 0
        self.internal_queue = 0
        self.loads = []
        self.switches = []
        self.close_calls = 0
        self.simulation = SimpleNamespace(
            getTime=lambda: self.time, getDeltaT=lambda: 1.0,
            getOption=lambda name: {"configuration-file": "/Users/k2/rl-term-project/toy/toy.sumocfg", "seed": "42"}[name],
            getDepartedNumber=lambda: 0, getArrivedNumber=lambda: 0,
            getCollidingVehiclesNumber=lambda: self.collisions, getStartingTeleportNumber=lambda: 0,
            getPendingVehicles=lambda: (),
        )
        self.trafficlight = SimpleNamespace(
            getIDList=lambda: ("center",),
            getControlledLinks=lambda tls: tuple(((f"{d}_in_0", "out_0", "via_0"),) for d in DIRECTIONS),
            getProgram=lambda tls: "fixed",
            getAllProgramLogics=lambda tls: (SimpleNamespace(programID="fixed", phases=tuple(
                SimpleNamespace(state=state, duration=duration)
                for state, duration in zip(EXPECTED_STATES, self.DURATIONS)
            )),),
            getPhase=lambda tls: self.phase_index,
            getSpentDuration=lambda tls: self.time - self.phase_started,
            getRedYellowGreenState=lambda tls: EXPECTED_STATES[self.phase_index],
            setPhase=self.set_phase, setPhaseDuration=self.set_remaining,
        )
        self.lane = SimpleNamespace(
            getIDList=lambda: tuple(f"{d}_in_0" for d in DIRECTIONS) + (":center_0_0",),
            getLength=lambda lane: 150.0,
            getLastStepHaltingNumber=self.halting,
            getLastStepVehicleNumber=lambda lane: 5 if lane == "north_in_0" else 0,
        )
        self.vehicle = SimpleNamespace(getIDCount=lambda: 5)

    def halting(self, lane):
        if lane == ":center_0_0":
            return self.internal_queue
        return self.queues(self.time) if lane == "north_in_0" and self.time else 0

    def set_phase(self, tls, phase):
        self.phase_index = phase
        self.phase_started = self.time
        self.switch_at = self.time + self.DURATIONS[phase]
        self.switches.append((self.time, phase))

    def set_remaining(self, tls, seconds):
        self.switch_at = self.time + seconds

    def simulationStep(self):
        if self.time >= self.switch_at:
            self.set_phase("center", (self.phase_index + 1) % 6)
        self.time += 1

    def load(self, arguments):
        self.loads.append(arguments)
        self.time, self.phase_index, self.phase_started, self.switch_at = 0.0, 0, 0.0, 30.0
        self.switches.clear()

    def close(self, wait=True):
        self.close_calls += 1


class ToyTrafficEnvTests(unittest.TestCase):
    def make_env(self, connection=None, **overrides):
        connection = connection or ToySumo()
        settings = {"warmup_seconds": 0, "duration_seconds": 100, **overrides}
        env = ToyTrafficEnv(connection=connection, settings=settings)
        self.addCleanup(env.close)
        return env, connection

    def test_reset_returns_normalized_state_and_mac_reload_path(self):
        env, connection = self.make_env()
        observation, info = env.reset(seed=7)
        self.assertEqual(observation.shape, (16,))
        self.assertEqual(observation.dtype, np.float32)
        self.assertTrue(env.observation_space.contains(observation))
        self.assertEqual(list(observation[:6]), [1, 0, 0, 0, 0, 0])
        self.assertEqual(observation[-1], 1)
        self.assertEqual(info["sumo_seed"], 7)
        self.assertEqual(connection.loads[0][:4], ["-c", "/Users/k2/rl-term-project/toy/toy.sumocfg", "--seed", "7"])
        self.assertIn("--start", connection.loads[0])

    def test_minimum_green_rejects_request_then_preserves_clearance(self):
        env, connection = self.make_env()
        env.reset(seed=42)
        for _ in range(2):
            _, _, _, _, info = env.step(1)
            self.assertFalse(info["action"]["accepted"])
            self.assertEqual(info["action"]["reason"], "min_green")
        _, _, _, _, info = env.step(1)
        self.assertTrue(info["action"]["accepted"])
        self.assertEqual(connection.switches[:3], [(10.0, 1), (13.0, 2), (14.0, 3)])
        self.assertEqual(info["raw_observation"]["phase_index"], 3)

    def test_maximum_green_is_enforced_inside_a_decision_interval(self):
        env, connection = self.make_env(max_green_seconds=12)
        env.reset(seed=42)
        env.step(0)
        env.step(0)
        _, _, _, _, info = env.step(0)
        self.assertIn((12.0, 1), connection.switches)
        self.assertEqual(info["forced_switches"], 1)

    def test_hold_overrides_native_30_second_switch(self):
        env, connection = self.make_env()
        env.reset(seed=42)
        for _ in range(7):
            env.step(0)
        self.assertEqual(connection.time, 35)
        self.assertEqual(connection.phase_index, 0)
        self.assertEqual(connection.switches, [])

    def test_fixed_mode_keeps_the_original_30_second_plan(self):
        connection = ToySumo()
        env = ToyTrafficEnv(connection=connection, control_mode="fixed", settings={"warmup_seconds": 0, "duration_seconds": 100})
        self.addCleanup(env.close)
        env.reset(seed=42)
        for _ in range(7):
            _, _, _, _, info = env.step(0)
        self.assertEqual(connection.phase_index, 3)
        self.assertEqual(info["action"]["reason"], "fixed_time")
        self.assertEqual(connection.switches[:3], [(30.0, 1), (33.0, 2), (34.0, 3)])

    def test_training_route_selection_is_seeded_and_reproducible(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        self.addCleanup(temporary.cleanup)
        paths = [Path(temporary.name) / f"routes_{index}.xml" for index in range(2)]
        for path in paths:
            path.write_text("<routes/>", encoding="utf-8")
        env = ToyTrafficEnv(route_files=paths, settings={"warmup_seconds": 0, "duration_seconds": 100})
        env.connection = ToySumo()  # Stand in for an owned local backend, without starting a process.
        self.addCleanup(env.close)
        _, first = env.reset(seed=42)
        _, second = env.reset(seed=42)
        self.assertEqual(first["route_file"], second["route_file"])
        self.assertIn("--route-files", env.connection.loads[-1])

    def test_reward_integrates_all_five_seconds_including_clearance(self):
        values = [2, 3, 4, 2, 1]
        env, connection = self.make_env(ToySumo(queues=lambda time: values[int(time) - 1]))
        env.reset(seed=42)
        connection.set_phase("center", 1)
        _, reward, _, _, info = env.step(1)
        self.assertEqual(reward, -12)
        self.assertEqual(info["halted_vehicle_seconds"], 12)
        self.assertEqual(len(info["samples"]), 5)
        self.assertEqual(info["action"]["reason"], "clearance")

    def test_reward_includes_internal_lanes(self):
        env, connection = self.make_env()
        env.reset(seed=42)
        connection.internal_queue = 2
        _, reward, _, _, _ = env.step(0)
        self.assertEqual(reward, -15)  # One incoming + two internal halted vehicles, for five seconds.

    def test_warmup_is_fixed_plan_and_not_part_of_reward(self):
        env, connection = self.make_env(warmup_seconds=35)
        observation, info = env.reset(seed=42)
        self.assertEqual(info["raw_observation"]["time_s"], 35)
        self.assertEqual(info["raw_observation"]["phase_index"], 3)
        self.assertEqual(info["episode_return"], 0)
        self.assertEqual(observation[-1], 1)
        _, reward, _, _, info = env.step(0)
        self.assertEqual(reward, -5)
        self.assertEqual(info["episode_return"], -5)

    def test_final_partial_interval_is_terminal_and_does_not_overrun(self):
        env, connection = self.make_env(duration_seconds=12)
        env.reset(seed=42)
        env.step(0)
        env.step(0)
        observation, reward, terminated, truncated, info = env.step(0)
        self.assertEqual(connection.time, 12)
        self.assertEqual(info["interval_seconds"], 2)
        self.assertEqual(reward, -2)
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertEqual(observation[-1], 0)
        with self.assertRaises(ResetNeeded):
            env.step(0)
        self.assertEqual(connection.close_calls, 0)

    def test_reset_reproduces_state_and_does_not_close_borrowed_connection(self):
        env, connection = self.make_env()
        first, _ = env.reset(seed=42)
        env.step(0)
        second, info = env.reset(seed=42)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(info["decision_count"], 0)
        self.assertEqual(info["episode_return"], 0)
        env.close()
        self.assertEqual(connection.close_calls, 0)

    def test_invalid_actions_do_not_advance_simulation(self):
        env, connection = self.make_env()
        with self.assertRaises(ResetNeeded):
            env.step(0)
        env.reset(seed=42)
        for action in (2, -1, 0.5, True, np.bool_(True)):
            with self.subTest(action=action), self.assertRaises(ValueError):
                env.step(action)
        self.assertEqual(connection.time, 0)

    def test_collision_requires_reset(self):
        env, connection = self.make_env()
        env.reset(seed=42)
        connection.collisions = 1
        with self.assertRaises(RuntimeError):
            env.step(0)
        with self.assertRaises(ResetNeeded):
            env.step(0)

    def test_gui_observer_preserves_transitions_and_skips_warmup_frames(self):
        baseline, _ = self.make_env(warmup_seconds=12)
        visual, _ = self.make_env(warmup_seconds=12)
        events = []
        visual.observer = lambda event, env, **payload: events.append((event, payload))
        baseline.reset(seed=42)
        visual.reset(seed=42)
        self.assertEqual([event for event, _ in events], ["reset"])
        for action in (0, 1, 0, 1, 1):
            original = baseline.step(action)
            displayed = visual.step(action)
            np.testing.assert_array_equal(original[0], displayed[0])
            self.assertEqual(original[1:], displayed[1:])
        self.assertEqual(sum(event == "second" for event, _ in events), 25)
        self.assertEqual(sum(event == "action" for event, _ in events), 5)


class ToyConsoleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "controller.py"
        self.path.write_text("def choose_action(observation, info):\n    return 0\n", encoding="utf-8")
        self.connection = ToySumo()
        self.env = ToyTrafficEnv(connection=self.connection, settings={"warmup_seconds": 0, "duration_seconds": 10})
        self.addCleanup(self.env.close)
        self.events = []
        self.session = ToyEnvSession(self.env, self.path, emit=lambda message: None, record=self.events.append)

    def test_manual_action_logs_transition_and_waits(self):
        self.session.command("action 1")
        self.assertFalse(self.session.advancing)
        transition = self.events[-1]
        self.assertEqual(transition["event"], "transition")
        self.assertEqual(transition["action"], 1)
        self.assertEqual(transition["reward"], -5)
        self.assertEqual(transition["info"]["action"]["reason"], "min_green")
        self.assertEqual(self.connection.close_calls, 0)

    def test_reload_replaces_action_policy_without_reset(self):
        self.session.command("action 0")
        self.path.write_text("def choose_action(observation, info):\n    return 1\n", encoding="utf-8")
        self.session.command("reload")
        self.assertEqual(self.connection.time, 5)
        self.session.command("step")
        self.session.tick()
        self.assertEqual(self.events[-1]["action"], 1)
        self.assertTrue(self.session.done)
        self.assertFalse(self.session.advancing)
        self.assertEqual(self.connection.close_calls, 0)
        controller = self.session.controller
        self.session.command("reset")
        self.assertEqual(self.connection.time, 0)
        self.assertFalse(self.session.done)
        self.assertIs(self.session.controller, controller)

    def test_consecutive_manual_commands_each_advance_one_interval(self):
        self.session.command("action 0")
        self.session.command("action 1")
        self.assertEqual(self.connection.time, 10)
        transitions = [event for event in self.events if event["event"] == "transition"]
        self.assertEqual([event["action"] for event in transitions], [0, 1])

    def test_failed_reload_keeps_previous_policy(self):
        previous = self.session.controller
        self.path.write_text("def choose_action(:", encoding="utf-8")
        with self.assertRaises(SyntaxError):
            self.session.command("reload")
        self.assertIs(self.session.controller, previous)
        self.assertEqual(self.connection.close_calls, 0)


if __name__ == "__main__":
    unittest.main()
