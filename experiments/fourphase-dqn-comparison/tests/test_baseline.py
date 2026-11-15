"""Regression checks for signal mapping and incomplete-vehicle accounting."""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from src.traffic.metrics import summarize


ROOT = Path(__file__).resolve().parents[1]
TOY = ROOT / "sumo" / "toy"


class MetricsTests(unittest.TestCase):
    def summary(self, xml, schedule, samples=()):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as directory:
            path = Path(directory) / "tripinfo.xml"
            path.write_text(xml, encoding="utf-8")
            return summarize(schedule, path, samples, warmup=10, end=100)

    def test_unfinished_pending_future_and_warmup_are_distinct(self):
        result = self.summary(
            '<tripinfos>'
            '<tripinfo id="warmup" depart="1" arrival="30" waitingTime="100" duration="29" departDelay="0"/>'
            '<tripinfo id="done" depart="20" arrival="50" waitingTime="10" duration="30" departDelay="0"/>'
            '<tripinfo id="running" depart="30" arrival="-1" waitingTime="50" duration="70" departDelay="0"/>'
            '</tripinfos>',
            {"warmup": 1, "done": 20, "running": 30, "pending": 40, "future": 120},
        )
        counts, metrics = result["counts"], result["metrics"]
        self.assertEqual(counts["arrived"], 2)
        self.assertEqual(counts["unfinished"], 1)
        self.assertEqual(counts["not_departed_due"], 1)
        self.assertEqual(counts["scheduled_after_end"], 1)
        self.assertEqual(counts["cohort_due"], 3)
        self.assertEqual(counts["cohort_not_departed"], 1)
        self.assertEqual(metrics["cohort_mean_waiting_observed_s"], 30)
        self.assertEqual(metrics["cohort_completed_mean_waiting_s"], 10)
        self.assertEqual(metrics["cohort_pending_departure_wait_s"], 60)

    def test_cohort_uses_planned_departure_even_when_insertion_is_delayed(self):
        result = self.summary(
            '<tripinfos><tripinfo id="delayed" depart="15" arrival="40" waitingTime="9" duration="25" departDelay="10"/></tripinfos>',
            {"delayed": 5},
        )
        self.assertEqual(result["counts"]["cohort_departed"], 0)
        self.assertIsNone(result["metrics"]["cohort_mean_waiting_observed_s"])

    def test_queue_integral_excludes_warmup(self):
        result = self.summary('<tripinfos/>', {}, [
            {"measured": 0, "network_halting": 99, "step_seconds": 1},
            {"measured": 1, "network_halting": 2, "step_seconds": 1},
            {"measured": 1, "network_halting": 4, "step_seconds": 1},
        ])
        self.assertEqual(result["metrics"]["network_queue_vehicle_seconds"], 6)
        self.assertEqual(result["metrics"]["network_queue_mean_vehicles"], 3)
        self.assertEqual(result["metrics"]["network_queue_p95_vehicles"], 4)

    def test_empty_trips_do_not_report_zero_mean_wait(self):
        result = self.summary('<tripinfos/>', {"blocked": 20})
        self.assertIsNone(result["metrics"]["cohort_mean_waiting_observed_s"])
        self.assertEqual(result["counts"]["cohort_not_departed"], 1)


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network = ET.parse(TOY / "toy.net.xml")

    def test_signal_links_and_green_directions(self):
        links = {int(c.get("linkIndex")): c.get("from")
                 for c in self.network.iter("connection") if c.get("tl") == "center"}
        self.assertEqual(links, {0: "north_in", 1: "south_in", 2: "east_in", 3: "west_in"})
        phases = self.network.find("tlLogic").findall("phase")
        self.assertEqual([links[i] for i, state in enumerate(phases[0].get("state")) if state == "G"],
                         ["north_in", "south_in"])
        self.assertEqual([links[i] for i, state in enumerate(phases[3].get("state")) if state == "G"],
                         ["east_in", "west_in"])

    def test_yellow_and_all_red_separate_green_phases(self):
        phases = self.network.find("tlLogic").findall("phase")
        self.assertEqual([(float(p.get("duration")), p.get("state")) for p in phases],
                         [(30, "GGrr"), (3, "yyrr"), (1, "rrrr"), (30, "rrGG"), (3, "rryy"), (1, "rrrr")])

    def test_every_vehicle_has_a_legal_sorted_straight_route(self):
        demand = ET.parse(TOY / "toy.rou.xml")
        routes = {r.get("id"): r.get("edges").split() for r in demand.iter("route")}
        allowed = {(c.get("from"), c.get("to")) for c in self.network.iter("connection") if c.get("tl")}
        departures = []
        identifiers = set()
        for vehicle in demand.iter("vehicle"):
            edges = routes[vehicle.get("route")]
            self.assertIn(tuple(edges), allowed)
            self.assertNotIn(vehicle.get("id"), identifiers)
            identifiers.add(vehicle.get("id"))
            departures.append(float(vehicle.get("depart")))
        self.assertGreater(len(departures), 0)
        self.assertEqual(departures, sorted(departures))


if __name__ == "__main__":
    unittest.main()
