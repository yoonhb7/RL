"""Masked Bellman targets, replay isolation, schedule units and frozen data; no SUMO."""

import copy
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from torch import nn

from src.agents.fourphase_data import case_path, episode_order, prepare_run, read_config, split_seeds
from src.agents.fourphase_dqn import DQNAgent, DQNPolicy, QNetwork, ReplayBuffer, epsilon_at, td_targets, valid_action
from src.agents.fourphase_evaluation import validation_score
from src.traffic.experiments import sha256, write_json
from src.traffic.fourphase.scenario import read_settings


class EncodedQ(nn.Module):
    def forward(self, states):
        return states[:, :2]


class DQNMathTests(unittest.TestCase):
    def test_truncation_bootstraps_with_a_mask_but_true_termination_does_not(self):
        replay = ReplayBuffer(3)
        initial = np.zeros(21, np.float32)
        for values, terminated, truncated, mask in (
            ((1, 100), False, False, (True, False)),
            ((2, 9), False, True, (False, True)),
            ((7, 8), True, False, (False, False)),
        ):
            next_state = initial.copy()
            next_state[:2] = values
            replay.add(initial, 0, -2, next_state, terminated, truncated, mask)
        tensors = {key: torch.from_numpy(value) for key, value in replay.arrays.items()}
        targets = td_targets(tensors["rewards"], tensors["terminated"], tensors["next_states"],
                             tensors["next_masks"], EncodedQ(), .99)
        torch.testing.assert_close(targets, torch.tensor([-1.01, 6.91, -2]))
        self.assertTrue(tensors["truncated"][1])
        self.assertFalse(targets.requires_grad)

    def test_greedy_and_random_exploration_both_respect_valid_actions(self):
        state = np.zeros(21, np.float32)
        state[:2] = (1, 100)
        self.assertEqual(valid_action(EncodedQ(), state, (True, False), "cpu"), 0)
        rng = np.random.default_rng(3)
        for _ in range(40):
            self.assertEqual(valid_action(EncodedQ(), state, (False, True), "cpu", epsilon=1, rng=rng), 1)

    def test_final_next_state_is_copied_before_reset_and_buffer_has_a_cap(self):
        replay = ReplayBuffer(3)
        state = np.zeros(21, np.float32)
        next_state = np.ones(21, np.float32)
        replay.add(state, 0, -1, next_state, False, True, (True, False))
        next_state[:] = 999  # Simulate a reused/reset observation array.
        np.testing.assert_array_equal(replay.arrays["next_states"][0], np.ones(21))
        for _ in range(4):
            replay.add(state, 1, -1, state, False, False, (False, True))
        self.assertEqual((replay.size, replay.position), (3, 2))
        with self.assertRaises(ValueError):
            replay.add(state, 0, 0, state, False, True, (False, False))

    def test_initial_collection_update_count_and_target_copy_are_decision_based(self):
        config = read_config()
        config.update(buffer_size=16, batch_size=2, learning_starts=2, target_update_decisions=4)
        agent = DQNAgent(config, 8)
        original_target = copy.deepcopy(agent.target.state_dict())
        state = np.zeros(21, np.float32)
        for decision in range(1, 9):
            row = agent.observe(state, 0, -1, state, False, decision == 8, (True, True))
            self.assertEqual(agent.updates, max(0, decision - 2))
            self.assertEqual(agent.target_copies, decision // 4)
            if decision == 3:
                for key, value in original_target.items():
                    torch.testing.assert_close(agent.target.state_dict()[key], value)
            if decision in (4, 8):
                self.assertTrue(row["target_copied"])
                for key, value in agent.online.state_dict().items():
                    torch.testing.assert_close(agent.target.state_dict()[key], value)

    def test_parameter_count_epsilon_and_checkpoint_inference_contract(self):
        config = read_config()
        self.assertEqual(sum(p.numel() for p in QNetwork().parameters()), 11202)  # 21*128+128 + 128*64+64 + 64*2+2
        self.assertEqual(epsilon_at(0, 4800, config), 1)
        self.assertAlmostEqual(epsilon_at(3360, 4800, config), .01)
        self.assertAlmostEqual(epsilon_at(4800, 4800, config), .01)
        agent = DQNAgent(config, 4800)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.pt"
            agent.save(path, {"network_sha256": "road", "env_settings": {"protocol": 1}})
            policy = DQNPolicy(path, expected_network_sha256="road", expected_settings={"protocol": 1})
            self.assertEqual(policy.choose(np.zeros(21), (False, True)), 1)
            with self.assertRaises(ValueError):
                DQNPolicy(path, expected_network_sha256="different_road")


class FrozenDataTests(unittest.TestCase):
    def test_balanced_order_is_reproducible_and_split_seeds_are_disjoint(self):
        config = read_config()
        self.assertEqual(episode_order(config), episode_order(config))
        self.assertEqual(sorted(Counter(c["level"] for c in episode_order(config)).values()), [66, 67, 67])  # 200 episodes
        groups = split_seeds(config)
        self.assertFalse(set(groups["train"]) & set(groups["validation"]))
        config["validation_demand_seeds"] = [config["train_demand_seed_start"]]
        with self.assertRaises(ValueError):
            split_seeds(config)

    def test_cases_resolve_shared_network_and_detect_route_mutation(self):
        config = read_config(episodes=1)
        config.update(validation_demand_seeds=[20000])
        with tempfile.TemporaryDirectory() as temporary:
            source, output = Path(temporary) / "source", Path(temporary) / "run"
            source.mkdir()
            (source / "network.net.xml").write_text("<net/>")
            (source / "view.xml").write_text("<viewsettings/>")
            write_json(source / "manifest.json", {"settings": read_settings(), "sha256": {
                name: sha256(source / name) for name in ("network.net.xml", "view.xml")}})
            manifest = prepare_run(output, source, config)
            case = manifest["cases"]["train"][0]
            path = case_path(output, manifest, case)
            self.assertEqual((path / "../../../network.net.xml").resolve(), output / "network.net.xml")
            self.assertEqual(len(manifest["cases"]["validation"]), 3)
            self.assertNotIn("test", manifest["cases"])
            self.assertEqual((source / "network.net.xml").read_text(), "<net/>")
            with (path / "demand.rou.xml").open("a") as stream:
                stream.write("<!-- mutation -->")
            with self.assertRaises(ValueError):
                case_path(output, manifest, case)

    def test_validation_ATT_weights_levels_equally_and_refuses_to_drop_abnormal_cases(self):
        records = [{"level": level, "status": "completed", "metrics": {"ATT_s": score}}
                   for level, score in (("low", 3), ("medium", 6), ("high", 12))]
        score, levels = validation_score(records)
        self.assertEqual(score, 7)
        self.assertEqual(levels["high"], 12)
        records[-1]["status"] = "abnormal"
        with self.assertRaises(ValueError):
            validation_score(records)


if __name__ == "__main__":
    unittest.main()
