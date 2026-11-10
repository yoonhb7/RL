import numpy as np
import pytest
import torch

from traffic_rl.dqn import DQNAgent, bootstrap_values


def test_target_mask_and_double_dqn_selection():
    online = torch.tensor([[1., 4., 999.], [8., 3., 999.]])
    target = torch.tensor([[6., 2., 999.], [1., 5., 999.]])
    mask = torch.tensor([[True, True, False], [True, True, False]])
    assert bootstrap_values(online, target, mask, False).tolist() == [6., 5.]
    assert bootstrap_values(online, target, mask, True).tolist() == [2., 1.]


def test_exploration_and_inference_obey_masks():
    agent = DQNAgent(np.int64(3), np.int64(4))
    obs = np.zeros(3, dtype=np.float32)
    mask = np.array([False, False, True, False])
    assert all(agent.act(obs, mask, epsilon=1) == 2 for _ in range(100))
    assert agent.act(obs, mask, epsilon=0) == 2


def test_checkpoint_checks_semantics_not_only_shape(tmp_path):
    agent = DQNAgent(np.int64(3), np.int64(4))
    path = tmp_path / "model.pt"
    schema = {"lanes": ["N", "E"], "network": "one"}
    agent.save(path, schema, {"training_seeds": [0]})
    loaded = DQNAgent.load(path, schema)
    assert loaded.actions == 4
    with pytest.raises(ValueError, match="mismatch"):
        DQNAgent.load(path, {"lanes": ["E", "N"], "network": "one"})
