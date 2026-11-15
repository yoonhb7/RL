"""Intended DQN variant differences; all tests use tensors/fakes, without SUMO."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch
from torch import nn

from src.agents.fourphase_data import ALGORITHMS, episode_order, read_config, split_seeds
from src.agents.fourphase_dqn import DQNAgent, DQNPolicy, DuelingQNetwork, QNetwork, td_targets


class TargetQ(nn.Module):
    def forward(self, state):
        return state[:, :2]


class OnlineQ(nn.Module):
    def forward(self, state):
        return state[:, :2].flip(-1)


class VariantTests(unittest.TestCase):
    def test_double_selects_online_but_evaluates_target_with_the_same_mask(self):
        states = torch.zeros((3, 13))
        states[:, :2] = torch.tensor([3., 9.])
        rewards = torch.tensor([-1., -1., -1.])
        terminal = torch.tensor([False, False, True])
        masks = torch.tensor([[True, True], [False, True], [False, False]])
        vanilla = td_targets(rewards, terminal, states, masks, TargetQ(), .9)
        double = td_targets(rewards, terminal, states, masks, TargetQ(), .9, online_network=OnlineQ())
        torch.testing.assert_close(vanilla, torch.tensor([7.1, 7.1, -1.]))
        torch.testing.assert_close(double, torch.tensor([1.7, 7.1, -1.]))

    def test_dueling_value_and_mean_centered_advantage_and_parameter_counts(self):
        network = DuelingQNetwork()
        with torch.no_grad():
            for parameter in network.parameters():
                parameter.zero_()
            network.value.bias.fill_(3)
            network.advantage.bias.copy_(torch.tensor([2., 6.]))
        torch.testing.assert_close(network(torch.zeros((2, 13))), torch.tensor([[1., 5.], [1., 5.]]))
        self.assertEqual(sum(p.numel() for p in QNetwork().parameters()), 5186)
        self.assertEqual(sum(p.numel() for p in network.parameters()), 5251)

    def test_only_double_agent_passes_online_network_to_target_calculation(self):
        state = np.zeros(13, np.float32)
        for algorithm in ALGORITHMS:
            config = read_config(algorithm=algorithm)
            config.update(learning_starts=1, batch_size=1, buffer_size=4)
            agent = DQNAgent(config, 5)
            with patch("src.agents.fourphase_dqn.td_targets", wraps=td_targets) as target:
                agent.observe(state, 0, -1, state, False, False, (True, True))
                agent.observe(state, 0, -1, state, False, True, (True, True))
                supplied = target.call_args.kwargs["online_network"]
                self.assertIs(supplied, agent.online if algorithm == "double_dqn" else None)

    def test_same_seed_preserves_case_order_splits_and_common_training_settings(self):
        configs = [read_config(episodes=200, seed=42, algorithm=algorithm) for algorithm in ALGORITHMS]
        for config in configs[1:]:
            self.assertEqual(episode_order(config), episode_order(configs[0]))
            self.assertEqual(split_seeds(config), split_seeds(configs[0]))
            self.assertEqual({k: v for k, v in config.items() if k != "algorithm"},
                             {k: v for k, v in configs[0].items() if k != "algorithm"})

    def test_vanilla_and_double_start_from_identical_network_parameters(self):
        vanilla = DQNAgent(read_config(algorithm="dqn"), 48000)
        double = DQNAgent(read_config(algorithm="double_dqn"), 48000)
        for key, value in vanilla.online.state_dict().items():
            torch.testing.assert_close(double.online.state_dict()[key], value)

    def test_all_variants_roundtrip_through_inference_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            for algorithm in ALGORITHMS:
                agent = DQNAgent(read_config(algorithm=algorithm), 48000)
                path = Path(temporary) / f"{algorithm}.pt"
                agent.save(path, {"network_sha256": "road", "env_settings": {}})
                policy = DQNPolicy(path, expected_network_sha256="road", expected_settings={})
                self.assertEqual(policy.algorithm, algorithm)
                self.assertEqual(policy.choose(np.zeros(13), (False, True)), 1)


if __name__ == "__main__":
    unittest.main()
