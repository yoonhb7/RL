"""Native GUI contract checks with mocks; no SUMO process or network connection."""

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import traci.constants as tc

from src.traffic.gui_presentation import ON, OFF, PREFIX, ToyGuiPresentation
from src.traffic.safety_controller import DIRECTIONS


ROOT = Path(__file__).resolve().parents[1]


class GuiPresentationTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.connection.gui.getIDList.return_value = ["View #0"]
        self.connection.poi.getIDList.return_value = []
        self.connection.vehicle.getIDList.return_value = ["north_00000", "east_00000"]
        shapes = {"north": [(248.4, 500), (248.4, 257.2)],
                  "south": [(251.6, 0), (251.6, 242.8)],
                  "east": [(500, 251.6), (257.2, 251.6)],
                  "west": [(0, 248.4), (242.8, 248.4)]}
        self.connection.lane.getShape.side_effect = lambda lane: shapes[lane.split("_")[0]]
        self.connection.lane.getAllSubscriptionResults.return_value = {
            f"{direction}_in_0": {tc.LAST_STEP_VEHICLE_HALTING_NUMBER: index,
                                  tc.LAST_STEP_VEHICLE_NUMBER: index + 1,
                                  tc.LAST_STEP_MEAN_SPEED: 5.0}
            for index, direction in enumerate(DIRECTIONS)
        }
        self.connection.trafficlight.getSubscriptionResults.return_value = {
            tc.TL_CURRENT_PHASE: 0, tc.TL_RED_YELLOW_GREEN_STATE: "GGrr"}
        self.connection.trafficlight.getSpentDuration.return_value = 1
        self.connection.simulation.getSubscriptionResults.return_value = {
            tc.VAR_DEPARTED_VEHICLES_IDS: (), tc.VAR_ARRIVED_VEHICLES_IDS: ()}
        self.env = SimpleNamespace(horizon=1200, _arrived=4, decision_interval=5,
                                   capacities={direction: 32.0 for direction in DIRECTIONS},
                                   controller=SimpleNamespace(min_green=10, max_green=60),
                                   sumo_config="/Users/k2/rl-term-project/toy/toy.gui.sumocfg")
        self.info = {"raw_observation": {"time_s": 120, "phase_elapsed_s": 12}}
        self.messages = []
        self.display = ToyGuiPresentation(self.connection, controller="DQN", emit=self.messages.append)
        self.display("reset", self.env, info=self.info)

    def test_lamps_follow_actual_link_state_including_clearance(self):
        self.assertTrue(self.display.ready)
        for phase, state in ((1, "yyrr"), (2, "rrrr"), (3, "rrGG"), (4, "rryy"), (5, "rrrr")):
            self.connection.trafficlight.getSubscriptionResults.return_value = {
                tc.TL_CURRENT_PHASE: phase, tc.TL_RED_YELLOW_GREEN_STATE: state}
            self.display("second", self.env, now=121 + phase)
            for index, direction in enumerate(DIRECTIONS):
                for lamp in ("r", "y", "g"):
                    self.assertEqual(self.display.cache["color", f"signal/{direction}/{lamp}"],
                                     ON[lamp] if lamp == state[index].lower() else OFF[lamp])

    def test_arriving_vehicle_is_not_styled_after_removal(self):
        self.connection.vehicle.reset_mock()
        self.connection.simulation.getSubscriptionResults.return_value = {
            tc.VAR_DEPARTED_VEHICLES_IDS: ("new_vehicle", "already_gone"),
            tc.VAR_ARRIVED_VEHICLES_IDS: ("east_00000", "already_gone")}
        self.display("second", self.env, now=121)
        self.assertEqual(self.display.active, {"north_00000", "new_vehicle"})
        self.assertEqual(self.connection.vehicle.setColor.call_count, 1)
        self.assertEqual(self.connection.vehicle.setColor.call_args.args[0], "new_vehicle")

    def test_scene_has_no_information_panels_or_labels(self):
        self.assertTrue(self.display.ready)
        self.display("action", self.env, action=1, result={"reason": "min_green"})
        self.display("transition", self.env, reward=-17, info={"interval_seconds": 5,
                     "episode_return": -89, "decision_count": 8, "forced_switches": 1})
        self.display.set_status("RUNNING", 0)
        self.connection.poi.add.assert_not_called()
        self.connection.poi.setType.assert_not_called()
        generated = [call.args[0] for call in self.connection.polygon.add.call_args_list]
        self.assertFalse(any(name.startswith((PREFIX + "hud/", PREFIX + "lane/", PREFIX + "queue/"))
                             for name in generated))
        self.connection.gui.setBoundary.assert_called_with("View #0", 135, 135, 365, 365)

    def test_display_never_advances_time_or_issues_physical_control(self):
        self.assertTrue(self.display.ready)
        self.display("second", self.env, now=125)
        self.display.command("view", ["junction"])
        self.display.command("colors", ["waiting"])
        self.display.command("screenshot", [])
        self.connection.simulationStep.assert_not_called()
        self.assertTrue(all(call[0] in {"subscribe", "getSubscriptionResults", "getSpentDuration"}
                            for call in self.connection.trafficlight.method_calls))
        self.assertTrue(all(call[0] in {"getIDList", "setColor", "setShapeClass"}
                            for call in self.connection.vehicle.method_calls))
        path = self.connection.gui.screenshot.call_args.args[1]
        self.assertTrue(path.startswith("/Users/k2/rl-term-project/toy/toy_preview_"))

    def test_display_error_is_disabled_once_and_reset_can_recover(self):
        self.connection.trafficlight.getSubscriptionResults.side_effect = RuntimeError("GUI unavailable")
        self.display("second", self.env, now=121)
        self.assertTrue(self.display.disabled)
        count = len(self.messages)
        self.display("second", self.env, now=122)
        self.assertEqual(len(self.messages), count)
        self.connection.trafficlight.getSubscriptionResults.side_effect = None
        self.display("reset", self.env, info=self.info)
        self.assertTrue(self.display.ready)
        self.assertFalse(self.display.disabled)

    def test_gui_entry_point_preserves_all_simulation_options(self):
        original = ET.parse(ROOT / "sumo/toy/toy.sumocfg").getroot()
        visual = ET.parse(ROOT / "sumo/toy/toy.gui.sumocfg").getroot()
        for group in ("time", "processing", "random_number"):
            self.assertEqual([(item.tag, item.attrib) for item in original.find(group)],
                             [(item.tag, item.attrib) for item in visual.find(group)])
        for name in ("net-file", "route-files"):
            self.assertEqual(original.find(f"input/{name}").attrib, visual.find(f"input/{name}").attrib)
        scenery = ET.parse(ROOT / "sumo/toy/toy.scenery.add.xml").getroot()
        self.assertTrue(all(item.tag in {"poly", "poi"} for item in scenery))


if __name__ == "__main__":
    unittest.main()
