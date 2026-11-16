"""Protocol checks with a fake TraCI clock; run explicitly by the user."""

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from gymnasium.error import ResetNeeded

from src.envs.fourphase_env import FourPhaseTrafficEnv
from src.traffic.fourphase.metrics import InvalidRun, TrafficMetrics
from src.traffic.fourphase.scenario import (
    LANES, STATES, TLS, connection_attributes, read_settings, write_demand, write_network_inputs,
)
from src.traffic.fourphase.signal import action_mask


class FakeSumo:
    def __init__(self, settings, queue=2):
        self.settings, self.queue = settings, queue
        self.time, self.phase, self.phase_age = 0, 0, 0
        self.phase_changes = []
        self.collisions = ()
        self.pending = ()
        self.teleports = ()
        self.active = ()
        self.departed_now = self.arrived_now = ()
        self.departure_time = {}
        self.loads = []
        self.close_count = 0
        self.simulation = SimpleNamespace(
            getTime=lambda: self.time, getDeltaT=lambda: 1,
            getOption=lambda name: "/Users/k2/rl-term-project/fourphase/cases/medium/seed_42/view.sumocfg",
            getDepartedIDList=lambda: self.departed_now, getArrivedIDList=lambda: self.arrived_now,
            getPendingVehicles=lambda: self.pending, getCollidingVehiclesIDList=lambda: self.collisions,
            getCollisions=lambda: (), getStartingTeleportIDList=lambda: self.teleports,
        )
        links = tuple(((LANES[i], f"{connection_attributes(i)['to']}_{connection_attributes(i)['toLane']}", "via"),)
                      for i in range(8))
        durations = tuple(d for g in settings["fixed_green_seconds"] for d in (g, 3, 1))
        self.trafficlight = SimpleNamespace(
            getIDList=lambda: (TLS,), getControlledLinks=lambda tls: links, getProgram=lambda tls: "fourphase",
            getAllProgramLogics=lambda tls: (SimpleNamespace(programID="fourphase", phases=tuple(
                SimpleNamespace(state=s, duration=d) for s, d in zip(STATES, durations))),),
            getPhase=lambda tls: self.phase, getRedYellowGreenState=lambda tls: STATES[self.phase],
            setPhase=self.set_phase, setPhaseDuration=lambda tls, duration: None,
        )
        self.lane = SimpleNamespace(
            getLength=lambda lane: 15.0,
            getIDList=lambda: (*LANES, ":internal_0"),
            getLastStepHaltingNumber=lambda lane: self.queue if lane == LANES[0] else (9 if lane == ":internal_0" else 0),
            getLastStepVehicleNumber=lambda lane: (self.queue if lane == LANES[0] else (9 if lane == ":internal_0" else 0)) + (
                getattr(self, "moving", 0) if lane == LANES[0] else 0),
        )
        self.vehicle = SimpleNamespace(
            getIDList=lambda: self.active, getDeparture=lambda vehicle: self.departure_time[vehicle],
            getLaneID=lambda vehicle: LANES[0], getLanePosition=lambda vehicle: 10.0,
        )

    def set_phase(self, tls, phase):
        self.phase, self.phase_age = phase, 0
        self.phase_changes.append((self.time, phase))

    def simulationStep(self):
        self.time += 1
        self.phase_age += 1

    def load(self, arguments):
        self.loads.append(arguments)
        self.time = self.phase = self.phase_age = 0
        self.phase_changes.clear()

    def close(self):
        self.close_count += 1


class FourPhaseProtocolTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.case = Path(self.folder.name)
        self.settings = read_settings()
        (self.case / "demand.rou.xml").write_text(
            '<routes><vehicle id="a" depart="0"/><vehicle id="future" depart="3600"/></routes>', encoding="utf-8")

    def make_env(self, *, queue=2, horizon=3600):
        settings = {**self.settings, "duration_seconds": horizon}
        connection = FakeSumo(settings, queue)
        env = FourPhaseTrafficEnv(self.case, connection=connection, settings=settings)
        self.addCleanup(env.close)
        return env, connection

    def test_masks_predict_the_entire_hold_and_protect_initial_minimum(self):
        for age, expected in ((0, (True, False)), (11, (True, True)), (45, (True, True)),
                              (56, (False, True)), (60, (False, True))):
            with self.subTest(age=age):
                self.assertEqual(action_mask(age, self.settings), expected)

    def test_observation_includes_moving_vehicle_density_per_lane(self):
        env, connection = self.make_env(queue=1)
        connection.moving = 3
        state, info = env.reset(seed=42)
        self.assertEqual(state[0], .5)   # 정지 1대 / 용량 2대
        self.assertEqual(state[8], 1.5)  # 주행 3대 / 용량 2대 (정지 차량은 제외)
        self.assertEqual(info["moving_raw"][LANES[0]], 3)
        self.assertTrue(env.observation_space.contains(state))

    def test_observation_allows_queue_above_one_without_clipping(self):
        env, _ = self.make_env(queue=5)
        state, info = env.reset(seed=42)
        self.assertEqual(state.shape, (21,))
        self.assertEqual(state.dtype, np.float32)
        self.assertEqual(state[0], 2.5)  # 15m / (5m + 2.5m) capacity = 2 vehicles.
        self.assertEqual(list(state[8:16]), [0] * 8)  # 주행 차량 없음
        self.assertEqual(list(state[16:20]), [1, 0, 0, 0])
        self.assertEqual(state[20], 0)
        self.assertTrue(env.observation_space.contains(state))
        self.assertEqual(info["queues_raw"][LANES[0]], 5)
        self.assertEqual(list(info["action_mask"]), [True, False])

    def test_invalid_switch_is_rejected_without_executing_or_relabeling_action(self):
        env, connection = self.make_env()
        env.reset(seed=42)
        with self.assertRaises(ValueError):
            env.step(1)
        self.assertEqual(connection.time, 0)
        self.assertEqual(env.decisions, 0)
        env.step(0)  # Remains usable after a rejected request.
        self.assertEqual(connection.time, 15)

    def test_switch_is_three_yellow_one_red_eleven_green(self):
        env, connection = self.make_env()
        env.reset(seed=42)
        env.step(0)
        _, reward, terminated, truncated, info = env.step(1)
        self.assertEqual(connection.phase_changes, [(0, 0), (15, 1), (18, 2), (19, 3)])
        self.assertEqual(connection.time, 30)
        self.assertEqual(info["green_elapsed_s"], 11)
        self.assertEqual(reward, -2)
        self.assertEqual(info["interval_stop_vehicle_s"], 30)
        self.assertFalse(terminated or truncated)
        self.assertEqual(env.runtime.metrics.phase_seconds[:4], [15, 3, 1, 11])

    def test_green_56_rejects_hold_and_keeps_the_switch_action(self):
        env, connection = self.make_env()
        env.reset(seed=42)
        env.step(0)
        env.step(1)
        for _ in range(3):
            _, _, _, _, info = env.step(0)
        self.assertEqual(info["green_elapsed_s"], 56)
        before = connection.time
        with self.assertRaises(ValueError):
            env.step(0)
        self.assertEqual(connection.time, before)
        env.step(1)
        self.assertEqual(env.runtime.controller.green, 2)

    def test_horizon_is_truncation_and_retains_real_final_state_and_mask(self):
        env, connection = self.make_env(horizon=60)
        state, _ = env.reset(seed=42)
        for _ in range(4):
            next_state, _, terminated, truncated, info = env.step(0)
        self.assertFalse(terminated)
        self.assertTrue(truncated)
        self.assertEqual(next_state[20], 1)
        self.assertEqual(state[20], 0)
        self.assertEqual(list(info["action_mask"]), [False, True])
        self.assertTrue(info["episode"]["checks"]["reward_stop_identity"])
        with self.assertRaises(ResetNeeded):
            env.step(1)
        self.assertEqual(connection.time, 60)
        env.reset(seed=42)
        self.assertEqual(connection.time, 0)
        self.assertEqual(connection.close_count, 0)  # Injected connection survives reset.

    def test_full_hour_has_240_decisions_and_raw_reward_identity(self):
        env, _ = self.make_env()
        _, info = env.reset(seed=42)
        terminated = truncated = False
        for _ in range(240):
            action = 0 if info["action_mask"][0] else 1
            _, _, terminated, truncated, info = env.step(action)
        self.assertFalse(terminated)
        self.assertTrue(truncated)
        self.assertEqual(env.decisions, 240)
        self.assertEqual(env.runtime.metrics.stop_in, -15 * env.raw_return)
        self.assertEqual(env.runtime.metrics.stop_in, 7200)
        self.assertEqual(env.runtime.metrics.stop_network, 39600)  # Internal lane excluded from R1.

    def test_collision_is_operational_failure_instead_of_a_terminal_transition(self):
        env, connection = self.make_env()
        env.reset(seed=42)
        connection.collisions = ("a", "b")
        with self.assertRaises(InvalidRun) as context:
            env.step(0)
        self.assertEqual(context.exception.event["time_s"], 1)
        self.assertEqual(context.exception.event["collision_vehicle_ids"], ["a", "b"])
        self.assertEqual(env.decisions, 0)
        with self.assertRaises(ResetNeeded):
            env.step(0)

    def test_reset_passes_collision_and_insertion_settings_to_mac(self):
        env, connection = self.make_env()
        env.reset(seed=42)
        arguments = connection.loads[0]
        for flag, value in (("--collision.action", "warn"), ("--collision.check-junctions", "true"),
                            ("--time-to-teleport", "-1"), ("--max-depart-delay", "-1")):
            self.assertEqual(arguments[arguments.index(flag) + 1], value)
        self.assertIn("--start", arguments)

    def test_pending_integral_keeps_wait_of_vehicles_that_later_enter(self):
        connection = FakeSumo(self.settings)
        metrics = TrafficMetrics(self.case / "demand.rou.xml", 3600)
        controller = SimpleNamespace(phase=0, elapsed=0)
        for now, pending in ((1, ("a", "future")), (2, ("a",)), (3, ())):
            connection.time, connection.pending = now, pending
            metrics.collect(connection, controller)
        self.assertEqual(metrics.pending_seconds, 2)
        self.assertEqual(metrics.last_sample["pending_due"], 0)

    def test_J_and_vehicle_conservation_include_delayed_insertion(self):
        connection = FakeSumo(self.settings)
        metrics = TrafficMetrics(self.case / "demand.rou.xml", 3)
        controller = SimpleNamespace(phase=0, elapsed=0, switches=0)
        connection.time, connection.pending = 1, ("a",)
        metrics.collect(connection, controller)
        connection.time, connection.pending = 2, ()
        connection.departed_now, connection.active = ("a",), ("a",)
        connection.departure_time["a"] = 1
        metrics.collect(connection, controller)
        connection.time, connection.departed_now, connection.active, connection.arrived_now = 3, (), (), ("a",)
        metrics.collect(connection, controller)
        summary = metrics.summary(connection, controller=controller)
        self.assertEqual(summary["status"], "completed")
        self.assertTrue(all(summary["checks"].values()))
        self.assertEqual(summary["metrics"]["W_stop_in_vehicle_s"] + summary["metrics"]["W_pending_vehicle_s"], 7)  # 6 stopped + 1 pending.
        self.assertEqual(summary["counts"]["scheduled_after_cutoff"], 1)

    def test_network_inputs_have_only_eight_straight_and_left_connections(self):
        write_network_inputs(self.case, self.settings)
        connections = ET.parse(self.case / "network.con.xml").getroot().findall("connection")
        self.assertEqual(len(connections), 8)
        self.assertEqual(connections[1].get("fromLane"), "1")
        self.assertEqual(connections[1].get("to"), "east_out")
        self.assertEqual(connections[5].get("to"), "south_out")
        self.assertEqual([p.get("state") for p in ET.parse(self.case / "network.tll.xml").getroot().findall("tlLogic/phase")], list(STATES))

    def test_demand_is_reproducible_and_continues_beyond_cutoff(self):
        write_demand(self.case, self.settings, "medium", 42)
        first = (self.case / "demand.rou.xml").read_bytes()
        write_demand(self.case, self.settings, "medium", 42)
        self.assertEqual(first, (self.case / "demand.rou.xml").read_bytes())
        metadata = json.loads((self.case / "demand.json").read_text())
        self.assertGreater(metadata["scheduled_after_cutoff"], 0)
        self.assertEqual(metadata["scheduled_total"], metadata["scheduled_due"] + metadata["scheduled_after_cutoff"])
        for vehicle in ET.parse(self.case / "demand.rou.xml").getroot().findall("vehicle"):
            self.assertEqual(float(vehicle.get("depart")) % 1, 0)
            self.assertEqual(vehicle.get("departLane"), "1" if vehicle.get("route").endswith("left") else "0")


if __name__ == "__main__":
    unittest.main()
