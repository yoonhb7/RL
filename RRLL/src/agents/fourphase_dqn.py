"""DQN, Double DQN and pure Dueling: shared masks, replay, budget and truncation."""

import copy
import math
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from src.traffic.fourphase.scenario import OBSERVATION_SIZE

# Fully connected 128-64 layers, as in the FC part of Genders & Razavi (2016) and Gao et al. (2017).
HIDDEN_SIZES = (128, 64)


class QNetwork(nn.Module):
    def __init__(self):
        super().__init__()
        first, second = HIDDEN_SIZES
        self.layers = nn.Sequential(nn.Linear(OBSERVATION_SIZE, first), nn.ReLU(), nn.Linear(first, second), nn.ReLU(),
                                    nn.Linear(second, 2))

    def forward(self, state):
        return self.layers(state)


class DuelingQNetwork(nn.Module):
    def __init__(self):
        super().__init__()
        first, second = HIDDEN_SIZES
        self.features = nn.Sequential(nn.Linear(OBSERVATION_SIZE, first), nn.ReLU(), nn.Linear(first, second), nn.ReLU())
        self.value = nn.Linear(second, 1)
        self.advantage = nn.Linear(second, 2)

    def forward(self, state):
        features = self.features(state)
        advantage = self.advantage(features)
        return self.value(features) + advantage - advantage.mean(dim=-1, keepdim=True)


def make_network(algorithm):
    if algorithm == "dueling_dqn":
        return DuelingQNetwork()
    if algorithm in ("dqn", "double_dqn"):
        return QNetwork()
    raise ValueError(f"Unknown DQN variant: {algorithm}")


def masked_argmax(q_values, masks):
    if q_values.shape != masks.shape or masks.dtype != torch.bool or not masks.any(dim=-1).all():
        raise ValueError("Every nonterminal observation needs at least one valid action")
    if not torch.isfinite(q_values).all():
        raise RuntimeError("Non-finite Q values")
    return q_values.masked_fill(~masks, -torch.inf).argmax(dim=-1)


@torch.no_grad()
def td_targets(rewards, terminated, next_states, next_masks, target_network, gamma, *, online_network=None):
    # `truncated` is intentionally not a bootstrap mask. End-of-window next
    # states/masks come from the final physical state before reset.
    values = torch.zeros_like(rewards)
    continuing = ~terminated
    if continuing.any():
        q_values = target_network(next_states[continuing])
        valid = next_masks[continuing]
        # Double selects with online and evaluates with target. Pure Dueling
        # leaves online_network=None and uses the vanilla DQN target maximum.
        selection_values = q_values if online_network is None else online_network(next_states[continuing])
        actions = masked_argmax(selection_values, valid)
        values[continuing] = q_values.gather(1, actions[:, None]).squeeze(1)
    return rewards + gamma * values


class ReplayBuffer:
    def __init__(self, capacity):
        self.capacity, self.size, self.position = int(capacity), 0, 0
        if self.capacity <= 0:
            raise ValueError("Replay capacity must be positive")
        self.arrays = {"states": np.zeros((capacity, OBSERVATION_SIZE), dtype=np.float32),
                       "next_states": np.zeros((capacity, OBSERVATION_SIZE), dtype=np.float32),
                       "actions": np.zeros(capacity, dtype=np.int64),
                       "rewards": np.zeros(capacity, dtype=np.float32),
                       "terminated": np.zeros(capacity, dtype=bool),
                       "truncated": np.zeros(capacity, dtype=bool),
                       "next_masks": np.zeros((capacity, 2), dtype=bool)}

    def add(self, state, action, reward, next_state, terminated, truncated, next_mask):
        state, next_state = np.asarray(state, dtype=np.float32), np.asarray(next_state, dtype=np.float32)
        mask = np.asarray(next_mask, dtype=bool)
        if state.shape != (OBSERVATION_SIZE,) or next_state.shape != (OBSERVATION_SIZE,) or not np.isfinite(state).all() or not np.isfinite(next_state).all():
            raise ValueError(f"Replay observations must be {OBSERVATION_SIZE} finite values")
        if type(action) is not int or action not in (0, 1) or not math.isfinite(reward):
            raise ValueError("Invalid replay action/reward")
        if mask.shape != (2,) or (not terminated and not mask.any()):
            raise ValueError("The final truncation mask must retain valid next actions")
        values = {"states": state, "actions": action, "rewards": reward, "next_states": next_state,
                  "terminated": terminated, "truncated": truncated, "next_masks": mask}
        for name, value in values.items():
            self.arrays[name][self.position] = value  # Copies; a later reset cannot replace next_state.
        self.position = (self.position + 1) % self.capacity
        self.size = min(self.capacity, self.size + 1)

    def sample(self, count, rng, device):
        if count > self.size:
            raise ValueError("Not enough replay samples")
        indices = rng.choice(self.size, count, replace=False)
        return {name: torch.as_tensor(array[indices], device=device) for name, array in self.arrays.items()}

    def state_dict(self):
        return {"capacity": self.capacity, "size": self.size, "position": self.position,
                "arrays": {name: torch.from_numpy(array[:self.size].copy()) for name, array in self.arrays.items()}}


def epsilon_at(decisions, budget, config):
    fraction = min(1.0, decisions / max(1.0, budget * config["epsilon_fraction"]))
    return config["epsilon_initial"] + fraction * (config["epsilon_final"] - config["epsilon_initial"])


