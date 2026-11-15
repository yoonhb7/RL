"""Offline joint-control checks. No SUMO process is launched by these tests."""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from gymnasium.error import ResetNeeded

from src.agents.corridor_evaluation import audit_corridor_signal, summarize_results
from src.envs.corridor_env import CorridorTrafficEnv
from src.envs.toy_console import ToyEnvSession
from src.traffic.corridor import INCOMING, ROUTES, SIGNALS, decode_action, prepare_cases, queue_action, read_settings, relative_cases, write_demand, write_network_inputs
from src.traffic.experiments import case_paths
from src.traffic.safety_controller import EXPECTED_STATES


class DualSumo:
    """Two independent clocks for signal phases, on ONE simulation clock."""

    durations = (30, 3, 1, 30, 3, 1)

    def __init__(self):
        self.close_calls = self.collisions = self.time = 0
        self.loads, self.switches = [], []
        self.reset_signals()
        self.simulation = SimpleNamespace(
            getTime=lambda: self.time, getDeltaT=lambda: 1,
            getOption=lambda name: "/Users/k2/rl-term-project/corridor2/corridor2.gui.sumocfg",
            getDepartedNumber=lambda: 0, getArrivedNumber=lambda: 0,
            getCollidingVehiclesNumber=lambda: self.collisions, getStartingTeleportNumber=lambda: 0,
            getPendingVehicles=lambda: (),
        )
        self.trafficlight = SimpleNamespace(
            getIDList=lambda: SIGNALS,
            getControlledLinks=lambda j: tuple(((f"{edge}_0", "out_0", "via_0"),) for edge in INCOMING[j]),
            getProgram=lambda j: "fixed",
            getAllProgramLogics=lambda j: (SimpleNamespace(programID="fixed", phases=tuple(
                SimpleNamespace(state=s, duration=d) for s, d in zip(EXPECTED_STATES, self.durations))),),
            getPhase=lambda j: self.signals[j][0],
            getSpentDuration=lambda j: self.time - self.signals[j][1],
            getRedYellowGreenState=lambda j: EXPECTED_STATES[self.signals[j][0]],
            setPhase=self.set_phase, setPhaseDuration=self.set_remaining,
        )
        self.lane = SimpleNamespace(
            getIDList=lambda: tuple(f"{edge}_0" for j in SIGNALS for edge in INCOMING[j]) + (":A_0_0",),
            getLength=lambda lane: 150,
            getLastStepHaltingNumber=lambda lane: {"west_in_0": 2, "A_to_B_0": 4, ":A_0_0": 3}.get(lane, 0),
            getLastStepVehicleNumber=lambda lane: 5,
        )
        self.vehicle = SimpleNamespace(getIDCount=lambda: 9)

    def reset_signals(self):
        self.signals = {j: [0, 0, 30] for j in SIGNALS}

    def set_phase(self, j, phase):
        self.signals[j] = [phase, self.time, self.time + self.durations[phase]]
        self.switches.append((j, self.time, phase))

    def set_remaining(self, j, duration):
        self.signals[j][2] = self.time + duration

    def simulationStep(self):
        for j in SIGNALS:
            if self.time >= self.signals[j][2]:
                self.set_phase(j, (self.signals[j][0] + 1) % 6)
        self.time += 1

    def load(self, arguments):
        self.loads.append(arguments)
        self.time = 0
        self.reset_signals()
        self.switches.clear()

    def close(self, wait=True):
        self.close_calls += 1


