"""Regression checks for fixed-cohort ATT, insertion delay and censored training diagnostics."""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from src.agents.fourphase_evaluation import (
    ATT_PROTOCOL, complete_trip_metrics, validation_score, write_evaluation_cohort,
)


class TripMetricTests(unittest.TestCase):
    def calculate(self, trips, scheduled, *, complete=False, departed=None, arrived=None):
        root = ET.Element("tripinfos")
        for trip in trips:
            ET.SubElement(root, "tripinfo", {key: str(value) for key, value in trip.items()})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tripinfo.xml"
            ET.ElementTree(root).write(path)
            return complete_trip_metrics(
                {"status": "completed", "metrics": {}, "checks": {}}, path,
                {trip["id"] for trip in trips} if departed is None else departed,
                {trip["id"] for trip in trips if trip["arrival"] >= 0} if arrived is None else arrived,
                scheduled=scheduled, horizon=3600, require_complete=complete,
            )

    def test_training_diagnostic_includes_pending_but_is_not_final_ATT(self):
        summary = self.calculate([
            dict(id="done", depart=100, arrival=180, duration=80, waitingTime=10),
            dict(id="late", depart=3500, arrival=-1, duration=100, waitingTime=40),
        ], {"done": 90, "late": 3490, "pending": 1000})
        self.assertIsNone(summary["metrics"]["ATT_s"])
        self.assertAlmostEqual(summary["metrics"]["ATT_observed_due_s"], (90 + 110 + 2600) / 3)
        self.assertEqual(summary["metrics"]["AWT_observed_due_s"], (20 + 50 + 2600) / 3)
        self.assertEqual(summary["status"], "completed")

    def test_full_ATT_uses_scheduled_departure_even_when_insertion_is_after_cutoff(self):
        summary = self.calculate([
            dict(id="done", depart=100, arrival=180, duration=80, waitingTime=10),
            dict(id="late", depart=3700, arrival=3800, duration=100, waitingTime=40),
        ], {"done": 90, "late": 3400}, complete=True)
        self.assertEqual(summary["metrics"]["ATT_s"], 245.)
        self.assertEqual(summary["metrics"]["AWT_s"], 180.)
        self.assertEqual(summary["metrics"]["ATT_observed_due_s"], 145.)
        self.assertTrue(summary["ATT_protocol"]["all_arrived"])
        self.assertEqual(summary["status"], "completed")

    def test_pending_vehicle_cannot_disappear_from_selection_score(self):
        trips = [dict(id=str(i), depart=0, arrival=50, duration=50, waitingTime=0) for i in range(10)]
        summary = self.calculate(trips, {str(i): 0 for i in range(100)}, complete=True)
        self.assertEqual(summary["metrics"]["ATT_entered_tripinfo_s"], 50.)
        self.assertEqual(summary["metrics"]["ATT_observed_due_s"], 3245.)
        self.assertIsNone(summary["metrics"]["ATT_s"])
        self.assertEqual(summary["status"], "abnormal")
        with self.assertRaises(ValueError):
            validation_score([{**summary, "level": "low"}])

    def test_tripinfo_must_match_departed_and_arrived_vehicles(self):
        summary = self.calculate([
            dict(id="a", depart=10, arrival=30, duration=20, waitingTime=0),
        ], {"a": 0}, departed=set())
        self.assertEqual(summary["status"], "abnormal")

    def test_future_vehicle_is_excluded_without_mutating_original_routes(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = Path(temporary) / "source.xml", Path(temporary) / "cohort.xml"
            source.write_text('<routes><vType id="car"/><route id="r" edges="a b"/>'
                              '<vehicle id="due" depart="3599"/><vehicle id="future" depart="3600"/></routes>')
            original = source.read_bytes()
            write_evaluation_cohort(source, target, 3600)
            self.assertEqual(source.read_bytes(), original)
            root = ET.parse(target).getroot()
            self.assertEqual([v.get("id") for v in root.findall("vehicle")], ["due"])
            self.assertIsNotNone(root.find("vType"))
            self.assertIsNotNone(root.find("route"))

    def test_checkpoint_selection_rejects_old_protocol_and_uses_equal_level_weights(self):
        records = [dict(level=level, status="completed", metrics={"ATT_s": score},
                        ATT_protocol={"name": ATT_PROTOCOL, "all_arrived": True})
                   for level, score in (("low", 10.), ("medium", 20.), ("high", 60.))]
        self.assertEqual(validation_score(records)[0], 30.)
        records[0].pop("ATT_protocol")
        with self.assertRaises(ValueError):
            validation_score(records)


if __name__ == "__main__":
    unittest.main()
