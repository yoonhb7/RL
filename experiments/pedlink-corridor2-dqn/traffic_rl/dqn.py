from __future__ import annotations

from collections import deque
import copy
import csv
from pathlib import Path
import random

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .common import write_json


def network(obs_size, actions):
    return nn.Sequential(nn.Linear(obs_size, 128), nn.ReLU(), nn.Linear(128, 128), nn.ReLU(), nn.Linear(128, actions))


def masked_values(q, mask):
    if not torch.all(mask.any(dim=-1)):
        raise ValueError("every next state requires a nonempty legal action set")
    return q.masked_fill(~mask, -torch.inf)


def bootstrap_values(online_q, target_q, masks, double=False):
    if double:
        selected = masked_values(online_q, masks).argmax(dim=1, keepdim=True)
        return target_q.gather(1, selected).squeeze(1)
    return masked_values(target_q, masks).max(dim=1).values


class DQNAgent:
    def __init__(self, obs_size, actions, seed=0, double=False, learning_rate=1e-3):
        obs_size, actions = int(obs_size), int(actions)
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.set_num_threads(1)
        self.rng = random.Random(seed)
        self.online = network(obs_size, actions)
        self.target = copy.deepcopy(self.online).eval()
        self.optimizer = torch.optim.Adam(self.online.parameters(), lr=learning_rate)
        self.memory = deque(maxlen=50000)
        self.double = double
        self.updates = 0
        self.obs_size, self.actions = obs_size, actions

    def act(self, obs, mask, epsilon=0.0):
        if self.rng.random() < epsilon:
            return int(self.rng.choice(np.flatnonzero(mask).tolist()))
        with torch.no_grad():
            q = self.online(torch.as_tensor(obs).unsqueeze(0))
            return int(masked_values(q, torch.as_tensor(mask).unsqueeze(0)).argmax().item())

    def learn(self, batch_size=64, gamma=0.99):
        batch = self.rng.sample(self.memory, batch_size)
        states, actions, rewards, next_states, dones, masks = zip(*batch)
        states = torch.as_tensor(np.array(states), dtype=torch.float32)
        next_states = torch.as_tensor(np.array(next_states), dtype=torch.float32)
        actions = torch.as_tensor(actions, dtype=torch.int64)
        rewards = torch.as_tensor(rewards, dtype=torch.float32)
        dones = torch.as_tensor(dones, dtype=torch.float32)
        masks = torch.as_tensor(np.array(masks), dtype=torch.bool)
        with torch.no_grad():
            values = bootstrap_values(self.online(next_states), self.target(next_states), masks, self.double)
            targets = rewards + gamma * (1 - dones) * values
        current = self.online(states).gather(1, actions[:, None]).squeeze(1)
        loss = F.smooth_l1_loss(current, targets)
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.online.parameters(), 10.0)
        self.optimizer.step()
        self.updates += 1
        if self.updates % 250 == 0:
            self.target.load_state_dict(self.online.state_dict())
        return float(loss.item())

    def save(self, path, schema, metadata):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"state_dict": self.online.state_dict(), "obs_size": self.obs_size, "actions": self.actions, "double": self.double, "schema": schema, "metadata": metadata}, path)

    @classmethod
    def load(cls, path, schema):
        data = torch.load(path, map_location="cpu", weights_only=True)
        if data["schema"] != schema:
            raise ValueError("Checkpoint network/observation/signal configuration mismatch. Train a new model.")
        agent = cls(data["obs_size"], data["actions"], double=data["double"])
        agent.online.load_state_dict(data["state_dict"])
        agent.target.load_state_dict(data["state_dict"])
        agent.metadata = data["metadata"]
        return agent


def train(env, output, episodes=50, seed=0, double=False):
    if episodes < 1 or seed < 0:
        raise ValueError("episodes must be positive, seed nonnegative")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    agent = DQNAgent(env.observation_space.shape[0], env.action_space.n, seed=seed, double=double)
    # Decision steps, not SUMO seconds, control replay / gradient updates.
    estimated_steps = episodes * env.manifest["horizon_seconds"] // env.manifest["decision_seconds"]
    step_count = 0
    meta = {"algorithm": "Double-DQN" if double else "DQN", "episodes": episodes, "training_seeds": list(range(seed, seed + episodes)), "gamma": 0.99, "learning_rate": 0.001, "batch_size": 64, "learning_starts": 256, "train_every_decisions": 4, "reward": "negative all-external-lane stopped vehicle-seconds / 100", "target_update_gradient_steps": 250, "replay_capacity": 50000, "architecture": [128, 128], "device": "cpu", "torch": str(torch.__version__), "numpy": np.__version__}
    write_json(output / "training_config.json", meta)
    try:
        with (output / "training.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["episode", "seed", "decisions", "return", "epsilon", "mean_loss", "arrived", "unfinished", "not_departed", "queue_vehicle_seconds"])
            writer.writeheader()
            for episode in range(episodes):
                obs, info = env.reset(seed=seed + episode)
                losses = []
                done = False
                while not done:
                    epsilon = max(0.05, 1.0 - 0.95 * step_count / max(1, estimated_steps * 0.7))
                    action = agent.act(obs, info["action_mask"], epsilon)
                    next_obs, reward, terminated, truncated, next_info = env.step(action)
                    done = terminated or truncated
                    agent.memory.append((obs.copy(), action, reward, next_obs.copy(), done, next_info["action_mask"].copy()))
                    step_count += 1
                    if len(agent.memory) >= 256 and step_count % 4 == 0:
                        losses.append(agent.learn())
                    obs, info = next_obs, next_info
                metrics = info["metrics"]
                writer.writerow({"episode": episode + 1, "seed": seed + episode, "decisions": step_count, "return": metrics["return"], "epsilon": epsilon, "mean_loss": float(np.mean(losses)) if losses else "", **{k: metrics[k] for k in ["arrived", "unfinished", "not_departed", "queue_vehicle_seconds"]}})
                f.flush()
                print(f"Episode {episode+1}/{episodes}: return={metrics['return']:.2f}, arrived={metrics['arrived']}, updates={agent.updates}", flush=True)
        meta["gradient_updates"] = agent.updates
        meta["decision_steps"] = step_count
        write_json(output / "training_config.json", meta)
        agent.save(output / "model.pt", env.checkpoint_schema, meta)
        return agent
    finally:
        env.close()