class CorridorEnvironmentTests(unittest.TestCase):
    def make_env(self, **overrides):
        connection = DualSumo()
        env = CorridorTrafficEnv(connection=connection, settings={**read_settings(), "warmup_seconds": 0,
                                 "duration_seconds": 100, **overrides}, record_signals=True)
        self.addCleanup(env.close)
        return env, connection

    def test_joint_bits_and_invalid_actions(self):
        self.assertEqual([decode_action(a) for a in range(4)], [(0, 0), (1, 0), (0, 1), (1, 1)])
        env, connection = self.make_env()
        env.reset(seed=42)
        for value in (-1, 4, True, np.bool_(True), 0.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                env.step(value)
        self.assertEqual(connection.time, 0)

    def test_joint_action_uses_one_shared_five_second_interval(self):
        env, connection = self.make_env()
        observation, _ = env.reset(seed=42)
        self.assertTrue(env.observation_space.contains(observation))
        self.assertEqual(observation.shape, (31,))
        self.assertEqual(list(observation[:6]), [1, 0, 0, 0, 0, 0])
        self.assertEqual(list(observation[15:21]), [1, 0, 0, 0, 0, 0])
        _, reward, _, _, info = env.step(3)
        self.assertEqual(connection.time, 5)  # Never 10 seconds for two signals.
        self.assertEqual(reward, -45)  # (2 + 4 + 3 internal) * 5; interlink counted once.
        self.assertEqual(len(info["samples"]), 5)
        self.assertEqual(info["decision_count"], 1)
        self.assertEqual(info["action"]["A"]["reason"], "min_green")
        self.assertEqual(info["action"]["B"]["reason"], "min_green")

    def test_separate_switches_preserve_each_signal_clearance(self):
        env, connection = self.make_env()
        env.reset(seed=42)
        env.step(0)
        env.step(0)
        _, _, _, _, info = env.step(1)
        self.assertEqual(info["raw_observation"]["phase_index"], {"A": 3, "B": 0})
        env.step(2)
        self.assertEqual([s for s in connection.switches if s[0] == "A"], [("A", 10, 1), ("A", 13, 2), ("A", 14, 3)])
        self.assertEqual([s for s in connection.switches if s[0] == "B"], [("B", 15, 1), ("B", 18, 2), ("B", 19, 3)])

    def test_maximum_enforced_for_both_signals_when_agent_holds(self):
        env, connection = self.make_env()
        env.reset(seed=42)
        for _ in range(12):
            env.step(0)
        _, _, _, _, info = env.step(0)
        self.assertEqual(info["forced_switches"], 2)
        self.assertIn(("A", 60, 1), connection.switches)
        self.assertIn(("B", 60, 1), connection.switches)

    def test_fixed_mode_and_warmup_leave_native_timers_unchanged(self):
        env, connection = self.make_env(control_mode="fixed", warmup_seconds=35)
        _, info = env.reset(seed=42)
        self.assertEqual(info["episode_return"], 0)
        self.assertEqual(info["raw_observation"]["phase_index"], {"A": 3, "B": 3})
        env.step(3)
        self.assertEqual(connection.time, 40)
        for j in SIGNALS:
            self.assertEqual([s[1:] for s in connection.switches if s[0] == j], [(30, 1), (33, 2), (34, 3)])

    def test_terminal_and_reset_keep_mac_connection_alive(self):
        env, connection = self.make_env(duration_seconds=12)
        first, _ = env.reset(seed=42)
        env.step(0)
        env.step(0)
        last, _, terminated, truncated, info = env.step(0)
        self.assertTrue(terminated)
        self.assertFalse(truncated)
        self.assertEqual(info["interval_seconds"], 2)
        self.assertEqual(last[-1], 0)
        with self.assertRaises(ResetNeeded):
            env.step(0)
        second, _ = env.reset(seed=42)
        np.testing.assert_array_equal(first, second)
        env.close()
        self.assertEqual(connection.close_calls, 0)

    def test_collision_stops_control_until_reset(self):
        env, connection = self.make_env()
        env.reset(seed=42)
        connection.collisions = 1
        with self.assertRaises(RuntimeError):
            env.step(0)
        with self.assertRaises(ResetNeeded):
            env.step(0)

    def test_console_accepts_all_four_actions_and_reloads_without_reset(self):
        env, connection = self.make_env()
        loader = lambda path: (SimpleNamespace(choose_action=lambda obs, info: 3), "rule")
        session = ToyEnvSession(env, Path(__file__), controller_loader=loader, emit=lambda message: None)
        session.command("action 2")
        session.command("action 3")
        session.command("reload")
        self.assertEqual(connection.time, 10)
        session.command("step")
        session.tick()
        self.assertEqual(connection.time, 15)
        self.assertEqual(connection.close_calls, 0)

    def test_queue_rule_uses_both_junctions_without_bypassing_safety(self):
        env, _ = self.make_env()
        observation, info = env.reset(seed=42)
        self.assertEqual(queue_action(observation, info), 2)  # B east/west=4 > NS=0 + 2.


class CorridorInputTests(unittest.TestCase):
    def test_straight_routes_and_program_offsets_match_connections(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            settings = read_settings()
            write_network_inputs(folder, settings)
            edges = {e.get("id"): (e.get("from"), e.get("to")) for e in ET.parse(folder / "corridor2.edg.xml").iter("edge")}
            connections = {(c.get("from"), c.get("to")) for c in ET.parse(folder / "corridor2.con.xml").iter("connection")}
            for route in ROUTES.values():
                for left, right in zip(route, route[1:]):
                    self.assertEqual(edges[left][1], edges[right][0])
                    self.assertIn((left, right), connections)
            programs = ET.parse(folder / "corridor2.tll.xml").getroot().findall("tlLogic")
            self.assertEqual({p.get("id"): float(p.get("offset")) for p in programs}, {"A": 0, "B": 25})
            self.assertEqual(len(connections), 8)

    def test_demand_is_reproducible_sorted_and_stops_for_drain(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, settings = Path(tmp), read_settings()
            write_demand(folder, settings, "changing", 42)
            first = (folder / "corridor2.rou.xml").read_bytes()
            write_demand(folder, settings, "changing", 42)
            self.assertEqual(first, (folder / "corridor2.rou.xml").read_bytes())
            vehicles = list(ET.parse(folder / "corridor2.rou.xml").iter("vehicle"))
            departures = [float(v.get("depart")) for v in vehicles]
            self.assertEqual(departures, sorted(departures))
            self.assertTrue(all(0 <= d < 900 for d in departures))
            self.assertTrue(any(d < 450 for d in departures) and any(d >= 450 for d in departures))
            self.assertEqual(len({v.get("id") for v in vehicles}), len(vehicles))
            write_demand(folder, settings, "changing", 43)
            self.assertNotEqual(first, (folder / "corridor2.rou.xml").read_bytes())

    def test_frozen_cases_include_actual_sumo_seed_and_detect_input_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, settings = Path(tmp), read_settings()
            source = folder / "source"
            source.mkdir()
            (source / "corridor2.net.xml").write_text("<net/>", encoding="utf-8")
            (source / "corridor2.view.xml").write_text("<viewsettings/>", encoding="utf-8")
            cases = relative_cases(prepare_cases(folder / "cases", source, settings, ["balanced"], [1000]), folder)
            config, routes = case_paths(folder, cases[0])
            self.assertEqual(ET.parse(config).find("random_number/seed").get("value"), "1000")
            self.assertEqual(cases[0]["sumo_seed"], 1000)
            routes.write_text("<routes/>", encoding="utf-8")
            with self.assertRaises(ValueError):
                case_paths(folder, cases[0])

    def test_incomplete_cohort_suppresses_waiting_improvement_claim(self):
        common = {"profile": "high", "unfinished": 1, "not_departed_due": 0,
                  "cohort_unfinished": 1, "cohort_not_departed": 0}
        rows = [{**common, "method": "fixed", "cohort_mean_waiting_observed_s": 100},
                {**common, "method": "dqn", "cohort_mean_waiting_observed_s": 10}]
        self.assertIsNone(summarize_results(rows)["high"]["dqn"]["waiting_reduction_percent"])

    def test_signal_audit_catches_skipped_clearance_and_unfinished_long_green(self):
        initial = {"time_s": 120, "phase_index": 0, "phase_elapsed_s": 20, "signal_state": "GGrr"}
        skipped = {"time_s": 121, "phase_index": 3, "phase_elapsed_s": 1, "signal_state": "rrGG"}
        self.assertTrue(audit_corridor_signal([initial, skipped], 10, 60))
        excessive = {**initial, "time_s": 161, "phase_elapsed_s": 61}
        self.assertTrue(audit_corridor_signal([initial, excessive], 10, 60))
        valid_yellow = {"time_s": 121, "phase_index": 1, "phase_elapsed_s": 1, "signal_state": "yyrr"}
        valid_red = {"time_s": 124, "phase_index": 2, "phase_elapsed_s": 1, "signal_state": "rrrr"}
        valid_green = {"time_s": 125, "phase_index": 3, "phase_elapsed_s": 1, "signal_state": "rrGG"}
        self.assertEqual(audit_corridor_signal([initial, valid_yellow, valid_red, valid_green], 10, 60), [])


if __name__ == "__main__":
    unittest.main()
