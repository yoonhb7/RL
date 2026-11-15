"""Check four-aspect direction heads and ensure decoration never controls traffic."""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock

from src.traffic.fourphase.city_display import FourPhaseCityDisplay
from src.traffic.fourphase.city_scene import CityGeometry, OFF, ON, PREFIX
from src.traffic.fourphase.scenario import DIRECTIONS, STATES


class FourPhaseCityTests(unittest.TestCase):
    def make_display(self, *, detailed=False):
        connection = Mock()
        connection.junction.getPosition.return_value = (500, 500)
        connection.gui.getIDList.return_value = ("View #0",)
        connection.polygon.getIDList.return_value = ()
        connection.vehicle.getIDList.return_value = ()
        connection.trafficlight.getRedYellowGreenState.return_value = STATES[0]
        display = FourPhaseCityDisplay(connection, detailed_cars=detailed)
        display.attach()
        return display, connection

    def test_four_combined_signal_heads_follow_all_twelve_phases(self):
        display, connection = self.make_display()
        self.assertEqual(len(display.geometry.signal_lamps), 4)
        red, green, yellow, left = {"r"}, {"g"}, {"y"}, {"r", "left"}
        # Explicit expected indication sets for N/S/E/W, including red+left.
        expected = ((green, green, red, red), (yellow, yellow, red, red), (red, red, red, red),
                    (left, left, red, red), (yellow, yellow, red, red), (red, red, red, red),
                    (red, red, green, green), (red, red, yellow, yellow), (red, red, red, red),
                    (red, red, left, left), (red, red, yellow, yellow), (red, red, red, red))
        for state, heads in zip(STATES, expected):
            connection.trafficlight.getRedYellowGreenState.return_value = state
            display.last_signal = None
            connection.polygon.setColor.reset_mock()
            display.update_signals()
            colors = display.lamp_colors
            for direction, enabled in zip(DIRECTIONS, heads):
                lamps = display.geometry.signal_lamps[direction]
                self.assertEqual(set(lamps), {"r", "y", "left", "g"})
                for lamp, shape_id in lamps.items():
                    on = ON["g" if lamp == "left" else lamp]
                    self.assertEqual(colors[shape_id], on if lamp in enabled else OFF)

    def test_old_eight_head_assets_are_replaced_when_attaching(self):
        display, connection = self.make_display()
        legacy = PREFIX + "signal.north.straight.r"
        connection.polygon.getIDList.return_value = (legacy, PREFIX + "shape.0001", "other.scene")
        connection.polygon.remove.reset_mock()
        display.attach()
        removed = {call.args[0] for call in connection.polygon.remove.call_args_list}
        self.assertIn(legacy, removed)
        self.assertIn(PREFIX + "shape.0001", removed)
        self.assertNotIn("other.scene", removed)

    def test_scene_file_contains_only_graphical_shapes_without_traffic_objects(self):
        geometry = CityGeometry().build()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "city.add.xml"
            geometry.write(path)
            root = ET.parse(path).getroot()
            self.assertTrue(all(child.tag == "poly" for child in root))
            self.assertEqual(len(root), len(geometry.shapes))
            self.assertTrue(all(child.get("id").startswith(PREFIX) for child in root))
            self.assertFalse(any("hud" in child.get("id") or "label" in child.get("id") for child in root))

    def test_positive_layer_decorations_do_not_cover_the_straight_road_arms(self):
        geometry = CityGeometry().build()
        for shape in geometry.shapes:
            if shape["layer"] < 0:
                continue
            for x, y in shape["shape"]:
                dx, dy = abs(x - 500), abs(y - 500)
                self.assertFalse((dx <= 6.4 and dy > 10.4) or (dy <= 6.4 and dx > 10.4), shape["id"])

    def test_display_never_advances_time_or_changes_signal_vehicle_or_lane_dynamics(self):
        display, connection = self.make_display(detailed=True)
        connection.vehicle.getIDList.return_value = ("veh_000000",)
        connection.vehicle.getPosition.return_value = (495.2, 800)
        connection.vehicle.getAngle.return_value = 180
        connection.vehicle.getColor.return_value = (41, 166, 218, 255)
        connection.vehicle.getLength.return_value = 5
        connection.vehicle.getWidth.return_value = 1.8
        display.update()
        connection.simulationStep.assert_not_called()
        self.assertTrue(all(call[0].startswith("get") for call in connection.trafficlight.method_calls))
        self.assertTrue(all(call[0].startswith("get") for call in connection.vehicle.method_calls))
        self.assertFalse(connection.lane.method_calls)
        self.assertEqual(connection.polygon.addDynamics.call_count, 8)
        self.assertTrue(all(call.kwargs["trackedObjectID"] == "veh_000000"
                            for call in connection.polygon.addDynamics.call_args_list))

    def test_departed_vehicle_shapes_are_cleaned_without_touching_the_scene(self):
        display, connection = self.make_display(detailed=True)
        ids = [PREFIX + "car.old.0", PREFIX + "car.old.1"]
        display.cars["old"] = ids
        connection.polygon.getIDList.return_value = (*ids, PREFIX + "signal.north.straight.r")
        display.update_cars()
        self.assertEqual([call.args[0] for call in connection.polygon.remove.call_args_list], ids)
        self.assertEqual(display.cars, {})

    def test_static_lamps_have_no_made_up_signal_state_before_connection(self):
        geometry = CityGeometry().build()
        colors = {shape["id"]: shape["color"] for shape in geometry.shapes}
        for lamps in geometry.signal_lamps.values():
            for shape_id in lamps.values():
                self.assertEqual(colors[shape_id], OFF)

    def test_standalone_default_keeps_native_vehicles_visible(self):
        root = ET.parse(Path(__file__).resolve().parents[1] / "configs/fourphase_city.view.xml").getroot()
        default = root.findall("scheme")[-1]
        self.assertEqual(default.get("name"), "Four phase city")
        self.assertGreater(float(default.find("vehicles").get("vehicle_exaggeration")), 1)


if __name__ == "__main__":
    unittest.main()
