from __future__ import annotations
from collections import deque
import copy
from pathlib import Path
import random

import numpy as np
import torch
from torch import nn
from .common import ALGOS, environment_signature


class QNetwork(nn.Module):
    def __init__(self, hidden=(512,256,64), dueling=False):
        super().__init__()
        layers, n = [], 13
        for width in hidden:
            layers += [nn.Linear(n, width), nn.ReLU()]
            n = width
        self.shared = nn.Sequential(*layers)
        self.dueling = dueling
        if dueling:
            self.value, self.advantage = nn.Linear(n,1), nn.Linear(n,2)
        else:
            self.q = nn.Linear(n,2)
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.kaiming_normal_(module.weight, nonlinearity='relu')
                nn.init.zeros_(module.bias)

    def forward(self, obs):
        x = self.shared(obs/10.0)  # same deterministic scaling for all models
        if self.dueling:
            a = self.advantage(x)
            return self.value(x)+a-a.mean(dim=-1, keepdim=True)
        return self.q(x)


def td_target(rewards, discounts, dones, online_next, target_next, double):
    if double:
        index = online_next.argmax(dim=1, keepdim=True)
        bootstrap = target_next.gather(1, index).squeeze(1)
    else:
        bootstrap = target_next.max(dim=1).values
    return rewards + discounts*(1-dones)*bootstrap


class Agent:
    def __init__(self, cfg, algorithm='dqn', seed=11):
        if algorithm not in ALGOS:
            raise ValueError(algorithm)
        self.cfg, self.l, self.algorithm = cfg, cfg['learning'], algorithm
        self.rng = random.Random(seed)
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.set_num_threads(1)
        device = self.l['device']
        if device == 'auto':
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        if device.startswith('cuda') and not torch.cuda.is_available():
            raise RuntimeError('CUDA requested but unavailable. Use cpu or install a compatible PyTorch build.')
        self.device = torch.device(device)
        self.online = QNetwork(self.l['hidden_sizes'], algorithm in ('dueling','d3qn')).to(self.device)
        self.target = copy.deepcopy(self.online).eval()
        self.optimizer = torch.optim.Adam(self.online.parameters(), lr=self.l['learning_rate'])
        self.memory = deque(maxlen=self.l['replay_capacity'])
        self.updates = self.steps = 0

    def epsilon(self):
        f = min(1, self.steps/self.l['epsilon_decay_decisions'])
        return self.l['epsilon_start'] + f*(self.l['epsilon_end']-self.l['epsilon_start'])

    def act(self, obs, epsilon=0.0):
        if self.rng.random() < epsilon:
            return self.rng.randrange(2)
        with torch.no_grad():
            return int(self.online(torch.as_tensor(obs, device=self.device).unsqueeze(0)).argmax().item())

    def remember(self, obs, action, reward, nxt, done, discount):
        self.memory.append((obs.copy(), action, reward, nxt.copy(), done, discount))
        self.steps += 1

    def learn(self):
        if len(self.memory) < self.l['learning_starts'] or self.steps % self.l['train_every_decisions']:
            return None
        rows = self.rng.sample(self.memory, self.l['batch_size'])
        obs, actions, rewards, nxt, dones, discounts = zip(*rows)
        def tensor(a, dtype=torch.float32):
            return torch.as_tensor(np.asarray(a), dtype=dtype, device=self.device)
        with torch.no_grad():
            targets = td_target(tensor(rewards), tensor(discounts), tensor(dones),
                                self.online(tensor(nxt)), self.target(tensor(nxt)), self.algorithm in ('double','d3qn'))
        prediction = self.online(tensor(obs)).gather(1, tensor(actions,torch.long)[:,None]).squeeze(1)
        loss = nn.functional.mse_loss(prediction, targets)
        if not torch.isfinite(loss):
            raise FloatingPointError('Nonfinite TD loss.')
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.online.parameters(), self.l['gradient_clip_norm'])
        self.optimizer.step()
        self.updates += 1
        if self.updates % self.l['target_update_every_updates'] == 0:
            self.target.load_state_dict(self.online.state_dict())
        return float(loss.item())

    def save(self, path, metadata):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        torch.save({'schema': 'trafficbench-v1', 'state_dict': self.online.state_dict(),
                    'algorithm': self.algorithm, 'config': self.cfg, 'metadata': metadata,
                    'environment_signature': environment_signature(self.cfg), 'updates': self.updates,
                    'decisions': self.steps}, temp)
        temp.replace(path)

    @classmethod
    def load(cls, path, cfg=None):
        data = torch.load(path, map_location='cpu', weights_only=True)
        if data['schema'] != 'trafficbench-v1':
            raise ValueError('Unsupported checkpoint schema.')
        cfg = cfg or data['config']
        if environment_signature(cfg) != data['environment_signature']:
            raise ValueError('Checkpoint geometry/observation/signal definitions differ from config.')
        agent = cls(cfg, data['algorithm'])
        agent.online.load_state_dict(data['state_dict'])
        agent.target.load_state_dict(data['state_dict'])
        agent.online.eval()
        agent.updates, agent.steps = data['updates'], data['decisions']
        return agent, data
