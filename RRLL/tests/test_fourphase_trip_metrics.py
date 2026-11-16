"""ATT/AWT include unfinished trips, as in CityFlow (TSCC 2019) and LibSignal."""

import tempfile
import unittest
from pathlib import Path

from src.agents.fourphase_evaluation import complete_trip_metrics


TRIPINFO = """<tripinfos>
    <tripinfo id="done" depart="100.00" arrival="180.00" duration="80.00" waitingTime="10.00"/>
    <tripinfo id="late" depart="3500.00" arrival="-1.00" duration="100.00" waitingTime="40.00"/>
</tripinfos>
"""


class TripMetricTests(unittest.TestCase):
    def summary(self):
        return {"status": "completed", "metrics": {}, "checks": {}}

    def test_unfinished_trip_counts_until_the_end_of_the_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tripinfo.xml"
            path.write_text(TRIPINFO, encoding="utf-8")
            summary = complete_trip_metrics(self.summary(), path, departed_ids={"done", "late"}, arrived_ids={"done"})
        self.assertEqual(summary["metrics"]["ATT_s"], 90.)  # (80 + 100) / 2, not 80
        self.assertEqual(summary["metrics"]["AWT_s"], 25.)  # (10 + 40) / 2, not 10
        self.assertEqual(summary["status"], "completed")

    def test_tripinfo_must_match_departed_and_arrived_vehicles(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tripinfo.xml"
            path.write_text(TRIPINFO, encoding="utf-8")
            summary = complete_trip_metrics(self.summary(), path, departed_ids={"done"}, arrived_ids={"done"})
        self.assertEqual(summary["status"], "abnormal")


if __name__ == "__main__":
    unittest.main()
