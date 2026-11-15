"""Cached reports must not mix cases, discard failed runs or use the wrong checkpoint."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.report_fourphase import aggregate, checked_records, collect, digest


def sample_records(controller):
    return [{"case_id": f"{level}_7", "level": level, "demand_seed": 7, "sumo_seed": 7,
             "controller": controller, "status": "completed", "failure": None, "time_s": 3600,
             "checks": {"full_observation_window": True}, "switches": 140,
             "counts": {"scheduled_due": 10, "departed": 10, "arrived": 8, "unfinished": 2, "pending_due": 0},
             "metrics": {"J_s_per_due_vehicle": 3., "ATT_completed_s": 100., "AQL_in_vehicles": 25 / 3600,
                         "throughput_vehicles": 8, "W_stop_in_vehicle_s": 25., "W_pending_vehicle_s": 5.}}
            for level in ("low", "medium", "high")]


class CachedReportTests(unittest.TestCase):
    def build_run(self, folder, algorithm):
        folder.mkdir()
        (folder / "network.net.xml").write_text("road")
        cases = []
        for level in ("low", "medium", "high"):
            path = folder / level
            path.mkdir()
            (path / "demand.xml").write_text(level)
            cases.append({"id": f"{level}_7", "level": level, "demand_seed": 7, "sumo_seed": 7,
                          "scheduled_due": 10, "folder": level, "sha256": {"demand.xml": digest(path / "demand.xml")}})
        manifest = {"algorithm": algorithm, "config": {"algorithm": algorithm, "seed": 42, "episodes": 3, "learning_starts": 1},
                    "env_settings": {"duration_seconds": 3600}, "network_sha256": digest(folder / "network.net.xml"),
                    "cases": {"validation": cases}}
        controller = "fixed" if algorithm == "fixed" else f"{algorithm}_greedy"
        summary = {"split": "validation", "J_equal_level_mean": 3., "runs": sample_records(controller)}
        files = {"manifest.json": manifest, "selected.json": summary,
                 "training_summary.json": {"algorithm": algorithm, "seed": 42, "status": "completed",
                                           "actual_decisions": 3, "optimizer_updates": 2}}
        for name, data in files.items():
            (folder / name).write_text(json.dumps(data))
        (folder / "best_model.pt").write_bytes(b"opaque; report must not load a model")
        (folder / "selection.json").write_text(json.dumps({"folder": ".", "checkpoint": "best_model.pt", "J": 3., "decisions": 3,
            "checkpoint_sha256": digest(folder / "best_model.pt"),
            "validation_summary_sha256": digest(folder / "selected.json")}))
        # The selected directory uses summary.json. A later unrelated file must not be used.
        (folder / "summary.json").write_bytes((folder / "selected.json").read_bytes())
        (folder / "validations.jsonl").write_text(json.dumps({"decisions": 3, "J": 3.,
            "J_by_level": {level: 3. for level in ("low", "medium", "high")}}) + "\n")
        episodes = [{"episode": i, "level": level, "global_decisions": i, "raw_reward_sum": -3.,
                     "mean_R1": -1., "epsilon": .5, "replay_size": i, "optimizer_updates": i - 1,
                     "checks": {"valid": True}} for i, level in enumerate(("low", "medium", "high"), 1)]
        updates = [{"decision": i, "epsilon": .5, "replay_size": i, "optimizer_updates": max(0, i - 1),
                    "loss": None if i == 1 else 1., "mean_q": -1., "mean_target": -2.} for i in range(1, 4)]
        for filename, values in (("episodes.jsonl", episodes), ("updates.jsonl", updates)):
            (folder / filename).write_text("".join(json.dumps(row) + "\n" for row in values))
        (folder / "unselected_later_summary.json").write_text("{}")
        return manifest, summary

    def test_reads_selected_cached_results_and_rejects_changed_demand(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folders = [root / name for name in ("dqn", "double_dqn", "dueling_dqn")]
            for folder in folders:
                self.build_run(folder, folder.name)
            fixed = root / "fixed"
            self.build_run(fixed, "fixed")
            report = collect(folders, fixed, fixed / "summary.json")
            self.assertEqual(len(report["rows"]), 12)
            self.assertEqual(report["test_cases_run"], 0)
            self.assertEqual(report["new_simulations_run"], 0)
            self.assertEqual(report["rows"][3]["J_s_per_due_vehicle"], 3.)
            (folders[1] / "low/demand.xml").write_text("changed")
            with self.assertRaisesRegex(ValueError, "validation input changed"):
                collect(folders, fixed, fixed / "summary.json")

    def test_partial_failed_and_wrong_split_results_are_not_silently_averaged(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest, summary = self.build_run(Path(temporary) / "run", "dqn")
            for kind in ("partial", "failure", "test", "wrong_j"):
                value = copy.deepcopy(summary)
                if kind == "partial":
                    value["runs"].pop()
                elif kind == "failure":
                    value["runs"][0]["checks"]["full_observation_window"] = False
                elif kind == "test":
                    value["split"] = "test"
                else:
                    value["runs"][0]["metrics"]["J_s_per_due_vehicle"] = 0.
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    checked_records(value, manifest, "dqn")

    def test_ATT_is_a_mean_of_case_means_not_a_pooled_completed_vehicle_mean(self):
        records = sample_records("dqn_greedy")
        extra = copy.deepcopy(records[0])
        extra["metrics"]["ATT_completed_s"] = 200.
        extra["counts"]["arrived"] = 1
        rows = aggregate(records + [extra], "dqn", 42)
        self.assertEqual(rows[0]["ATT_completed_s"], 150.)
        self.assertAlmostEqual(rows[0]["ATT_completed_s_sd_demand"], 70.7106781187)


if __name__ == "__main__":
    unittest.main()
