"""PedLink-Corridor2: one central DQN controls two four-arm junctions and pedestrians."""
from __future__ import annotations
import argparse
import itertools
from pathlib import Path
import subprocess
import uuid
import xml.etree.ElementTree as ET

import core

np, torch = core.np, core.torch
ROOT = Path(__file__).resolve().parent
SITES = ['J0', 'J1']
SERVICES = ['EW', 'NS', 'PED']
STAGES = SERVICES + ['yellow', 'all_red', 'clearance']
ARMS = ['W', 'E', 'N', 'S']
ACTIONS = np.array(list(itertools.product(range(3), repeat=2)), dtype=np.int32)
OBS_SIZE = 52
INCOMING = {'J0': ['w_in', 'link_w', 'n0_in', 's0_in'],
            'J1': ['link_e', 'e_in', 'n1_in', 's1_in']}
OUTGOING = {'J0': ['w_out', 'link_e', 'n0_out', 's0_out'],
            'J1': ['link_w', 'e_out', 'n1_out', 's1_out']}
FIXED_PERIODS = {'EW': 25, 'NS': 25, 'PED': 15}


def build():
    folder = ROOT / 'network'
    folder.mkdir(parents=True, exist_ok=True)
    nodes, edges, connections = ET.Element('nodes'), ET.Element('edges'), ET.Element('connections')
    positions = {'W': (-100,0), 'J0': (0,0), 'J1': (140,0), 'E': (240,0),
                 'N0': (0,85), 'S0': (0,-85), 'N1': (140,85), 'S1': (140,-85)}
    for ident, (x,y) in positions.items():
        ET.SubElement(nodes, 'node', id=ident, x=str(x), y=str(y),
                      type='traffic_light' if ident in SITES else 'dead_end')
    pairs = [('w', 'W', 'J0'), ('e', 'E', 'J1'), ('n0','N0','J0'),
             ('s0','S0','J0'), ('n1','N1','J1'), ('s1','S1','J1')]
    for name, outer, center in pairs:
        for suffix, source, target in [('in',outer,center), ('out',center,outer)]:
            ET.SubElement(edges, 'edge', id=name+'_'+suffix, **{'from': source, 'to': target},
                          numLanes='1', width='3.2', sidewalkWidth='3', speed='11.11')
    for ident, source, target in [('link_e','J0','J1'), ('link_w','J1','J0')]:
        ET.SubElement(edges, 'edge', id=ident, **{'from': source,'to':target},
                      numLanes='1', width='3.2', sidewalkWidth='3', speed='11.11')
    for site in SITES:
        incoming, outgoing = INCOMING[site], OUTGOING[site]
        # Straight-only motor traffic: one lane per approach, no turning movements.
        for source, destination in zip(incoming, [outgoing[1], outgoing[0], outgoing[3], outgoing[2]]):
            ET.SubElement(connections, 'connection', **{'from':source,'to':destination})
        for arm, source, destination in zip(ARMS, incoming, outgoing):
            ET.SubElement(connections, 'crossing', node=site, edges=f'{source} {destination}', width='4')
    for name, tree in [('nodes.nod.xml',nodes), ('edges.edg.xml',edges), ('connections.con.xml',connections)]:
        ET.ElementTree(tree).write(folder/name, encoding='utf-8', xml_declaration=True)
    command = [core.binary('netconvert'), '--node-files', str(folder/'nodes.nod.xml'),
               '--edge-files', str(folder/'edges.edg.xml'), '--connection-files', str(folder/'connections.con.xml'),
               '--no-turnarounds', 'true', '--walkingareas', 'true', '--output-file', str(folder/'corridor.net.xml')]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(result.stdout+result.stderr)
    print(result.stdout.strip())


def schema():
    return {'version':1, 'network_sha256':core.sha256(ROOT/'network/corridor.net.xml'),
            'experiment':'PedLink-Corridor2', 'agent_count':1, 'junction_count':2, 'crossing_count':8,
            'observation':'52-features-two-junctions', 'services':SERVICES,
            'actions':'lexicographic [J0,J1] ternary service requests; 9 joint actions',
            'decision_s':core.DECISION, 'min_vehicle_s':15, 'min_pedestrian_s':10,
            'max_vehicle_with_competing_demand_s':60, 'max_pedestrian_with_vehicle_s':30,
            'yellow_s':4, 'all_red_s':2, 'clearance_min_s':10,
            'wait_limit_s':core.WAIT_LIMIT, 'switch_weight':core.SWITCH_WEIGHT,
            'cost_aggregation':'mean across two junctions', 'horizon_s':core.HORIZON, 'demand_end_s':core.DEMAND_END}


