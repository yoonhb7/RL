from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import subprocess
from .common import ALGOS, REWARDS, LEVELS, ROOT, load_config, provenance, write_json


def main():
    parser=argparse.ArgumentParser(description='Shared single-intersection traffic benchmark')
    parser.add_argument('--config',type=Path,default=ROOT/'configs/shared.json')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor')
    sub.add_parser('build')
    t=sub.add_parser('train')
    t.add_argument('--algorithm',choices=ALGOS,default='dqn')
    t.add_argument('--reward',choices=REWARDS,default='wtmin')
    t.add_argument('--level',choices=LEVELS,default='medium')
    t.add_argument('--seed',type=int,default=11)
    t.add_argument('--episodes',type=int)
    t.add_argument('--out',type=Path,required=True)
    for name in ('evaluate','view','calibrate'):
        e=sub.add_parser(name)
        e.add_argument('--model',type=Path)
        e.add_argument('--controller',choices=('fixed','queue'),default='fixed')
        e.add_argument('--levels',choices=LEVELS,nargs='+',default=['low','medium','high'] if name!='view' else ['medium'])
        e.add_argument('--seeds',type=int,nargs='+',default=[1001,1002,1003] if name!='view' else [1001])
        e.add_argument('--vph',type=float,help='Override total veh/h; requires exactly one level.')
        e.add_argument('--delay',type=int,default=70)
        e.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('plan')
    p.add_argument('--algorithms',choices=ALGOS,nargs='+')
    p.add_argument('--rewards',choices=REWARDS,nargs='+')
    p.add_argument('--levels',choices=LEVELS,nargs='+')
    p.add_argument('--seeds',type=int,nargs='+')
    p.add_argument('--cross-evaluate',action='store_true')
    p.add_argument('--out',type=Path,required=True)
    b=sub.add_parser('batch')
    b.add_argument('--plan',type=Path,required=True)
    b.add_argument('--owner',choices=('A','B','C'))
    b.add_argument('--out',type=Path,required=True)
    r=sub.add_parser('report')
    r.add_argument('--roots',type=Path,nargs='+',required=True)
    r.add_argument('--out',type=Path,required=True)
    a=parser.parse_args()
    cfg=load_config(a.config)
    from .scenario import binary,build_network
    from .experiment import train,evaluate,create_plan,run_batch
    if a.command=='doctor':
        import torch,sys
        print(json.dumps(dict(python=sys.executable,cuda=torch.cuda.is_available(),
                              sumo=binary('sumo'),sumo_version=subprocess.check_output([binary('sumo'),'--version'],text=True).splitlines()[0],
                              **provenance(cfg)),indent=2))
    elif a.command=='build':
        print(build_network(cfg))
    elif a.command=='train':
        if a.episodes is not None:
            if a.episodes<1: parser.error('--episodes must be positive')
            cfg['learning']['episodes']=a.episodes
        print('Model:',train(cfg,a.algorithm,a.reward,a.level,a.seed,a.out))
    elif a.command in ('evaluate','view','calibrate'):
        if a.vph is not None:
            if len(a.levels)!=1: parser.error('--vph requires one level')
            if a.vph<=0 or a.vph*max(cfg['scenario']['direction_shares'].values())/3600>=1:
                parser.error('vph outside generator capacity')
            cfg['scenario']['loads_vph'][a.levels[0]]=a.vph
        if a.command=='calibrate':
            if a.model: parser.error('calibrate uses fixed and queue baselines, not --model')
            for controller in ('fixed','queue'):
                evaluate(cfg,a.out/controller,a.levels,a.seeds,controller=controller)
        else:
            evaluate(cfg,a.out,a.levels,a.seeds,model=a.model,controller=a.controller,gui=a.command=='view',delay=a.delay)
        print('Results:',a.out.resolve())
    elif a.command=='plan':
        p=create_plan(cfg,a.out,a.algorithms,a.rewards,a.levels,a.seeds,a.cross_evaluate)
        print(f'{p["job_count"]} training jobs; {p["evaluation_count"]} held-out evaluations. Plan: {a.out}')
    elif a.command=='batch':
        run_batch(a.plan,a.out,a.owner)
    elif a.command=='report':
        from .report import make_report
        print(make_report(a.roots,a.out))
