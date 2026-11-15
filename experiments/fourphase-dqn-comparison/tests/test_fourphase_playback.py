"""Check cached remote telemetry and pauseable one-second physical stepping."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import traci.constants as tc

from src.envs.fourphase_env import FourPhaseTrafficEnv
from src.traffic.fourphase.metrics import InvalidRun
from src.traffic.fourphase.scenario import STATES, read_settings
from src.traffic.fourphase.telemetry import TrafficSnapshot
from test_fourphase import FakeSumo


class SubscribedSumo(FakeSumo):
    def __init__(self, settings):
        super().__init__(settings)
        self.lane.subscribe = Mock()
        self.simulation.subscribe = Mock()
        self.trafficlight.subscribe = Mock()
        halt = self.lane.getLastStepHaltingNumber
        lanes = self.lane.getIDList()
        self.lane.getAllSubscriptionResults = lambda: {
            lane: {tc.LAST_STEP_VEHICLE_HALTING_NUMBER: halt(lane)} for lane in lanes}
        self.simulation.getSubscriptionResults = lambda: {
            tc.VAR_TIME: self.time, tc.VAR_DEPARTED_VEHICLES_IDS: self.departed_now,
            tc.VAR_ARRIVED_VEHICLES_IDS: self.arrived_now, tc.VAR_PENDING_VEHICLES: self.pending,
            tc.VAR_COLLIDING_VEHICLES_IDS: self.collisions,
            tc.VAR_TELEPORT_STARTING_VEHICLES_IDS: self.teleports}
        self.trafficlight.getSubscriptionResults = lambda tls: {
            tc.TL_CURRENT_PHASE: self.phase, tc.TL_RED_YELLOW_GREEN_STATE: STATES[self.phase]}


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.case = Path(self.folder.name)
        (self.case / "demand.rou.xml").write_text('<routes><vehicle id="a" depart="0"/></routes>')
        self.settings = read_settings()

    def env(self, connection, *, cached=False):
        env = FourPhaseTrafficEnv(self.case, connection=connection, settings=self.settings,
                                  use_subscriptions=cached)
        self.addCleanup(env.close)
        env.reset(seed=42)
        return env

    def test_view_can_pause_after_one_second_without_changing_decision_interval(self):
        connection = FakeSumo(self.settings)
        env = self.env(connection)
        env.begin_action(0)
        self.assertIsNone(env.advance_action_second())
        self.assertEqual(connection.time, 1)
        self.assertEqual(env.decisions, 0)
        self.assertTrue(env.action_in_progress)
        with self.assertRaises(RuntimeError):
            env.begin_action(1)
        for _ in range(13):
            self.assertIsNone(env.advance_action_second())
        state, reward, terminated, truncated, info = env.advance_action_second()
        self.assertEqual(connection.time, 15)
        self.assertEqual(reward, -2)
        self.assertEqual(info["interval_seconds"], 15)
        self.assertFalse(env.action_in_progress)
        self.assertFalse(terminated or truncated)

    def test_subscriptions_return_the_same_switch_observation_and_reward(self):
        direct = self.env(FakeSumo(self.settings))
        cached = self.env(SubscribedSumo(self.settings), cached=True)
        for action in (0, 1, 0, 0, 0, 1):
            a, b = direct.step(action), cached.step(action)
            np.testing.assert_array_equal(a[0], b[0])
            self.assertEqual(a[1:4], b[1:4])
            self.assertEqual(a[4]["queues_raw"], b[4]["queues_raw"])
        self.assertEqual(direct.runtime.metrics.stop_in, cached.runtime.metrics.stop_in)
        self.assertEqual(direct.runtime.metrics.stop_network, cached.runtime.metrics.stop_network)
        self.assertEqual(direct.runtime.metrics.phase_seconds, cached.runtime.metrics.phase_seconds)

    def test_snapshot_refresh_reads_local_subscription_caches_only(self):
        connection = SubscribedSumo(self.settings)
        snapshot = TrafficSnapshot(connection)
        connection.simulation.getTime = Mock(side_effect=AssertionError("extra clock request"))
        connection.lane.getLastStepHaltingNumber = Mock(side_effect=AssertionError("extra lane request"))
        connection.trafficlight.getPhase = Mock(side_effect=AssertionError("extra TLS request"))
        connection.time = 1
        connection.pending = ("a",)
        snapshot.refresh()
        self.assertEqual(snapshot.time, 1)
        self.assertEqual(snapshot.pending, ("a",))
        self.assertEqual(sum(snapshot.queues.values()), 11)

    def test_cached_collision_still_aborts_instead_of_becoming_a_transition(self):
        connection = SubscribedSumo(self.settings)
        env = self.env(connection, cached=True)
        connection.collisions = ("a", "b")
        with self.assertRaises(InvalidRun):
            env.step(0)
        self.assertEqual(env.decisions, 0)

    def test_missing_or_stale_subscription_data_is_rejected(self):
        connection = SubscribedSumo(self.settings)
        snapshot = TrafficSnapshot(connection)
        connection.simulation.getSubscriptionResults = lambda: {}
        with self.assertRaises(RuntimeError):
            snapshot.refresh()
        connection = SubscribedSumo(self.settings)
        env = self.env(connection, cached=True)
        connection.simulationStep = lambda: None
        with self.assertRaisesRegex(RuntimeError, "exactly one second"):
            env.step(0)


if __name__ == "__main__":
    unittest.main()