def demand(folder, seed, profile):
    rng = np.random.default_rng(seed)
    vehicles, people = [], []
    ew_rate, ns_rate = (540,180) if profile=='vehicle-heavy' else (360,120)
    routes = [('east','w_in link_e e_out',ew_rate), ('west','e_in link_w w_out',ew_rate)]
    routes += [(f'{site}-{direction}', f'{origin} {target}', ns_rate)
               for site in SITES for direction,origin,target in
               [('south',INCOMING[site][2],OUTGOING[site][3]), ('north',INCOMING[site][3],OUTGOING[site][2])]]
    for name, route, rate in routes:
        for i, depart in enumerate(core.arrivals(rng,rate)):
            vehicles.append((f'{name}-{i}',depart,route))
    network = ET.parse(ROOT/'network/corridor.net.xml').getroot()
    lengths = {edge.get('id'):float(edge.find('lane').get('length'))
               for edge in network.findall('edge') if not edge.get('id').startswith(':')}
    for j, site in enumerate(SITES):
        for arm_index, arm in enumerate(ARMS):
            departures = core.arrivals(rng,30 if profile=='balanced' else 15)
            if profile=='ped-burst' and (j,arm) in [(0,'N'),(1,'S')]:
                departures += [120+j*30+i*.5 for i in range(18)]
            source, target = INCOMING[site][arm_index], OUTGOING[site][arm_index]
            for i, depart in enumerate(sorted(departures)):
                people.append((f'{site}-{arm}-ped-{i}',depart,f'{source} {target}',j,arm,
                               max(1,lengths[source]-15)))
    tree = ET.Element('routes')
    ET.SubElement(tree,'vType',id='car',vClass='passenger',carFollowModel='IDM',maxSpeed='11.11',
                  color='40,125,235',length='5',minGap='2.5')
    ET.SubElement(tree,'vType',id='walker',vClass='pedestrian',maxSpeed='1.3',color='240,100,30')
    events = [(t,'vehicle',ident,route,None) for ident,t,route in vehicles]
    events += [(t,'person',ident,route,pos) for ident,t,route,_,_,pos in people]
    for depart,kind,ident,route,pos in sorted(events):
        attrs = {'id':ident,'depart':f'{depart:.3f}','type':'car' if kind=='vehicle' else 'walker'}
        if kind=='person':
            attrs['departPos'] = f'{pos:.3f}'
        element = ET.SubElement(tree,kind,**attrs)
        ET.SubElement(element,'route' if kind=='vehicle' else 'walk',edges=route,
                      **({'arrivalPos':'15'} if kind=='person' else {}))
    path = folder/'demand.rou.xml'
    ET.ElementTree(tree).write(path,encoding='utf-8',xml_declaration=True)
    return path,vehicles,people


class Junction:
    def __init__(self,variant):
        self.variant,self.stage,self.target = variant,'EW',0
        self.elapsed = self.switches = 0

    def mask(self,pedestrians,veh_ew,veh_ns,oldest):
        if self.stage not in SERVICES:
            return np.array([i==self.target for i in range(3)])
        current = SERVICES.index(self.stage)
        mask = np.ones(3,dtype=bool)
        if self.elapsed < (10 if self.stage=='PED' else 15):
            return np.array([i==current for i in range(3)])
        if self.stage=='PED':
            if self.elapsed>=30 and veh_ew+veh_ns:
                mask[2]=False
        elif pedestrians and (self.elapsed>=60 or (self.variant!='basic' and oldest>=core.WAIT_LIMIT)):
            return np.array([False,False,True])
        elif self.elapsed>=60 and (veh_ns if self.stage=='EW' else veh_ew):
            return np.array([i==1-current for i in range(3)])
        return mask

    def request(self,action,oldest):
        changed = self.stage in SERVICES and SERVICES.index(self.stage)!=int(action)
        cost = core.SWITCH_WEIGHT*max(0,1-oldest/core.WAIT_LIMIT) if changed and self.variant=='adaptive' else 0
        if changed:
            self.previous,self.target = self.stage,int(action)
            self.stage = 'clearance' if self.previous=='PED' else 'yellow'
            self.elapsed=0
            self.switches+=1
        return bool(changed),float(cost)

    def advance(self,occupied):
        if self.stage=='yellow' and self.elapsed>=4:
            self.stage,self.elapsed='all_red',0
        elif self.stage=='all_red' and self.elapsed>=2:
            self.stage,self.elapsed=SERVICES[self.target],0
        elif self.stage=='clearance' and self.elapsed>=10 and not occupied:
            self.stage,self.elapsed=SERVICES[self.target],0


