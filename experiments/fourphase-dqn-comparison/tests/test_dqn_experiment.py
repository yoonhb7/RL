"""Protocol and inference checks; never start SUMO or train a model."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np

from src.agents.dqn import DQNController, read_dqn_config
from src.agents.evaluation import audit_signals
from src.traffic.demand_builder import write_demand
from src.traffic.experiments import ROOT, case_paths, prepare_run, sha256, validate_splits


class ExperimentProtocolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.config = read_dqn_config(timesteps=5000)
        self.config.update(train_demand_seeds=[100], validation_demand_seeds=[1000], test_demand_seeds=[2000])
        self.traffic = json.loads((ROOT / "configs" / "toy.json").read_text(encoding="utf-8"))

    def test_training_requires_optimizer_updates_after_initial_collection(self):
        with self.assertRaises(ValueError):
            read_dqn_config(timesteps=1000)
        self.assertEqual(self.config["train_freq"], 4)

    def test_overlapping_or_duplicate_demand_seeds_are_rejected(self):
        for changes in ({"test_demand_seeds": [100]}, {"train_demand_seeds": [100, 100]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_splits({**self.config, **changes})

    def test_demand_generator_preserves_existing_scenario_bytes(self):
        original = ROOT / "sumo" / "toy"
        metadata = json.loads((original / "demand.json").read_text(encoding="utf-8"))
        write_demand(self.folder / "generated", metadata["config"], metadata["seed"])
        self.assertEqual((self.folder / "generated" / "toy.rou.xml").read_bytes(), (original / "toy.rou.xml").read_bytes())

    def test_scenario_preparation_is_disjoint_and_preserves_original_input(self):
        original = ROOT / "sumo" / "toy" / "toy.rou.xml"
        digest = sha256(original)
        run = self.folder / "experiment"
        manifest = prepare_run(run, self.config, {"warmup_seconds": 120, "duration_seconds": 1200})
        routes = [case_paths(run, manifest["cases"][split][0])[1] for split in ("train", "validation", "test")]
        self.assertEqual(len(set(routes)), 3)
        self.assertEqual(len({sha256(path) for path in routes}), 3)
        self.assertEqual(sha256(original), digest)
        with self.assertRaises(ValueError):
            prepare_run(run, self.config, {})

    def test_modified_frozen_input_is_detected_before_evaluation(self):
        run = self.folder / "experiment"
        manifest = prepare_run(run, self.config, {})
        case = manifest["cases"]["test"][0]
        _, route = case_paths(run, case)
        route.write_bytes(route.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            case_paths(run, case)

    def test_model_preview_uses_deterministic_inference(self):
        model = Mock()
        model.predict.return_value = (np.asarray(1), None)
        policy = DQNController(model)
        observation = np.zeros(16, dtype=np.float32)
        self.assertEqual(policy.choose_action(observation, {}), 1)
        model.predict.assert_called_once_with(observation, deterministic=True)


class SignalAuditTests(unittest.TestCase):
    def test_safe_order_and_clearance_times_pass(self):
        rows = [
            {"time_s": 10, "phase_index": 0, "phase_elapsed_s": 10},
            {"time_s": 11, "phase_index": 1, "phase_elapsed_s": 1},
            {"time_s": 14, "phase_index": 2, "phase_elapsed_s": 1},
            {"time_s": 15, "phase_index": 3, "phase_elapsed_s": 1},
        ]
        self.assertEqual(audit_signals(rows, 10, 60), [])

    def test_skipping_yellow_is_detected(self):
        rows = [
            {"time_s": 10, "phase_index": 0, "phase_elapsed_s": 10},
            {"time_s": 11, "phase_index": 3, "phase_elapsed_s": 1},
        ]
        self.assertIn("phase_order", [row["reason"] for row in audit_signals(rows, 10, 60)])

    def test_maximum_green_violation_is_detected(self):
        rows = [
            {"time_s": 60, "phase_index": 0, "phase_elapsed_s": 60},
            {"time_s": 62, "phase_index": 1, "phase_elapsed_s": 1},
        ]
        self.assertIn("phase_duration", [row["reason"] for row in audit_signals(rows, 10, 60)])


if __name__ == "__main__":
    unittest.main()
