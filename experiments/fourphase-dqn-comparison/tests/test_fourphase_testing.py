"""Held-out protocol, immutable inputs, no training, and failure accounting; no SUMO."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.agents.fourphase_data import episode_order, read_config
from src.agents.fourphase_results import digest, read_json
from src.agents.fourphase_testing import (assert_frozen, build_comparison, prepare_test,
    protocol_for, replot_test, run_test, signal_values)
from src.traffic.experiments import write_json


def records_for(cases, controller):
    label = "fixed" if controller == "fixed" else f"{controller}_greedy"
    return [{"case_id": case["id"], "level": case["level"], "demand_seed": case["demand_seed"],
             "sumo_seed": case["sumo_seed"], "controller": label, "status": "completed", "failure": None,
             "time_s": 3600, "sumo_version": [22, "SUMO 1.28.0"], "switches": 100,
             "tls_phase_seconds": [800, 75, 25] * 4, "checks": {"valid": True},
             "counts": {"scheduled_due": 100, "departed": 95, "arrived": 90, "unfinished": 5, "pending_due": 5},
             "metrics": {"J_s_per_due_vehicle": 10., "ATT_completed_s": 120., "AQL_in_vehicles": .25,
                         "throughput_vehicles": 90, "W_stop_in_vehicle_s": 900, "W_pending_vehicle_s": 100}}
            for case in cases]


def group_result(manifest, controller, split="test"):
    return {"split": split, "selection_allowed": split == "validation", "J_equal_level_mean": 10.,
            "runs": records_for(manifest["cases"][split], controller)}


class HeldOutEvaluationTests(unittest.TestCase):
    def create_runs(self, root):
        folders = []
        for algorithm in ("dqn", "double_dqn", "dueling_dqn"):
            folder = root / algorithm
            folder.mkdir()
            folders.append(folder)
            config = read_config(episodes=200, seed=42, algorithm=algorithm)
            (folder / "network.net.xml").write_text("<net/>")
            cases = {"train": [{"demand_seed": 10000}], "validation": [], "test": []}
            for split in ("validation", "test"):
                for level in ("low", "medium", "high"):
                    for seed in config[f"{split}_demand_seeds"]:
                        relative = Path("scenarios") / split / f"{level}_seed_{seed}"
                        path = folder / relative
                        path.mkdir(parents=True)
                        (path / "demand.xml").write_text(f"{level}:{seed}")
                        cases[split].append({"id": path.name, "level": level, "demand_seed": seed, "sumo_seed": seed,
                            "scheduled_due": 100, "folder": str(relative), "sha256": {"demand.xml": digest(path / "demand.xml")}})
            manifest = {"algorithm": algorithm, "config": config, "episode_order": episode_order(config),
                        "env_settings": {"duration_seconds": 3600}, "network_sha256": digest(folder / "network.net.xml"),
                        "observation_size": 13, "actions": {"0": "hold", "1": "next_phase"}, "cases": cases}
            write_json(folder / "manifest.json", manifest)
            write_json(folder / "training_summary.json", {"status": "completed", "algorithm": algorithm, "seed": 42,
                "episodes_completed": 200, "actual_decisions": 48000})
            selected = folder / "validation/step_004800"
            selected.mkdir(parents=True)
            write_json(selected / "summary.json", group_result(manifest, algorithm, "validation"))
            (folder / "best_model.pt").write_bytes(algorithm.encode())
            (folder / "last_model.pt").write_bytes(b"unselected last checkpoint")
            write_json(folder / "selection.json", {"episode": 20, "decisions": 4800, "J": 10.,
                "folder": "validation/step_004800", "checkpoint": "best_model.pt", "checkpoint_sha256": digest(folder / "best_model.pt"),
                "validation_summary_sha256": digest(selected / "summary.json")})
            (folder / "validations.jsonl").write_text("".join(json.dumps({"decisions": number * 240,
                "J": 10. if number == 20 else 11., "folder": f"validation/step_{number * 240:06d}"}) + "\n" for number in range(20, 201, 20)))
        return folders

    def policy_factory(self, model, **kwargs):
        self.assertEqual(model.name, "best_model.pt")
        manifest = read_json(model.parent / "manifest.json")
        self.assertEqual(kwargs["expected_network_sha256"], manifest["network_sha256"])
        return SimpleNamespace(algorithm=manifest["algorithm"], decisions=4800,
                               metadata={"manifest_sha256": digest(model.parent / "manifest.json")})

    def evaluator(self, folder, manifest, split, output, *, policy):
        self.assertEqual(split, "test")
        controller = "fixed" if policy is None else policy.algorithm
        output.mkdir(parents=True)
        result = group_result(manifest, controller)
        write_json(output / "summary.json", result)
        return result

    def reporter(self, report, output):
        write_json(output / "comparison.json", report)

    def test_all_four_use_the_canonical_test_inputs_without_training(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = prepare_test(self.create_runs(root))
            output = root / "evaluation"
            calls = []

            def evaluate(folder, manifest, split, target, *, policy):
                self.assertTrue((output / "protocol.json").is_file())
                self.assertEqual(folder, prepared[0]["folder"])
                self.assertIs(manifest, prepared[0]["manifest"])
                calls.append(target.name)
                return self.evaluator(folder, manifest, split, target, policy=policy)

            report = run_test(prepared, output, policy_factory=self.policy_factory, evaluator=evaluate, reporter=self.reporter)
            self.assertEqual(calls, ["fixed", "dqn", "double_dqn", "dueling_dqn"])
            self.assertEqual(report["test_cases_run"], 60)
            self.assertEqual(len(report["signal_rows"]), 12)
            self.assertFalse(report["selection_allowed"])
            self.assertEqual(read_json(output / "summary.json")["unattempted"], 0)
            self.assertEqual(report["J_equal_level_mean"]["dqn"], 10.)
            assert_frozen(prepared)

    def test_changed_test_input_and_train_test_overlap_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            folders = self.create_runs(Path(temporary))
            manifest = read_json(folders[0] / "manifest.json")
            case = manifest["cases"]["test"][0]
            path = folders[0] / case["folder"] / "demand.xml"
            original = path.read_bytes()
            path.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "Frozen case input changed"):
                prepare_test(folders)
            path.write_bytes(original)
            manifest["cases"]["train"][0]["demand_seed"] = case["demand_seed"]
            write_json(folders[0] / "manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "disjoint"):
                prepare_test(folders)

    def test_abnormal_case_stops_remaining_controllers_and_is_not_averaged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = prepare_test(self.create_runs(root))
            output = root / "failed"

            def evaluate(folder, manifest, split, target, *, policy):
                if policy is None:
                    return self.evaluator(folder, manifest, split, target, policy=policy)
                target.mkdir()
                write_json(target / "summary.json", {"runs": [{"case_id": manifest["cases"]["test"][0]["id"], "status": "abnormal"}]})
                raise RuntimeError("collision fixture")

            with self.assertRaisesRegex(RuntimeError, "collision fixture"):
                run_test(prepared, output, policy_factory=self.policy_factory, evaluator=evaluate, reporter=self.reporter)
            summary = read_json(output / "summary.json")
            self.assertEqual((summary["completed"], summary["abnormal"], summary["unattempted"]), (15, 1, 44))
            self.assertFalse((output / "double_dqn").exists())
            self.assertFalse((output / "comparison.json").exists())

    def test_source_changes_during_evaluation_stop_before_the_next_controller(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = prepare_test(self.create_runs(root))
            output = root / "changed_source"

            def evaluate(folder, manifest, split, target, *, policy):
                result = self.evaluator(folder, manifest, split, target, policy=policy)
                prepared[0]["model"].write_bytes(b"concurrently replaced checkpoint")
                return result

            with self.assertRaisesRegex(ValueError, "source changed"):
                run_test(prepared, output, policy_factory=self.policy_factory, evaluator=evaluate, reporter=self.reporter)
            self.assertFalse((output / "dqn").exists())
            self.assertEqual(read_json(output / "summary.json")["completed"], 15)

    def test_nonminimum_validation_checkpoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            folders = self.create_runs(Path(temporary))
            path = folders[0] / "validations.jsonl"
            values = [json.loads(line) for line in path.read_text().splitlines()]
            values[1]["J"] = 5.
            path.write_text("".join(json.dumps(value) + "\n" for value in values))
            with self.assertRaisesRegex(ValueError, "validation minimum"):
                prepare_test(folders)

    def test_plot_failure_can_be_recovered_without_repeating_evaluation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = prepare_test(self.create_runs(root))
            output = root / "plot_failure"

            def failed_plot(report, target):
                self.reporter(report, target)
                raise RuntimeError("plot fixture")

            with self.assertRaises(RuntimeError):
                run_test(prepared, output, policy_factory=self.policy_factory, evaluator=self.evaluator, reporter=failed_plot)
            self.assertEqual(read_json(output / "summary.json")["status"], "report_failed")
            with patch("src.agents.fourphase_testing.write_test_report", side_effect=self.reporter):
                report = replot_test(output)
            self.assertEqual(report["test_cases_run"], 60)
            self.assertEqual(read_json(output / "summary.json")["status"], "completed")

    def test_validation_data_and_incomplete_signal_exposures_cannot_be_reported_as_test(self):
        with tempfile.TemporaryDirectory() as temporary:
            prepared = prepare_test(self.create_runs(Path(temporary)))
            manifest = prepared[0]["manifest"]
            results = {name: group_result(manifest, name) for name in ("fixed", "dqn", "double_dqn", "dueling_dqn")}
            results["dqn"]["split"] = "validation"
            with self.assertRaises(ValueError):
                build_comparison(protocol_for(prepared), results)
            run = results["fixed"]["runs"][0]
            run["tls_phase_seconds"][0] += 1
            with self.assertRaises(ValueError):
                signal_values(run)


if __name__ == "__main__":
    unittest.main()