class Environment(core.Environment):
    def __init__(self,folder,seed,profile,variant,*,gui=False,delay=80,record_motion=False):
        self.folder=Path(folder).resolve()
        self.folder.mkdir(parents=True)
        self.route_file,vehicles,people=demand(self.folder,seed,profile)
        self.planned={'vehicle':{v[0]:v[1] for v in vehicles},'person':{p[0]:p[1] for p in people}}
        self.person_site={p[0]:p[3] for p in people}
        self.person_arm={p[0]:p[4] for p in people}
        self.crossing_visits={p[0]:set() for p in people}
        self.departed={'vehicle':set(),'person':set()}
        self.arrived={'vehicle':set(),'person':set()}
        self.wait={'vehicle':{},'person':{}}
        self.previous_stopped=set()
        self.stops=self.collisions=self.teleports=self.time=0
        self.trace,self.tick_trace=[],[]
        self.record_motion,self.motion=record_motion,[]
        self.controls=[Junction(variant) for _ in SITES]
        self.profile,self.seed,self.variant,self.gui=profile,seed,variant,gui
        self.signals=[]
        net=ET.parse(ROOT/'network/corridor.net.xml').getroot()
        self.crossings={e.get('id') for e in net.findall('edge') if e.get('function')=='crossing'}
        self.vehicle_lanes={site:[next(l.get('id') for l in net.find(f"edge[@id='{edge}']").findall('lane')
                             if l.get('allow')!='pedestrian') for edge in INCOMING[site]] for site in SITES}
        for site in SITES:
            count=len(net.find(f"tlLogic[@id='{site}']/phase").get('state'))
            vehicle_indices={int(c.get('linkIndex')) for c in net.findall('connection')
                             if c.get('tl')==site and c.get('from') in INCOMING[site]}
            ew={int(c.get('linkIndex')) for c in net.findall('connection')
                if c.get('tl')==site and c.get('from') in INCOMING[site][:2]}
            ns=vehicle_indices-ew
            greens={'EW':ew,'NS':ns,'PED':set(range(count))-vehicle_indices}
            assert len(ew)==len(ns)==2 and len(greens['PED'])>=4
            signal={group:''.join('G' if i in indices else 'r' for i in range(count)) for group,indices in greens.items()}
            signal.update(all_red='r'*count,clearance='r'*count,vehicle_indices=sorted(vehicle_indices),
                          pedestrian_indices=sorted(greens['PED']))
            self.signals.append(signal)
        command=[core.binary('sumo-gui' if gui else 'sumo'),'--net-file',str(ROOT/'network/corridor.net.xml'),
                 '--route-files',str(self.route_file),'--step-length','1','--seed',str(seed),
                 '--time-to-teleport','-1','--no-step-log','true','--collision.action','warn',
                 '--tripinfo-output',str(self.folder/'tripinfo.xml'),'--tripinfo-output.write-unfinished','true']
        if gui:
            settings=ET.parse(ROOT/'view.xml')
            settings.write(self.folder/'view.xml',encoding='utf-8')
            command+=['--start','--quit-on-end','--delay',str(delay),'--window-size','1280,800','--window-pos','0,0',
                      '--gui-settings-file',str(self.folder/'view.xml')]
        self.connection=core.start_sumo(command,'two-junctions-'+uuid.uuid4().hex,self.folder)
        for site,signal in zip(SITES,self.signals):
            self.connection.trafficlight.setRedYellowGreenState(site,signal['EW'])
        if gui:
            self.connection.gui.setBoundary('View #0',-15,-10,355,200)
            self.connection.poi.add('status',170,180,(235,241,230,255),poiType='ONE CENTRAL DQN / TWO JUNCTIONS',width=.1,height=.1)
            self.lamps=self.draw_signals()
        self.snapshot=self.read_state()
        self.raw_return=self.cost_sum=0.

    def draw_signals(self):
        lamps=[]
        for j,site in enumerate(SITES):
            x,y=100+j*140,85
            self.connection.poi.add('label-'+site,x,145,(235,241,230,255),poiType=site+' / CENTRAL DQN',width=.1,height=.1)
            heads=[('W',x-23,y-10,'EW'),('E',x+23,y+10,'EW'),('N',x-10,y+23,'NS'),('S',x+10,y-23,'NS'),
                   ('PW',x-17,y+15,'PED'),('PE',x+17,y-15,'PED'),('PN',x+15,y+17,'PED'),('PS',x-15,y-17,'PED')]
            for suffix,hx,hy,group in heads:
                aspects=['red','green'] if group=='PED' else ['red','yellow','green']
                self.connection.polygon.add(site+suffix,[(hx-1.8,hy-1.8),(hx+1.8,hy-1.8),
                    (hx+1.8,hy+(len(aspects)-1)*2.5+1.8),(hx-1.8,hy+(len(aspects)-1)*2.5+1.8)],
                    (25,30,35,255),fill=True,layer=10)
                for k,aspect in enumerate(aspects):
                    ident=site+suffix+aspect
                    self.connection.poi.add(ident,hx,hy+(len(aspects)-1-k)*2.5,(45,50,50,255),layer=20,width=2,height=2)
                    lamps.append((ident,j,group,aspect))
        return lamps

    def update_signals(self):
        colors={'red':(245,55,55,255),'yellow':(255,190,30,255),'green':(45,205,100,255)}
        for ident,j,group,aspect in self.lamps:
            control=self.controls[j]
            current='green' if control.stage==group else 'yellow' if control.stage=='yellow' and control.previous==group else 'red'
            self.connection.poi.setColor(ident,colors[aspect] if aspect==current else (45,50,50,255))

    def read_state(self):
        c=self.connection
        vehicles,people=c.vehicle.getIDList(),c.person.getIDList()
        for kind,departed,arrived in [('vehicle',c.simulation.getDepartedIDList(),c.simulation.getArrivedIDList()),
                                     ('person',c.simulation.getDepartedPersonIDList(),c.simulation.getArrivedPersonIDList())]:
            self.departed[kind].update(departed)
            self.arrived[kind].update(arrived)
        v_wait={v:c.vehicle.getWaitingTime(v) for v in vehicles}
        p_wait={p:c.person.getWaitingTime(p) for p in people}
        roads={p:c.person.getRoadID(p) for p in people}
        stopped_v={v for v in vehicles if v_wait[v]>0}
        stopped_p={p for p in people if p_wait[p]>0}
        for kind,ids,stopped in [('vehicle',vehicles,stopped_v),('person',people,stopped_p)]:
            for ident in ids:
                self.wait[kind][ident]=self.wait[kind].get(ident,0)+(int(ident in stopped) if self.time else 0)
        for p in people:
            if roads[p] in self.crossings:
                self.crossing_visits[p].add(roads[p])
        self.stops+=len(stopped_v-self.previous_stopped)
        self.previous_stopped=stopped_v
        self.collisions+=c.simulation.getCollidingVehiclesNumber()
        self.teleports+=c.simulation.getStartingTeleportNumber()
        pending=sum(t<self.time and ident not in self.departed['vehicle'] for ident,t in self.planned['vehicle'].items())
        local=[]
        for j,site in enumerate(SITES):
            waiting=[p for p in stopped_p if self.person_site[p]==j and roads[p] not in self.crossings]
            lanes=self.vehicle_lanes[site]
            halts=[c.lane.getLastStepHaltingNumber(lane) for lane in lanes]
            local_vehicles=[v for lane in lanes for v in c.lane.getLastStepVehicleIDs(lane)]
            local.append({'waiting':waiting,'crossing':[p for p in people if roads[p] in self.crossings and roads[p].startswith(':'+site+'_')],
                          'oldest_p':max((p_wait[p] for p in waiting),default=0),
                          'oldest_v':max((v_wait[v] for v in local_vehicles),default=0),
                          'q_p':[sum(self.person_arm[p]==arm for p in waiting) for arm in ARMS],
                          'halts':halts,'counts':[c.lane.getLastStepVehicleNumber(lane) for lane in lanes],
                          'veh_ew':sum(halts[:2]),'veh_ns':sum(halts[2:])})
        return {'vehicle_ids':vehicles,'person_ids':people,'stopped_v':len(stopped_v),'stopped_p':len(stopped_p),
                'pending_v':pending,'sites':local}

    def observe(self):
        values=[self.time/core.HORIZON]
        for local,control in zip(self.snapshot['sites'],self.controls):
            values += [n/20 for n in local['counts']]+[n/15 for n in local['halts']]+[n/10 for n in local['q_p']]
            values += [local['oldest_p']/60,local['oldest_v']/60,len(local['crossing'])/10,control.elapsed/60]
            values += [float(control.stage==stage) for stage in STAGES]
            values += [float(control.target==i) for i in range(3)]
        values += [self.snapshot['pending_v']/10]
        observation=np.clip(values,0,2).astype(np.float32)
        assert observation.shape==(OBS_SIZE,)
        return observation

    def mask(self):
        masks=[control.mask(len(local['waiting']),local['veh_ew'],local['veh_ns'],local['oldest_p'])
               for control,local in zip(self.controls,self.snapshot['sites'])]
        return np.array([all(mask[request] for mask,request in zip(masks,requests)) for requests in ACTIONS])

    def step(self,action):
        if not self.mask()[action]:
            raise ValueError('Joint action violates signal constraints')
        requests=ACTIONS[action]
        rows,costs=[],[]
        for site,control,local,request in zip(SITES,self.controls,self.snapshot['sites'],requests):
            before,elapsed=control.stage,control.elapsed
            changed,cost=control.request(request,local['oldest_p'])
            rows.append({'site':site,'stage_before':before,'elapsed_before':elapsed,'action':int(request),
                         'target_changed':changed,'oldest_ped_wait':local['oldest_p'],'switch_cost':cost})
            costs.append(cost)
        cost=float(np.mean(costs))
        if self.gui:
            label=' | '.join(f'{site} {c.stage} ped:{s["oldest_p"]:.0f}s' for site,c,s in zip(SITES,self.controls,self.snapshot['sites']))
            self.connection.poi.setType('status',f'ONE DQN / {self.variant.upper()} / t={self.time}s | '+label)
        stopped_seconds=0
        for _ in range(core.DECISION):
            tick=[]
            for site,control,signal,local in zip(SITES,self.controls,self.signals,self.snapshot['sites']):
                occupied=bool(local['crossing'])
                control.advance(occupied)
                state=signal[control.previous].replace('G','y') if control.stage=='yellow' else signal[control.stage]
                self.connection.trafficlight.setRedYellowGreenState(site,state)
                tick.append({'site':site,'stage':control.stage,'target':control.target,'elapsed':control.elapsed,
                             'crossing_occupied_before':occupied,'signal':state})
            if self.gui:
                self.update_signals()
            self.tick_trace.append({'time':self.time,'sites':tick})
            self.connection.simulationStep()
            self.time+=1
            for control in self.controls:
                control.elapsed+=1
            self.snapshot=self.read_state()
            if self.record_motion and 100<=self.time<=240 and self.time%2==0:
                c=self.connection
                self.motion.append({'time':self.time,'stages':[control.stage for control in self.controls],
                    'vehicles':[{'id':v,'xy':c.vehicle.getPosition(v),'angle':c.vehicle.getAngle(v)} for v in self.snapshot['vehicle_ids']],
                    'persons':[{'id':p,'xy':c.person.getPosition(p)} for p in self.snapshot['person_ids']]})
            if self.gui and self.time%60==0:
                core.write_json(self.folder/'progress.json',{'simulation_seconds':self.time,'vehicle_count':len(self.snapshot['vehicle_ids']),
                                'person_count':len(self.snapshot['person_ids'])})
            stopped_seconds+=self.snapshot['stopped_v']+self.snapshot['pending_v']+2*self.snapshot['stopped_p']
        reward=-stopped_seconds/100-cost
        self.raw_return-=stopped_seconds/100
        self.cost_sum+=cost
        self.trace.append({'time':self.time-core.DECISION,'action_id':int(action),'actions':requests.tolist(),
                           'sites':rows,'oldest_ped_wait':max(r['oldest_ped_wait'] for r in rows),
                           'switch_cost':cost,'reward':reward})
        return self.observe(),reward,self.time>=core.HORIZON,self.mask()

    def finish(self):
        if self.record_motion:
            core.write_json(self.folder/'motion.json',self.motion)
        result=super().finish(switches=sum(c.switches for c in self.controls),extra={
            'experiment':'PedLink-Corridor2','agent_count':1,'junction_count':2,'crossing_count':len(self.crossings),
            'site_switches':{site:c.switches for site,c in zip(SITES,self.controls)},
            'arrived_pedestrians_crossed':sum(bool(self.crossing_visits[p]) for p in self.arrived['person']),
            'pedestrians_crossed_multiple':sum(len(v)>1 for v in self.crossing_visits.values())})
        return result


