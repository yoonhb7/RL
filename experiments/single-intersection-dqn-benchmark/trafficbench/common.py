from __future__ import annotations
import copy
import hashlib
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALGOS = ('dqn', 'double', 'dueling', 'd3qn')
REWARDS = ('wtmin', 'asmax', 'ttmin', 'ctmax', 'wctmax', 'tmqmax')
LEVELS = ('low', 'medium', 'high')


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_hash():
    files = [ROOT / 'run.py', *sorted((ROOT / 'trafficbench').glob('*.py'))]
    return digest({p.relative_to(ROOT).as_posix(): file_hash(p) for p in files})


def load_config(path=None):
    path = Path(path) if path else ROOT / 'configs/shared.json'
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    s, l = cfg['scenario'], cfg['learning']
    if s['demand_seconds'] <= 0 or s['drain_seconds'] < 0:
        raise ValueError('Demand must be positive; drain must be nonnegative.')
    if not 0 <= s['right_turn_ratio'] <= 1:
        raise ValueError('Invalid turn ratio.')
    if set(s['direction_shares']) != set('NESW') or abs(sum(s['direction_shares'].values()) - 1) > 1e-8:
        raise ValueError('Four direction shares must sum to 1.')
    if any(v < 0 for v in s['direction_shares'].values()):
        raise ValueError('Negative direction share.')
    if not 0 < l['gamma_per_second'] <= 1 or l['learning_starts'] < l['batch_size']:
        raise ValueError('Invalid gamma or learning_starts < batch_size.')
    if l['episodes'] <= 0 or s['yellow_s'] < 1:
        raise ValueError('Invalid episode count or yellow duration.')
    for level in LEVELS:
        if s['loads_vph'][level] <= 0 or max(s['direction_shares'].values()) * s['loads_vph'][level] / 3600 >= 1:
            raise ValueError('Requested demand exceeds Bernoulli one-vehicle/direction/second generator.')
    return cfg


def environment_signature(cfg):
    # Demand level/length can change at evaluation; physical observation/signal definitions cannot.
    s = copy.deepcopy(cfg['scenario'])
    for key in ('loads_vph', 'demand_seconds', 'drain_seconds', 'direction_shares', 'right_turn_ratio'):
        s.pop(key)
    return digest({'protocol': cfg['protocol'], 'geometry': s, 'observation': 'E2-50m-count-occ-speed-phase-v1'})


def provenance(cfg):
    import torch
    import numpy
    return {'config_sha256': digest(cfg), 'code_sha256': code_hash(),
            'protocol_sha256': digest({'config': cfg, 'code': code_hash()}),
            'torch': str(torch.__version__), 'numpy': str(numpy.__version__),
            'environment_signature': environment_signature(cfg)}
