"""Shared PedLink-DQN signal, accounting, and training helpers."""
from __future__ import annotations

import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
import bootstrap
bootstrap.configure()
import numpy as np
import torch
from traffic_rl.common import binary, sha256, write_json
from traffic_rl.dqn import DQNAgent
from traffic_rl.launch import start_sumo

PORTABLE = Path.home() / 'Downloads/sumo-win64-1.28.0/sumo-win64-1.28.0'
if not os.getenv('SUMO_HOME') and (PORTABLE / 'bin/sumo.exe').is_file():
    os.environ['SUMO_HOME'] = str(PORTABLE)

HORIZON = 600
DEMAND_END = 300
DECISION = 5
WAIT_LIMIT = 30
SWITCH_WEIGHT = .02
STAGES = ['vehicle', 'yellow', 'to_pedestrian', 'pedestrian', 'clearance']
PROFILES = ['balanced', 'vehicle-heavy', 'ped-burst']




def arrivals(rng, rate):
    current = 0.0
    times = []
    while True:
        current += float(rng.exponential(3600.0 / rate))
        if current >= DEMAND_END:
            return times
        times.append(current)




class Environment:
    def finish(self, *, switches=None, extra=None):
        result = {'variant': self.variant, 'seed': self.seed, 'profile': self.profile, 'seconds': self.time,
                  'route_sha256': sha256(self.route_file), 'switches': self.control.switches if switches is None else switches,
                  'vehicle_stops': self.stops,
                  'collisions': self.collisions, 'teleports': self.teleports, 'base_return': self.raw_return,
                  'switch_cost_sum': self.cost_sum, 'return': self.raw_return - self.cost_sum,
                  'max_continuous_ped_wait_at_decision_s': max((r['oldest_ped_wait'] for r in self.trace), default=0)}
        for kind in ('vehicle', 'person'):
            waits = list(self.wait[kind].values())
            active = set(self.snapshot['vehicle_ids' if kind == 'vehicle' else 'person_ids'])
            result[kind] = {'scheduled': len(self.planned[kind]), 'departed': len(self.departed[kind]),
                            'arrived': len(self.arrived[kind]), 'remaining': len(active),
                            'not_departed': len(set(self.planned[kind]) - self.departed[kind]),
                            'mean_wait_s': float(np.mean(waits)) if waits else 0,
                            'p95_wait_s': float(np.percentile(waits, 95)) if waits else 0,
                            'max_wait_s': max(waits, default=0)}
        if extra:
            result.update(extra)
        write_json(self.folder / 'result.json', result)
        write_json(self.folder / 'decisions.json', self.trace)
        write_json(self.folder / 'seconds.json', self.tick_trace)
        return result

    def close(self):
        self.connection.close()


def train(args, *, environment, obs_size, actions, checkpoint_schema):
    out = args.out.resolve()
    out.mkdir(parents=True)
    agent = DQNAgent(obs_size, actions, seed=args.seed)
    initial = {k: v.clone() for k, v in agent.online.state_dict().items()}
    steps = 0
    budget = args.episodes * HORIZON // DECISION
    rows = []
    metadata = {'variant': args.variant, 'episodes': args.episodes, 'seed': args.seed,
                'action_budget': budget, 'wait_limit_s': WAIT_LIMIT, 'switch_weight': SWITCH_WEIGHT,
                'reward': '-(stopped vehicle seconds + pending vehicle seconds + 2*stopped person seconds)/100 - cost',
                'learning_starts': 128, 'learn_every': 2, 'batch': 64, 'gamma': .99, 'learning_rate': .001,
                'training_seeds': [args.seed + 1000 * i for i in range(args.episodes)], 'profiles': PROFILES,
                'observation_size': obs_size, 'joint_actions': actions, 'agent_count': 1, 'junction_count': 2,
                'architecture': [obs_size,128,128,actions], 'horizon_s': HORIZON, 'demand_end_s': DEMAND_END,
                'device': 'cpu', 'torch_version': str(torch.__version__)}
    write_json(out / 'config.json', metadata)
    for i in range(args.episodes):
        profile = PROFILES[i % len(PROFILES)]
        env = environment(out / f'episode-{i+1:03d}', metadata['training_seeds'][i], profile, args.variant)
        losses = []
        try:
            state, mask = env.observe(), env.mask()
            done = False
            while not done:
                epsilon = max(.05, 1 - .95 * steps / max(1, .7 * budget))
                action = agent.act(state, mask, epsilon)
                next_state, reward, done, next_mask = env.step(action)
                agent.memory.append((state, action, reward, next_state, done, next_mask))
                steps += 1
                if len(agent.memory) >= 128 and steps % 2 == 0:
                    loss = agent.learn()
                    if not math.isfinite(loss):
                        raise FloatingPointError('Nonfinite DQN loss')
                    losses.append(loss)
                state, mask = next_state, next_mask
            row = env.finish()
            row.update(episode=i + 1, updates=agent.updates, mean_loss=float(np.mean(losses)) if losses else None)
            rows.append(row)
        finally:
            env.close()
        write_json(out / 'training.json', rows)
        agent.save(out / 'model.tmp', checkpoint_schema(), {**metadata, 'completed_episodes': i + 1, 'updates': agent.updates})
        (out / 'model.tmp').replace(out / 'model.pt')
        print(f'{args.variant} {i+1}/{args.episodes} | {profile} | updates={agent.updates} '
              f'car={row["vehicle"]["mean_wait_s"]:.1f}s ped={row["person"]["mean_wait_s"]:.1f}s', flush=True)
    change = max(float((v - initial[k]).abs().max()) for k, v in agent.online.state_dict().items())
    write_json(out / 'summary.json', {**metadata, 'decisions': steps, 'updates': agent.updates,
                                    'max_weight_change': change, 'model_sha256': sha256(out / 'model.pt')})


def evaluate(args, *, environment, checkpoint_schema):
    agent = DQNAgent.load(args.model, checkpoint_schema())
    variant = agent.metadata['variant']
    if set(args.seeds) & set(agent.metadata['training_seeds']):
        raise ValueError('Evaluation seeds overlap training')
    out = args.out.resolve()
    out.mkdir(parents=True)
    rows = []
    for profile in args.profiles:
        for seed in args.seeds:
            env = environment(out / f'{profile}-{seed}', seed, profile, variant,
                              gui=args.command == 'view', delay=args.delay,
                              record_motion=args.command == 'record')
            try:
                state, mask = env.observe(), env.mask()
                done = False
                while not done:
                    action = agent.act(state, mask, 0)
                    state, _, done, mask = env.step(action)
                row = env.finish()
                rows.append(row)
                print(f'{variant} {profile} seed={seed} | car={row["vehicle"]["mean_wait_s"]:.2f}s '
                      f'ped95={row["person"]["p95_wait_s"]:.2f}s switches={row["switches"]}', flush=True)
            finally:
                env.close()
    write_json(out / 'evaluation.json', {'model_sha256': sha256(args.model), 'training': agent.metadata, 'results': rows})
