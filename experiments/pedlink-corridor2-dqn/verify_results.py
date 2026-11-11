"""Audit two-junction topology, joint-agent training, paired demand, and phase traces."""
import csv
import json
from pathlib import Path
from statistics import mean
import xml.etree.ElementTree as ET
import run as experiment

ROOT=Path(__file__).resolve().parent

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def check_trace(folder,variant):
    decisions,seconds=read(folder/'decisions.json'),read(folder/'seconds.json')
    assert len(decisions)==120 and len(seconds)==600
    for row in decisions:
        assert row['actions']==experiment.ACTIONS[row['action_id']].tolist()
        assert len(row['sites'])==2
        for local in row['sites']:
            expected=.02*max(0,1-local['oldest_ped_wait']/30) if local['target_changed'] and variant=='adaptive' else 0
            assert abs(local['switch_cost']-expected)<1e-10
            if variant in ['priority','adaptive'] and local['stage_before'] in ['EW','NS']:
                if local['elapsed_before']>=15 and local['oldest_ped_wait']>=30:
                    assert local['action']==2
        assert abs(row['switch_cost']-mean(s['switch_cost'] for s in row['sites']))<1e-10
    net=ET.parse(ROOT/'network/corridor.net.xml').getroot()
    indices=[]
    for site in experiment.SITES:
        vehicle={int(c.get('linkIndex')) for c in net.findall('connection')
                 if c.get('tl')==site and c.get('from') in experiment.INCOMING[site]}
        count=len(net.find(f"tlLogic[@id='{site}']/phase").get('state'))
        indices.append((vehicle,set(range(count))-vehicle))
    for row in seconds:
        for local,(vehicles,persons) in zip(row['sites'],indices):
            state=local['signal']
            assert not (any(state[i] in 'Gg' for i in vehicles) and any(state[i] in 'Gg' for i in persons))
            if local['stage'] in ['EW','NS']:
                assert not local['crossing_occupied_before']
    minimums={'EW':15,'NS':15,'PED':10,'yellow':4,'all_red':2,'clearance':10}
    for previous,current in zip(seconds,seconds[1:]):
        for before,after in zip(previous['sites'],current['sites']):
            if before['stage']!=after['stage']:
                assert before['elapsed']+1>=minimums[before['stage']]
                a,b=before['stage'],after['stage']
                assert (a in ['EW','NS'] and b=='yellow') or (a=='yellow' and b=='all_red') or \
                       (a=='all_red' and b in ['EW','NS','PED']) or (a=='PED' and b=='clearance') or \
                       (a=='clearance' and b in ['EW','NS'])
                if a=='clearance':
                    assert not after['crossing_occupied_before']
    return len(seconds)*2

