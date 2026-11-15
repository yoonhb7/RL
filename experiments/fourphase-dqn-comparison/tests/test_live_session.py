"""Persistent-session regression checks. These tests never connect to SUMO."""

import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.traffic.live_session import ConsoleInput, DIRECTIONS, EXPECTED_STATES, LiveSession, run_console


ROOT = Path(__file__).resolve().parents[1]


class FakeSumo:
    def __init__(self):
        self.time = 0.0
        self.phase = 0
        self.elapsed = 0.0
        self.simulation = Mock()
        self.simulation.getTime.side_effect = lambda: self.time
        self.simulation.getOption.side_effect = {
            "configuration-file": "/Users/k2/rl-term-project/toy/toy.sumocfg", "seed": "42",
        }.__getitem__
        self.trafficlight = Mock()
        self.trafficlight.getIDList.return_value = ("center",)
        self.trafficlight.getControlledLinks.return_value = tuple(
            ((f"{d}_in_0", "out_0", "via_0"),) for d in DIRECTIONS
        )
        self.trafficlight.getProgram.return_value = "fixed"
        self.trafficlight.getAllProgramLogics.return_value = (
            SimpleNamespace(programID="fixed", phases=tuple(
                SimpleNamespace(state=state, duration=duration)
                for state, duration in zip(EXPECTED_STATES, (30, 3, 1, 30, 3, 1))
            )),
        )
        self.trafficlight.getPhase.side_effect = lambda _: self.phase
        self.trafficlight.getSpentDuration.side_effect = lambda _: self.elapsed
        self.trafficlight.getRedYellowGreenState.side_effect = lambda _: EXPECTED_STATES[self.phase]
        self.lane = Mock()
        self.lane.getLastStepHaltingNumber.return_value = 0
        self.lane.getLastStepVehicleNumber.return_value = 0
        self.simulationStep = Mock(side_effect=self.advance)
        self.load = Mock(side_effect=self.reset)
        self.close = Mock()

    def advance(self):
        self.time += 1
        self.elapsed += 1

    def reset(self, arguments):
        self.time, self.elapsed, self.phase = 0.0, 0.0, 0


class LiveSessionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "controller.py"
        self.write_controller(30)
        self.connection = FakeSumo()
        self.output = []
        self.session = LiveSession(self.connection, self.path, emit=self.output.append)

    def write_controller(self, duration):
        self.path.write_text(
            f"GREEN = {duration}\ndef green_seconds(observation):\n    return GREEN\n", encoding="utf-8",
        )

    def test_starts_paused_and_reaching_horizon_keeps_connection(self):
        self.assertFalse(self.session.advancing)
        self.connection.time = 1199
        self.session.command("resume")
        self.session.tick()
        self.assertEqual(self.connection.time, 1200)
        self.assertFalse(self.session.advancing)
        self.assertFalse(self.session.closed)
        self.connection.close.assert_not_called()
        self.session.command("resume")
        self.assertFalse(self.session.advancing)

    def test_reload_reads_same_size_edits_without_advancing_or_reconnecting(self):
        self.connection.time = 100
        self.session.command("resume")
        old_version = self.session.controller_version
        self.write_controller(45)
        self.session.command("reload")
        self.assertEqual(self.session.controller.green_seconds({}), 45)
        self.assertNotEqual(self.session.controller_version, old_version)
        self.assertEqual(self.connection.time, 100)
        self.assertFalse(self.session.advancing)
        self.connection.simulationStep.assert_not_called()
        self.connection.close.assert_not_called()
        self.connection.load.assert_not_called()

    def test_broken_reload_keeps_previous_policy_and_pauses(self):
        previous = self.session.controller
        for source, error in (
            ("def green_seconds(:", SyntaxError),
            ("def green_seconds(observation):\n    return 2\n", ValueError),
            ("green_seconds = None\n", ValueError),
        ):
            with self.subTest(source=source):
                self.path.write_text(source, encoding="utf-8")
                self.session.command("resume")
                with self.assertRaises(error):
                    self.session.command("reload")
                self.assertIs(self.session.controller, previous)
                self.assertFalse(self.session.advancing)
                self.connection.close.assert_not_called()

    def test_missing_controller_on_reload_does_not_replace_previous_policy(self):
        previous = self.session.controller
        self.session.controller_path = self.path.parent / "missing.py"
        with self.assertRaises(ValueError):
            self.session.command("reload")
        self.assertIs(self.session.controller, previous)
        self.connection.close.assert_not_called()

    def test_reset_uses_mac_path_and_keeps_reloaded_controller(self):
        self.write_controller(45)
        self.session.command("reload")
        previous = self.session.controller
        self.connection.time = 700
        self.session.command("reset")
        self.connection.load.assert_called_once_with([
            "-c", "/Users/k2/rl-term-project/toy/toy.sumocfg", "--start", "--seed", "42",
        ])
        self.assertEqual(self.connection.time, 0)
        self.assertIs(self.session.controller, previous)
        self.assertFalse(self.session.advancing)
        self.connection.close.assert_not_called()

    def test_step_budget_and_pause_keep_connection(self):
        self.session.command("step 2")
        self.session.tick()
        self.assertTrue(self.session.advancing)
        self.session.tick()
        self.assertFalse(self.session.advancing)
        self.assertEqual(self.connection.time, 2)
        self.session.command("resume")
        self.session.command("pause")
        self.assertFalse(self.session.advancing)
        self.connection.close.assert_not_called()

    def test_green_duration_is_total_and_does_not_extend_forever(self):
        self.connection.elapsed = 12
        self.session.tick()
        self.session.tick()
        durations = [call.args[1] for call in self.connection.trafficlight.setPhaseDuration.call_args_list]
        self.assertEqual(durations, [18, 17])
        self.connection.elapsed = 35
        self.session.tick()
        self.connection.trafficlight.setPhaseDuration.assert_called_with("center", 0)

    def test_yellow_and_all_red_are_never_overridden(self):
        self.session.controller.green_seconds = Mock(side_effect=AssertionError("Called outside green"))
        for phase in (1, 2, 4, 5):
            self.connection.phase = phase
            self.session.tick()
        self.session.controller.green_seconds.assert_not_called()
        self.connection.trafficlight.setPhaseDuration.assert_not_called()

    def test_invalid_duration_is_rejected_before_touching_sumo(self):
        for value in (0, 61, float("nan"), float("inf"), True):
            with self.subTest(value=value):
                self.session.controller.green_seconds = lambda observation: value
                with self.assertRaises(ValueError):
                    self.session.tick()
        self.connection.trafficlight.setPhaseDuration.assert_not_called()
        self.connection.simulationStep.assert_not_called()

    def test_console_recovers_from_reload_error_and_can_resume(self):
        self.path.write_text("def green_seconds(:", encoding="utf-8")
        self.session.delay = 0
        reader = Mock()
        reader.poll.side_effect = [(True, "reload"), (True, "resume"), (False, None), (True, "quit")]
        with patch("src.traffic.live_session.ConsoleInput", return_value=reader), patch("sys.stdout", new=io.StringIO()):
            run_console(self.session)
        self.assertEqual(self.connection.time, 1)
        self.assertTrue(self.session.closed)
        self.connection.close.assert_not_called()


class ConsoleInputTests(unittest.TestCase):
    def test_pasted_command_lines_are_not_lost_to_read_buffering(self):
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd, encoding="utf-8") as stream:
            with os.fdopen(write_fd, "wb") as writer:
                writer.write(b"pause\nreload\nresume\n")
            reader = ConsoleInput(stream)
            self.assertEqual(reader.poll(0), (True, "pause"))
            self.assertEqual(reader.poll(0), (True, "reload"))
            self.assertEqual(reader.poll(0), (True, "resume"))
            self.assertEqual(reader.poll(0), (True, None))


if __name__ == "__main__":
    unittest.main()