def valid_action(network, state, mask, device, *, epsilon=0.0, rng=None):
    mask = np.asarray(mask, dtype=bool)
    if mask.shape != (2,) or not mask.any():
        raise ValueError("Choose an action only from a nonempty valid mask")
    if epsilon and rng is not None and rng.random() < epsilon:
        return int(rng.choice(np.flatnonzero(mask)))
    with torch.no_grad():
        values = network(torch.as_tensor(np.asarray(state, dtype=np.float32), device=device).unsqueeze(0))
        return int(masked_argmax(values, torch.as_tensor(mask, device=device).unsqueeze(0)).item())


class DQNAgent:
    def __init__(self, config, budget):
        self.config, self.budget = dict(config), budget
        self.algorithm = config["algorithm"]
        self.device = torch.device(config["device"])
        torch.set_num_threads(config["torch_threads"])
        torch.manual_seed(config["seed"])
        if self.device.type == "cuda":
            if not torch.cuda.is_available():
                raise ValueError("CUDA requested but unavailable")
            torch.cuda.manual_seed_all(config["seed"])
        torch.use_deterministic_algorithms(True)
        self.online = make_network(self.algorithm).to(self.device)
        self.target = copy.deepcopy(self.online).eval()
        self.target.requires_grad_(False)
        self.optimizer = torch.optim.Adam(self.online.parameters(), lr=config["learning_rate"])
        self.replay = ReplayBuffer(config["buffer_size"])
        explore_seed, replay_seed = np.random.SeedSequence(config["seed"]).spawn(2)
        self.exploration_rng = np.random.default_rng(explore_seed)
        self.replay_rng = np.random.default_rng(replay_seed)
        self.decisions = self.updates = self.target_copies = 0

    @property
    def epsilon(self):
        return epsilon_at(self.decisions, self.budget, self.config)

    def choose(self, state, mask, *, greedy=False):
        epsilon = 0.0 if greedy else (1.0 if self.decisions < self.config["learning_starts"] else self.epsilon)
        return valid_action(self.online, state, mask, self.device, epsilon=epsilon, rng=self.exploration_rng)

    def observe(self, state, action, reward, next_state, terminated, truncated, next_mask):
        self.replay.add(state, action, reward, next_state, terminated, truncated, next_mask)
        self.decisions += 1
        result = {"decision": self.decisions, "epsilon": self.epsilon, "replay_size": self.replay.size,
                  "optimizer_updates": self.updates, "loss": None, "target_copied": False}
        # First 1000 decisions collect experience; update 1 starts at decision 1001.
        if self.decisions > self.config["learning_starts"] and self.replay.size >= self.config["batch_size"]:
            batch = self.replay.sample(self.config["batch_size"], self.replay_rng, self.device)
            target = td_targets(batch["rewards"], batch["terminated"], batch["next_states"],
                                batch["next_masks"], self.target, self.config["gamma"],
                                online_network=self.online if self.algorithm == "double_dqn" else None)
            prediction = self.online(batch["states"]).gather(1, batch["actions"][:, None]).squeeze(1)
            loss = F.smooth_l1_loss(prediction, target)
            if not torch.isfinite(loss):
                raise RuntimeError("Non-finite DQN loss")
            self.optimizer.zero_grad(set_to_none=True)
            loss.backward()
            if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in self.online.parameters()):
                raise RuntimeError("Non-finite DQN gradient")
            self.optimizer.step()
            self.updates += 1
            result.update(loss=float(loss.item()), optimizer_updates=self.updates,
                          mean_target=float(target.mean().item()), mean_q=float(prediction.mean().item()))
        if self.decisions % self.config["target_update_decisions"] == 0:
            self.target.load_state_dict(self.online.state_dict())
            self.target_copies += 1
            result["target_copied"] = True
        result["target_copies"] = self.target_copies
        return result

    def save(self, path, metadata):
        path = Path(path)
        payload = {"format": "fourphase_dqn_v2", "algorithm": self.algorithm, "config": self.config,
                   "online": self.online.state_dict(), "target": self.target.state_dict(),
                   "optimizer": self.optimizer.state_dict(), "replay": self.replay.state_dict(),
                   "decisions": self.decisions, "updates": self.updates, "target_copies": self.target_copies,
                   "decision_budget": self.budget, "exploration_rng": self.exploration_rng.bit_generator.state,
                   "replay_rng": self.replay_rng.bit_generator.state, "torch_rng": torch.get_rng_state(),
                   "metadata": metadata}
        temporary = path.with_suffix(path.suffix + ".tmp")
        torch.save(payload, temporary)
        temporary.replace(path)


class DQNPolicy:
    """Evaluation/GUI inference only: no replay or optimizer updates."""
    def __init__(self, path, *, expected_network_sha256=None, expected_settings=None):
        payload = torch.load(Path(path), map_location="cpu", weights_only=True)
        if payload.get("format") != "fourphase_dqn_v2" or payload.get("algorithm") not in ("dqn", "double_dqn", "dueling_dqn"):
            raise ValueError(f"Expected a {OBSERVATION_SIZE}-observation fourphase_dqn_v2 checkpoint; retrain older 13-observation models")
        self.metadata = payload["metadata"]
        self.algorithm = payload["algorithm"]
        if expected_network_sha256 and self.metadata["network_sha256"] != expected_network_sha256:
            raise ValueError("Checkpoint was trained on a different road network")
        if expected_settings is not None and self.metadata["env_settings"] != expected_settings:
            raise ValueError("Checkpoint environment settings differ from the loaded SUMO scenario")
        torch.set_num_threads(payload["config"]["torch_threads"])
        self.network = make_network(self.algorithm).eval()
        self.network.load_state_dict(payload["online"])
        self.decisions = payload["decisions"]

    def choose(self, state, mask, *, greedy=True):
        return valid_action(self.network, state, mask, torch.device("cpu"))
