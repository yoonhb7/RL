from __future__ import annotations
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import time

from .agent import Agent
from .common import ROOT, code_hash, digest, environment_signature, provenance, write_json
from .env import TrafficEnv


def training_demand_seed(seed, episode):
    # Disjoint from held-out evaluation seeds; same train seed => same routes for all algorithms/rewards.
    return 100000 + seed*10000 + episode


def controller_action(env, obs, controller):
    if controller == 'fixed':
        return int(env.green_age >= env.s['fixed_green_s'])
    if controller == 'queue':
        ns = float(obs[0]+obs[6])
        ew = float(obs[3]+obs[9])
        current, other = (ns, ew) if env.phase == 0 else (ew, ns)
        return int(env.green_age >= 10 and (other > current+1 or (env.green_age >= 60 and other > 0)))
    raise ValueError(controller)


def run_episode(cfg, level, reward, demand_seed, out, agent=None, controller='fixed', train=False,
                split='eval', gui=False, delay=70):
    env = TrafficEnv(cfg, level, reward, demand_seed, split, out, gui, delay)
    losses = []
    started = time.perf_counter()
    try:
        obs, _ = env.reset()
        while True:
            epsilon = agent.epsilon() if train else 0.0
            action = agent.act(obs, epsilon) if agent else controller_action(env, obs, controller)
            nxt, r, terminal, truncated, info = env.step(action)
            if train:
                agent.remember(obs, action, r, nxt, terminal or truncated, info['discount'])
                loss = agent.learn()
                if loss is not None:
                    losses.append(loss)
            obs = nxt
            if terminal or truncated:
                break
        metrics = env.metrics()
        if metrics['departed'] != metrics['arrived']+metrics['remaining']:
            raise AssertionError('Vehicle conservation failed.')
        if metrics['scheduled'] != metrics['departed']+metrics['not_departed']:
            raise AssertionError('Demand conservation failed.')
        if metrics['collisions'] or metrics['teleports']:
            raise RuntimeError('Collision/teleport invalidates this run. Inspect sumo.log.')
        metrics.update(controller=agent.algorithm if agent else controller,
                       mean_td_loss=statistics.mean(losses) if losses else None,
                       gradient_updates=len(losses), wall_seconds=time.perf_counter()-started)
        write_json(Path(out)/'metrics.json', metrics)
        return metrics
    finally:
        env.close()


def train(cfg, algorithm, reward, level, seed, out):
    out = Path(out)
    if (out/'training.json').exists() or (out/'training.csv').exists():
        raise FileExistsError(f'Training output already exists: {out}. Choose a new --out.')
    out.mkdir(parents=True, exist_ok=True)
    p = provenance(cfg)
    write_json(out/'config.json', cfg)
    metadata = {'algorithm': algorithm, 'reward': reward, 'training_level': level, 'training_seed': seed,
                'provenance': p, 'state': 'training', 'started_utc': datetime.now(timezone.utc).isoformat()}
    write_json(out/'training.json', metadata)
    agent = Agent(cfg, algorithm, seed)
    metadata['effective_device'] = str(agent.device)
    rows = []
    with (out/'training.csv').open('w', newline='', encoding='utf-8') as f:
        fields = ['episode','epsilon','decisions','updates','raw_return','mean_td_loss',
                  'penalized_wait_s_per_scheduled','completion_rate','wall_seconds']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for episode in range(cfg['learning']['episodes']):
            ds = training_demand_seed(seed, episode)
            if ds in cfg['experiment']['evaluation_seeds']:
                raise ValueError('Training demand seed overlaps held-out evaluation seed.')
            m = run_episode(cfg, level, reward, ds, out/f'episode-{episode+1:03d}', agent=agent, train=True, split='train')
            row = {k:m[k] for k in fields if k in m}
            row.update(episode=episode+1, epsilon=agent.epsilon(), decisions=agent.steps, updates=agent.updates)
            writer.writerow(row)
            f.flush()
            rows.append(m)
            # Save final completed episode too: interrupted later episodes leave a usable policy.
            agent.save(out/'model.pt', dict(metadata, completed_episodes=episode+1))
            print(f'{level}/{reward}/{algorithm} seed={seed} episode={episode+1}/{cfg["learning"]["episodes"]} '
                  f'wait={m["penalized_wait_s_per_scheduled"]:.2f}s completion={m["completion_rate"]:.3f} '
                  f'updates={agent.updates}', flush=True)
    metadata.update(state='complete', completed_episodes=len(rows), decisions=agent.steps, updates=agent.updates,
                    finished_utc=datetime.now(timezone.utc).isoformat())
    write_json(out/'training.json', metadata)
    agent.save(out/'model.pt', metadata)
    return out/'model.pt'


