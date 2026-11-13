from __future__ import annotations
import csv
import html
import json
from pathlib import Path
import statistics
from .common import write_json

METRICS = ['penalized_wait_s_per_scheduled','observed_wait_s_per_scheduled','completion_rate',
           'mean_queue_vehicles','co2_g','max_observed_vehicle_wait_s','signal_switches']


def make_report(roots, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    evaluations = []
    seen_files = set()
    for root in roots:
        root = Path(root)
        candidates = list(root.rglob('complete.json'))
        if candidates:
            paths = [p.parent/json.loads(p.read_text())['evaluation'] for p in candidates]
        else:
            paths = list(root.rglob('evaluation.json'))
        for p in paths:
            if p.resolve() not in seen_files:
                evaluations.append((p,json.loads(p.read_text(encoding='utf-8'))))
                seen_files.add(p.resolve())
    if not evaluations:
        raise ValueError('No completed evaluation.json found.')
    protocols = {e['provenance']['protocol_sha256'] for _,e in evaluations}
    if len(protocols) != 1:
        raise ValueError('Cannot merge different code/config protocols. Use separate reports.')
    rows, identities = [], {}
    route_hashes, network_hashes, sumo_versions = {}, set(), set()
    for path,e in evaluations:
        for original in e['runs']:
            r = dict(original)
            key=(r['level'],r['demand_seed'])
            if key in route_hashes and route_hashes[key] != r['route_sha256']:
                raise ValueError(f'Demand files differ for the same evaluation condition: {key}')
            route_hashes[key]=r['route_sha256']
            network_hashes.add(r['network_structure_sha256'])
            sumo_versions.add(r['sumo_version'])
            identity = tuple(r.get(k) for k in ('controller','reward','training_level','training_seed','level','demand_seed'))
            if identity in identities:
                if identities[identity] != original:
                    raise ValueError(f'Conflicting duplicate run: {identity}')
                continue
            identities[identity] = original
            r['source'] = str(path.resolve())
            rows.append(r)
    if len(network_hashes)!=1 or len(sumo_versions)!=1:
        raise ValueError('Different network structures or SUMO versions cannot be pooled.')
    # Average held-out demand seeds within a trained model first; SD then uses independent trained models.
    models = {}
    for r in rows:
        k = tuple(r.get(x) for x in ('level','controller','reward','training_level','training_seed'))
        models.setdefault(k,[]).append(r)
    groups = {}
    for k, rr in models.items():
        groups.setdefault(k[:-1],[]).append({m:statistics.mean(r[m] for r in rr) for m in METRICS})
    summary = []
    for k, mm in sorted(groups.items()):
        s = dict(zip(('test_level','controller','reward','training_level'),k))
        s['independent_models'] = len(mm)
        for m in METRICS:
            vals=[r[m] for r in mm]
            s[m+'_mean']=statistics.mean(vals)
            s[m+'_std_across_models']=statistics.stdev(vals) if len(vals)>1 else None
        summary.append(s)
    flat = [{k:v for k,v in r.items() if not isinstance(v,dict)} for r in rows]
    for name,data in [('runs.csv',flat),('summary.csv',summary)]:
        fields=list(dict.fromkeys(k for r in data for k in r))
        with (out/name).open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(data)
    write_json(out/'summary.json',{'protocol_sha256':next(iter(protocols)),'rows':summary,'run_count':len(rows)})
    plot(out,summary)
    trs=''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in [r['test_level'],r['controller'],r['reward'],r['training_level'],r['independent_models'],round(r['penalized_wait_s_per_scheduled_mean'],2),round(r['completion_rate_mean'],3),round(r['mean_queue_vehicles_mean'],2)])+'</tr>' for r in summary)
    (out/'index.html').write_text('''<!doctype html><meta charset="utf-8"><title>SUMO DQN benchmark</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:1300px;margin:30px auto;padding:0 20px;background:#f5f7fa;color:#17202a}table{border-collapse:collapse;background:white;width:100%}th,td{padding:10px;border-bottom:1px solid #ddd;text-align:left}img{max-width:100%}h1{font-size:27px}</style>
<h1>Single intersection: algorithms × rewards × traffic demand</h1>
<p>Pilot results validate execution only. One training seed does not establish algorithm superiority.</p>
<p>Wait = (observed stopped vehicle-seconds + pending vehicle-seconds) / scheduled vehicles. Completion must be read alongside wait.</p>
<img src="comparison.png"><table><tr><th>Test load</th><th>Controller</th><th>Reward</th><th>Train load</th><th>Models</th><th>Wait (s)</th><th>Completion</th><th>Mean queue</th></tr>'''+trs+'</table>',encoding='utf-8')
    return out/'index.html'


def plot(out, rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    labels = sorted({(r['controller'],r['reward'],r['training_level']) for r in rows})
    fig,axes=plt.subplots(1,3,figsize=(15,4.6))
    for ax,level in zip(axes,('low','medium','high')):
        rr=[r for r in rows if r['test_level']==level]
        names=[f'{r["controller"]}\n{r["reward"]}' for r in rr]
        vals=[r['penalized_wait_s_per_scheduled_mean'] for r in rr]
        ax.bar(np.arange(len(rr)),vals,color=['#8594a8' if r['training_level']=='baseline' else {'dqn':'#2877cc','double':'#16a085','dueling':'#e58b25','d3qn':'#884eb9'}.get(r['controller'],'#2877cc') for r in rr])
        ax.set_xticks(np.arange(len(rr)),names,rotation=50,ha='right',fontsize=8)
        ax.set_title(level.upper());ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
        ax.set_ylabel('Observed + pending wait / scheduled vehicle (s)')
    fig.suptitle('Shared SUMO benchmark — check completion rates and independent training seeds')
    fig.tight_layout();fig.savefig(out/'comparison.png',dpi=150);plt.close(fig)