def main():
    net=ET.parse(ROOT/'network/corridor.net.xml').getroot()
    assert {n.get('id') for n in net.findall('tlLogic')}=={'J0','J1'}
    assert sum(e.get('function')=='crossing' for e in net.findall('edge'))==8
    assert len(experiment.ACTIONS)==9 and experiment.OBS_SIZE==52
    all_rows=[]
    checked=0
    histories=[]
    for variant in ['basic','priority','adaptive']:
        folder=ROOT/f'results/train-{variant}'
        summary=read(folder/'summary.json')
        assert summary['agent_count']==1 and summary['junction_count']==2
        assert summary['episodes']==30 and summary['decisions']==3600 and summary['updates']==1737
        assert summary['max_weight_change']>0 and summary['observation_size']==52 and summary['joint_actions']==9
        assert summary['model_sha256']==experiment.core.sha256(folder/'model.pt')
        histories.append(read(folder/'training.json'))
        data=read(ROOT/f'results/eval-{variant}/evaluation.json')
        assert data['model_sha256']==summary['model_sha256'] and len(data['results'])==9
        model=experiment.core.DQNAgent.load(folder/'model.pt',experiment.schema())
        assert model.obs_size==52 and model.actions==9 and not model.double
        for row in data['results']:
            row['controller']=variant
            all_rows.append(row)
            checked+=check_trace(ROOT/f'results/eval-{variant}/{row["profile"]}-{row["seed"]}',variant)
    for episodes in zip(*histories,strict=True):
        assert len({r['route_sha256'] for r in episodes})==1
    rules=read(ROOT/'results/baselines/evaluation.json')['results']
    assert len(rules)==18
    for row in rules:
        all_rows.append(row)
        checked+=check_trace(ROOT/f'results/baselines/{row["controller"]}-{row["profile"]}-{row["seed"]}','basic')
    for profile in experiment.core.PROFILES:
        for seed in [1001,1002,1003]:
            group=[r for r in all_rows if r['profile']==profile and r['seed']==seed]
            assert len(group)==5 and len({r['route_sha256'] for r in group})==1
    residuals=[]
    for row in all_rows:
        assert row['agent_count']==1 and row['junction_count']==2 and row['crossing_count']==8
        assert row['collisions']==row['teleports']==0
        assert row['arrived_pedestrians_crossed']==row['person']['arrived']
        assert row['pedestrians_crossed_multiple']==0
        for kind in ['vehicle','person']:
            counts=row[kind]
            assert counts['scheduled']==counts['arrived']+counts['remaining']+counts['not_departed']
            assert counts['departed']==counts['arrived']+counts['remaining']
            if counts['remaining']+counts['not_departed']:
                residuals.append({'controller':row['controller'],'profile':row['profile'],'seed':row['seed'],'kind':kind,
                                  'remaining':counts['remaining'],'not_departed':counts['not_departed']})
    summary_rows=[]
    for profile in experiment.core.PROFILES:
        for controller in ['fixed','queue','basic','priority','adaptive']:
            group=[r for r in all_rows if r['profile']==profile and r['controller']==controller]
            summary_rows.append({'profile':profile,'controller':controller,'n_seeds':len(group),
                'vehicle_mean_wait_s':mean(r['vehicle']['mean_wait_s'] for r in group),
                'person_mean_wait_s':mean(r['person']['mean_wait_s'] for r in group),
                'person_p95_wait_s':mean(r['person']['p95_wait_s'] for r in group),
                'switches':mean(r['switches'] for r in group),
                'remaining_vehicles':sum(r['vehicle']['remaining'] for r in group),
                'remaining_persons':sum(r['person']['remaining'] for r in group)})
    with (ROOT/'results/comparison.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)
    report={'agent_count':1,'junction_count':2,'crossing_count':8,'observation_size':52,'joint_actions':9,
            'training_episodes_per_variant':30,'evaluation_runs':len(all_rows),'signal_node_seconds_checked':checked,
            'paired_demand_hashes_verified':True,'phase_constraints_verified':True,'pedestrian_crossings_verified':True,
            'collisions':0,'teleports':0,'residuals':residuals}
    if (ROOT/'results/gui-demo/evaluation.json').exists():
        demo=read(ROOT/'results/gui-demo/evaluation.json')['results'][0]
        expected=next(r for r in all_rows if r['controller']=='adaptive' and r['profile']=='ped-burst' and r['seed']==1001)
        expected={k:v for k,v in expected.items() if k!='controller'}
        assert demo==expected
        assert read(ROOT/'results/gui-demo/ped-burst-1001/decisions.json')==read(ROOT/'results/eval-adaptive/ped-burst-1001/decisions.json')
        report['gui_matches_headless']=True
    replay=read(ROOT/'results/replay/evaluation.json')['results'][0]
    expected=next(r for r in all_rows if r['controller']=='adaptive' and r['profile']=='ped-burst' and r['seed']==1001)
    assert replay=={k:v for k,v in expected.items() if k!='controller'}
    motion=read(ROOT/'results/replay/ped-burst-1001/motion.json')
    ticks=read(ROOT/'results/replay/ped-burst-1001/seconds.json')
    assert len(motion)==71 and motion[0]['time']==100 and motion[-1]['time']==240
    for frame in motion:
        assert frame['stages']==[s['stage'] for s in ticks[frame['time']-1]['sites']]
    from PIL import Image
    with Image.open(ROOT/'media/two-junctions-replay.gif') as gif:
        assert gif.n_frames==71
    report['recorded_position_replay_matches_evaluation']=True
    report['replay_frames']=71
    experiment.core.write_json(ROOT/'results/verification.json',report)
    print(json.dumps(report))

if __name__=='__main__':
    main()
