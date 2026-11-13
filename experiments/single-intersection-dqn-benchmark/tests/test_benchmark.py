from __future__ import annotations
import copy
import csv
import json
from pathlib import Path
import uuid
import unittest
import xml.etree.ElementTree as ET

import numpy as np
import torch

from trafficbench.agent import Agent, QNetwork, td_target
from trafficbench.common import ROOT, load_config
from trafficbench.env import TrafficEnv
from trafficbench.experiment import controller_action, training_demand_seed, train, evaluate
from trafficbench.rewards import reward_value
from trafficbench.scenario import prepare_demand


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.cfg=load_config()
        (ROOT/'tmp/tests').mkdir(parents=True,exist_ok=True)
        # pathlib avoids restrictive temporary-directory ACLs in managed Windows runtimes.
        self.folder=ROOT/'tmp/tests'/uuid.uuid4().hex
        self.folder.mkdir()

    def tearDown(self):
        pass  # Retain small diagnostic artifacts under tmp/tests; no recursive filesystem mutation.

    def test_double_separates_selection_and_evaluation(self):
        rewards=torch.tensor([2.,2.]);discount=torch.tensor([.5,.5]);done=torch.tensor([0.,1.])
        online=torch.tensor([[3.,2.],[3.,2.]])
        target=torch.tensor([[1.,9.],[1.,9.]])
        self.assertTrue(torch.equal(td_target(rewards,discount,done,online,target,False),torch.tensor([6.5,2.])))
        self.assertTrue(torch.equal(td_target(rewards,discount,done,online,target,True),torch.tensor([2.5,2.])))

    def test_dueling_advantage_offset_does_not_change_q(self):
        model=QNetwork([16],True)
        x=torch.ones(3,13)
        before=model(x).detach()
        with torch.no_grad(): model.advantage.bias.add_(5)
        self.assertTrue(torch.allclose(before,model(x),atol=1e-5))
        self.assertTrue(torch.allclose(model(x).mean(1),model.value(model.shared(x/10)).squeeze(1),atol=1e-5))

    def test_all_reward_definitions(self):
        kwargs=dict(stopped=3,active=10,mean_speed=5,speed_limit=10,arrived=2,weighted_arrived=2.5,departed=1)
        for name,value in [('wtmin',-3),('asmax',.5),('ttmin',-10),('ctmax',2),('wctmax',2.5),('tmqmax',-2)]:
            self.assertEqual(reward_value(name,**kwargs),value)
        self.assertEqual(reward_value('asmax',**dict(kwargs,active=0)),0)

    def test_learning_and_checkpoint_for_four_variants(self):
        cfg=copy.deepcopy(self.cfg)
        cfg['learning'].update(hidden_sizes=[32,16],batch_size=8,learning_starts=8)
        for algorithm in ('dqn','double','dueling','d3qn'):
            agent=Agent(cfg,algorithm)
            original=copy.deepcopy(agent.online.state_dict())
            for i in range(20):
                obs=np.full(13,i/20,dtype=np.float32)
                agent.remember(obs,i%2,-float(i+1),obs+.1,i==19,.9**(1 if i%2==0 else 4))
                loss=agent.learn()
            self.assertTrue(np.isfinite(loss))
            self.assertTrue(any(not torch.equal(original[k],v) for k,v in agent.online.state_dict().items()))
            path=self.folder/f'{algorithm}.pt'
            agent.save(path,{'reward':'wtmin'})
            loaded,_=Agent.load(path,cfg)
            self.assertTrue(torch.equal(agent.online(torch.ones(1,13)),loaded.online(torch.ones(1,13))))
            bad=copy.deepcopy(cfg);bad['scenario']['yellow_s']=4
            with self.assertRaises(ValueError): Agent.load(path,bad)

    def test_routes_reproducible_sorted_and_independent_of_controller(self):
        route,m=prepare_demand(self.cfg,'medium',1001,directory=self.folder/'a')
        route2,m2=prepare_demand(self.cfg,'medium',1001,directory=self.folder/'b')
        self.assertEqual(m['sha256'],m2['sha256'])
        departures=[float(v.get('depart')) for v in ET.parse(route).findall('vehicle')]
        self.assertEqual(departures,sorted(departures))
        self.assertEqual(len(departures),m['scheduled'])
        self.assertNotIn(training_demand_seed(11,0),self.cfg['experiment']['evaluation_seeds'])
        _,other=prepare_demand(self.cfg,'medium',1002,directory=self.folder/'c')
        self.assertNotEqual(m['sha256'],other['sha256'])

    def test_sumo_yellow_timing_and_vehicle_conservation(self):
        cfg=copy.deepcopy(self.cfg)
        cfg['scenario'].update(demand_seconds=100,drain_seconds=80)
        env=TrafficEnv(cfg,'medium',out=self.folder/'sumo')
        try:
            obs,_=env.reset()
            self.assertTrue(env.observation_space.contains(obs))
            obs,_,_,_,info=env.step(0)
            self.assertEqual(info['elapsed'],1)
            obs,_,done,_,info=env.step(1)
            self.assertEqual(info['elapsed'],4)
            self.assertEqual(env.phase,1)
            self.assertAlmostEqual(info['discount'],.9**4)
            while not done:
                obs,_,done,_,_=env.step(controller_action(env,obs,'fixed'))
            m=env.metrics()
            self.assertEqual(m['scheduled'],m['arrived']+m['remaining']+m['not_departed'])
            self.assertEqual(m['collisions'],0)
            self.assertEqual(m['simulation_seconds'],180)
        finally:
            env.close()
        with (self.folder/'sumo/seconds.csv').open() as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(sum(int(r['yellow']) for r in rows[:5]),3)

    def test_blocked_vehicles_are_not_mistaken_for_completed_trips(self):
        cfg=copy.deepcopy(self.cfg)
        cfg['scenario'].update(demand_seconds=300,drain_seconds=0)
        cfg['scenario']['loads_vph']['high']=10000
        env=TrafficEnv(cfg,'high',out=self.folder/'blocked')
        try:
            env.reset()
            done=False
            while not done: _,_,done,_,_=env.step(0) # deliberately starve EW traffic
            m=env.metrics()
            self.assertGreater(m['not_departed'],0)
            self.assertGreater(m['pending_vehicle_seconds'],0)
            self.assertLess(m['completion_rate'],1)
            self.assertGreater(m['penalized_wait_s_per_scheduled'],m['observed_wait_s_per_scheduled'])
        finally:
            env.close()

    def test_train_save_evaluate_full_pipeline(self):
        cfg=copy.deepcopy(self.cfg)
        cfg['scenario'].update(demand_seconds=50,drain_seconds=30)
        cfg['learning'].update(episodes=1,hidden_sizes=[32,16],learning_starts=8,batch_size=8)
        model=train(cfg,'double','wtmin','medium',11,self.folder/'training')
        loaded,data=Agent.load(model,cfg)
        self.assertGreater(data['updates'],0)
        self.assertEqual(data['metadata']['state'],'complete')
        result=evaluate(cfg,self.folder/'evaluation',['low','high'],[1001],model=model)
        self.assertEqual(len(result['runs']),2)
        self.assertTrue(all(r['simulation_seconds']==80 for r in result['runs']))
        with (self.folder/'training/training.csv').open() as f:
            row=next(csv.DictReader(f))
        self.assertEqual(int(row['decisions']),data['decisions'])


if __name__=='__main__':
    unittest.main(verbosity=2)