def evaluate(cfg, out, levels, seeds, model=None, controller='fixed', reward='wtmin', gui=False, delay=70):
    out = Path(out)
    if (out/'evaluation.json').exists():
        raise FileExistsError(f'Evaluation output exists: {out}. Choose a new --out.')
    agent, data = Agent.load(model, cfg) if model else (None, None)
    if data:
        reward = data['metadata']['reward']
        train_seeds = [training_demand_seed(data['metadata']['training_seed'], i)
                       for i in range(data['metadata'].get('completed_episodes',0))]
        if set(seeds) & set(train_seeds):
            raise ValueError('Evaluation route seeds overlap training route seeds.')
    rows = []
    for level in levels:
        for seed in seeds:
            m = run_episode(cfg, level, reward, seed, out/f'{level}-demand-{seed}', agent=agent,
                            controller=controller, split='eval', gui=gui, delay=delay)
            m['training_level'] = data['metadata']['training_level'] if data else 'baseline'
            m['training_seed'] = data['metadata']['training_seed'] if data else None
            m['reward'] = reward if data else 'baseline'
            rows.append(m)
            print(f'{m["controller"]} test={level}/{seed}: wait={m["penalized_wait_s_per_scheduled"]:.2f}s '
                  f'arrived={m["arrived"]}/{m["scheduled"]} pending={m["not_departed"]}', flush=True)
    result = {'state':'complete', 'provenance': provenance(cfg), 'model': str(Path(model).resolve()) if model else None,
              'training_metadata': data['metadata'] if data else None, 'runs': rows}
    write_json(out/'evaluation.json', result)
    return result


def create_plan(cfg, out, algorithms=None, rewards=None, levels=None, seeds=None, cross=False):
    jobs = []
    e = cfg['experiment']
    for level in levels or ['low','medium','high']:
        for reward in rewards or e['rewards']:
            for algorithm in algorithms or e['algorithms']:
                for seed in seeds or e['training_seeds']:
                    jobs.append({'id': f'{level}/{reward}/{algorithm}/seed-{seed}', 'level':level,
                                 'reward':reward, 'algorithm':algorithm, 'training_seed':seed,
                                 'owner':e['owners'][level], 'evaluation_levels': ['low','medium','high'] if cross else [level]})
    plan = {'protocol':'trafficbench-plan-v1', 'config':cfg, 'provenance':provenance(cfg), 'jobs':jobs,
            'job_count':len(jobs), 'evaluation_count':sum(len(j['evaluation_levels'])*len(e['evaluation_seeds']) for j in jobs)}
    write_json(out, plan)
    return plan


def run_batch(plan_path, out, owner=None):
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    cfg = plan['config']
    if plan['provenance']['code_sha256'] != code_hash():
        raise ValueError('Code changed since plan creation. Recreate the plan so team members share the same code.')
    if plan['provenance']['config_sha256'] != digest(cfg):
        raise ValueError('Plan config fingerprint mismatch.')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out/'plan_snapshot.json', plan)
    failures = []
    for j in plan['jobs']:
        if owner and j['owner'] != owner:
            continue
        jobdir = out/j['id']
        if (jobdir/'complete.json').exists():
            old = json.loads((jobdir/'complete.json').read_text())
            if old['protocol_sha256'] != plan['provenance']['protocol_sha256']:
                raise ValueError(f'Existing output belongs to a different protocol: {jobdir}')
            print('SKIP complete:',j['id'],flush=True)
            continue
        jobdir.mkdir(parents=True, exist_ok=True)
        # Interrupted attempts are kept intact; each retry gets a fresh directory.
        attempts = sorted(jobdir.glob('attempt-*'))
        attempt = jobdir/f'attempt-{len(attempts)+1:03d}'
        try:
            model = train(cfg,j['algorithm'],j['reward'],j['level'],j['training_seed'],attempt/'train')
            evaluate(cfg,attempt/'eval',j['evaluation_levels'],cfg['experiment']['evaluation_seeds'],model=model)
            write_json(jobdir/'complete.json',dict(j, protocol_sha256=plan['provenance']['protocol_sha256'],
                                                   evaluation=str((attempt/'eval/evaluation.json').relative_to(jobdir))))
        except Exception as exc:
            write_json(attempt/'failed.json',dict(job=j, error=repr(exc)))
            failures.append(j['id'])
            print('FAILED:',j['id'],repr(exc),flush=True)
    if failures:
        raise RuntimeError(f'{len(failures)} job(s) failed. Inspect failed.json. Rerun batch to retry incomplete jobs.')