def rule_action(env,controller):
    choices=[]
    for local,signal in zip(env.snapshot['sites'],env.controls):
        legal=signal.mask(len(local['waiting']),local['veh_ew'],local['veh_ns'],local['oldest_p'])
        if controller=='fixed':
            requested=signal.target if signal.stage not in SERVICES else SERVICES.index(signal.stage)
            if signal.stage in SERVICES and signal.elapsed>=FIXED_PERIODS[signal.stage]:
                requested=(requested+1)%3
            choices.append(requested if legal[requested] else int(np.flatnonzero(legal)[0]))
        else:
            scores=np.array([local['veh_ew'],local['veh_ns'],2*len(local['waiting'])+local['oldest_p']/10],dtype=float)
            scores[~legal]=-np.inf
            choices.append(int(scores.argmax()))
    return int(np.flatnonzero((ACTIONS==choices).all(axis=1))[0])


def evaluate_rules(args):
    args.out.mkdir(parents=True)
    rows=[]
    for controller in args.controllers:
        for profile in args.profiles:
            for seed in args.seeds:
                env=Environment(args.out/f'{controller}-{profile}-{seed}',seed,profile,'basic')
                try:
                    done=False
                    while not done:
                        _,_,done,_=env.step(rule_action(env,controller))
                    row=env.finish()
                    row['controller']=controller
                    rows.append(row)
                    print(f'{controller} {profile} {seed}: car={row["vehicle"]["mean_wait_s"]:.2f} ped={row["person"]["mean_wait_s"]:.2f}',flush=True)
                finally:
                    env.close()
    core.write_json(args.out/'evaluation.json',{'controllers':args.controllers,'results':rows})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('build')
    training=sub.add_parser('train')
    training.add_argument('--variant',choices=['basic','priority','adaptive'],required=True)
    training.add_argument('--episodes',type=int,default=30)
    training.add_argument('--seed',type=int,default=42)
    training.add_argument('--out',type=Path,required=True)
    for name in ['evaluate','view','record','baselines']:
        p=sub.add_parser(name)
        if name=='baselines':
            p.add_argument('--controllers',nargs='+',choices=['fixed','queue'],default=['fixed','queue'])
        else:
            p.add_argument('--model',type=Path,default=ROOT/'results/train-adaptive/model.pt')
        p.add_argument('--out',type=Path,required=True)
        p.add_argument('--profiles',nargs='+',choices=core.PROFILES,default=['ped-burst'] if name in ['view','record'] else core.PROFILES)
        p.add_argument('--seeds',nargs='+',type=int,default=[1001] if name in ['view','record'] else [1001,1002,1003])
        p.add_argument('--delay',type=int,default=80)
    args=parser.parse_args()
    torch.set_num_threads(1)
    if args.command=='build':
        build()
    elif args.command=='train':
        if args.episodes<2 or args.seed<0:
            parser.error('Use at least two episodes and a nonnegative seed')
        core.train(args,environment=Environment,obs_size=OBS_SIZE,actions=len(ACTIONS),checkpoint_schema=schema)
    else:
        if args.delay<0 or min(args.seeds)<0:
            parser.error('Delay and seeds must be nonnegative')
        if args.command=='baselines':
            evaluate_rules(args)
        else:
            core.evaluate(args,environment=Environment,checkpoint_schema=schema)


if __name__=='__main__':
    main()
