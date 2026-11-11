"""Validate the recorded four-site SUMO runs and create the user report."""
import json
from pathlib import Path
from statistics import mean
import xml.etree.ElementTree as ET
import run as experiment

ROOT = Path(__file__).resolve().parent
NAMES = {'basic': '기본 DQN', 'priority': '보행자 우선', 'adaptive': '우선 + 대기 연동 비용'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def check_trace(folder, variant):
    decisions, seconds = read(folder / 'decisions.json'), read(folder / 'seconds.json')
    assert len(decisions) == 84 and len(seconds) == 420
    minimums = {'vehicle': 15, 'yellow': 4, 'to_pedestrian': 1, 'pedestrian': 10, 'clearance': 10}
    following = {'vehicle': 'yellow', 'yellow': 'to_pedestrian', 'to_pedestrian': 'pedestrian',
                 'pedestrian': 'clearance', 'clearance': 'vehicle'}
    for tick in seconds:
        assert len(tick['sites']) == 4
        for row in tick['sites']:
            signal = row['signal']
            assert len(signal) == 3
            assert not ('G' in signal[:2] and signal[2] in 'Gg')
    for previous, current in zip(seconds, seconds[1:]):
        for before, after in zip(previous['sites'], current['sites']):
            if before['stage'] != after['stage']:
                assert following[before['stage']] == after['stage']
                assert before['elapsed'] + 1 >= minimums[before['stage']]
                if after['stage'] == 'vehicle':
                    assert not after['crossing_occupied_before']
    for decision in decisions:
        assert decision['actions'] == experiment.ACTIONS[decision['action_id']].tolist()
        for i, row in enumerate(decision['sites']):
            assert row['site'] == experiment.SITES[i]
            gate = max(0, 1-row['oldest_ped_wait']/30)
            expected = .02*gate if variant == 'adaptive' and row['target_changed'] else 0
            assert abs(expected-row['switch_cost']) < 1e-10
            if variant != 'basic' and row['stage_before'] == 'vehicle' and row['oldest_ped_wait'] >= 30:
                elapsed = seconds[decision['time']-1]['sites'][i]['elapsed'] + 1 if decision['time'] else 0
                if elapsed >= 15:
                    assert row['action'] == 1
        assert abs(decision['switch_cost']-mean(r['switch_cost'] for r in decision['sites'])) < 1e-10


def main():
    net = ET.parse(ROOT / 'network/corridor.net.xml').getroot()
    assert {node.get('id') for node in net.findall('tlLogic')} == set(experiment.SITES)
    assert sum(edge.get('function') == 'crossing' for edge in net.findall('edge')) == 4
    results = {}
    training = {}
    for variant in NAMES:
        summary = read(ROOT / f'results/train-{variant}/summary.json')
        assert summary['decisions'] == 2520 and summary['updates'] == 1197 and summary['max_weight_change'] > 0
        training[variant] = read(ROOT / f'results/train-{variant}/training.json')
        data = read(ROOT / f'results/eval-{variant}/evaluation.json')
        assert data['model_sha256'] == summary['model_sha256'] == experiment.single.sha256(ROOT / f'results/train-{variant}/model.pt')
        results[variant] = data['results']
        assert len(results[variant]) == 9
        for row in results[variant]:
            assert row['crossing_count'] == 4 and row['seconds'] == 420
            assert row['collisions'] == row['teleports'] == 0
            assert sum(row['site_switches'].values()) == row['switches']
            for kind in ['vehicle','person']:
                counts = row[kind]
                assert counts['scheduled'] == counts['arrived']+counts['remaining']+counts['not_departed']
                assert counts['departed'] == counts['arrived']+counts['remaining']
            check_trace(ROOT / f'results/eval-{variant}/{row["profile"]}-{row["seed"]}', variant)
    for row_group in zip(*results.values(), strict=True):
        assert len({r['route_sha256'] for r in row_group}) == 1
        assert len({(r['seed'],r['profile']) for r in row_group}) == 1
    for row_group in zip(*training.values(), strict=True):
        assert len({r['route_sha256'] for r in row_group}) == 1
    demo = read(ROOT / 'results/demo/evaluation.json')['results'][0]
    expected = next(r for r in results['adaptive'] if r['profile'] == 'ped-burst' and r['seed'] == 1001)
    assert demo == expected
    assert read(ROOT / 'results/demo/ped-burst-1001/decisions.json') == read(ROOT / 'results/eval-adaptive/ped-burst-1001/decisions.json')
    from PIL import Image
    with Image.open(ROOT / 'media/pedlink-sumo.gif') as animation:
        assert animation.n_frames == 50
    remaining = sum(row[k]['remaining']+row[k]['not_departed'] for rows in results.values() for row in rows for k in ['vehicle','person'])
    print(json.dumps({'verified_runs': 27, 'signal_node_seconds': 45360,
                      'remaining': remaining, 'gif_frames': 50}))

if __name__ == '__main__':
    main()
