"""PedLink-DQN: one central DQN controls four pedestrian crossings."""
from __future__ import annotations
import argparse
import itertools
from pathlib import Path
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
import core as single
np, torch = single.np, single.torch
SITES = ['C1', 'C2', 'C3', 'C4']
ACTIONS = np.array(list(itertools.product([0, 1], repeat=4)), dtype=np.int32)
OBS_SIZE = 62


def build():
    folder = ROOT / 'network'
    folder.mkdir(parents=True, exist_ok=True)
    nodes, edges, connections = ET.Element('nodes'), ET.Element('edges'), ET.Element('connections')
    ET.SubElement(nodes, 'node', id='W', x='-70', y='0', type='dead_end')
    ET.SubElement(nodes, 'node', id='E', x='250', y='0', type='dead_end')
    for i, site in enumerate(SITES):
        ET.SubElement(nodes, 'node', id=site, x=str(i * 60), y='0', type='traffic_light')
        for side, y in [('N', 22), ('S', -22)]:
            ET.SubElement(nodes, 'node', id=side + site, x=str(i * 60 + 8), y=str(y), type='dead_end')
        ET.SubElement(edges, 'edge', id='N' + site, **{'from': 'N' + site, 'to': site},
                      numLanes='1', width='3', speed='1.3', allow='pedestrian', spreadType='center')
        ET.SubElement(edges, 'edge', id='S' + site, **{'from': site, 'to': 'S' + site},
                      numLanes='1', width='3', speed='1.3', allow='pedestrian', spreadType='center')
        ET.SubElement(connections, 'connection', **{'from': f'e{i}', 'to': f'e{i+1}'}, fromLane='0', toLane='0')
        ET.SubElement(connections, 'connection', **{'from': f'w{i+1}', 'to': f'w{i}'}, fromLane='0', toLane='0')
        ET.SubElement(connections, 'crossing', node=site, edges=f'e{i+1} w{i+1}', width='4')
    vertices = ['W', *SITES, 'E']
    for i, (left, right) in enumerate(zip(vertices, vertices[1:])):
        for ident, source, target in [(f'e{i}', left, right), (f'w{i}', right, left)]:
            ET.SubElement(edges, 'edge', id=ident, **{'from': source, 'to': target},
                          numLanes='1', width='3.2', speed='11.11', disallow='pedestrian')
    for name, tree in [('nodes.nod.xml', nodes), ('edges.edg.xml', edges), ('connections.con.xml', connections)]:
        ET.ElementTree(tree).write(folder / name, encoding='utf-8', xml_declaration=True)
    result = subprocess.run([single.binary('netconvert'), '--node-files', str(folder / 'nodes.nod.xml'),
        '--edge-files', str(folder / 'edges.edg.xml'), '--connection-files', str(folder / 'connections.con.xml'),
        '--no-turnarounds', 'true', '--output-file', str(folder / 'corridor.net.xml')],
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def schema():
    return {**single.signal_schema(), 'network_sha256': single.sha256(ROOT / 'network/corridor.net.xml'),
            'observation': '62-features-four-sites', 'sites': SITES,
            'actions': 'lexicographic four binary requests', 'cost_aggregation': 'mean across four sites'}


def demand(folder, seed, profile):
    rng = np.random.default_rng(seed)
    vehicles, people = [], []
    vehicle_rate = 750 if profile == 'vehicle-heavy' else 450
    for name, route in [('east', 'e0 e1 e2 e3 e4'), ('west', 'w4 w3 w2 w1 w0')]:
        for i, depart in enumerate(single.arrivals(rng, vehicle_rate)):
            vehicles.append((f'{name}-{i}', depart, route))
    for index, site in enumerate(SITES):
        departures = single.arrivals(rng, 90 if profile == 'balanced' else 45)
        if profile == 'ped-burst':
            # Two different crossings receive bursts at different times.
            if index in (1, 3):
                departures += [120 + index * 15 + i * .5 for i in range(20)]
        for i, depart in enumerate(sorted(departures)):
            route = f'N{site} S{site}' if rng.random() < .5 else f'S{site} N{site}'
            people.append((f'{site}-ped-{i}', depart, route, index))
    tree = ET.Element('routes')
    ET.SubElement(tree, 'vType', id='car', vClass='passenger', carFollowModel='IDM', maxSpeed='11.11',
                  color='40,125,235', length='5', minGap='2.5')
    ET.SubElement(tree, 'vType', id='walker', vClass='pedestrian', maxSpeed='1.3', color='240,100,30')
    events = [(t, 'vehicle', ident, route) for ident, t, route in vehicles]
    events += [(t, 'person', ident, route) for ident, t, route, _ in people]
    for depart, kind, ident, route in sorted(events):
        element = ET.SubElement(tree, kind, id=ident, depart=f'{depart:.3f}', type='car' if kind == 'vehicle' else 'walker')
        ET.SubElement(element, 'route' if kind == 'vehicle' else 'walk', edges=route)
    path = folder / 'demand.rou.xml'
    ET.ElementTree(tree).write(path, encoding='utf-8', xml_declaration=True)
    return path, vehicles, people


class Environment(single.Environment):
    def __init__(self, folder, seed, profile, variant, *, gui=False, delay=80, capture=None):
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True)
        self.route_file, vehicles, people = demand(self.folder, seed, profile)
        self.planned = {'vehicle': {v[0]: v[1] for v in vehicles}, 'person': {p[0]: p[1] for p in people}}
        self.person_site = {p[0]: p[3] for p in people}
        self.ped_origin = {p[0]: p[2].split()[0] for p in people}
        self.departed = {'vehicle': set(), 'person': set()}
        self.arrived = {'vehicle': set(), 'person': set()}
        self.wait = {'vehicle': {}, 'person': {}}
        self.previous_stopped = set()
        self.stops = self.collisions = self.teleports = self.time = 0
        self.trace, self.tick_trace = [], []
        self.controls = [single.Crossing(variant) for _ in SITES]
        self.profile, self.seed, self.variant, self.gui = profile, seed, variant, gui
        self.signals = []
        net = ET.parse(ROOT / 'network/corridor.net.xml').getroot()
        for i, site in enumerate(SITES):
            size = len(net.find(f"tlLogic[@id='{site}']/phase").get('state'))
            links = {int(c.get('linkIndex')) for c in net.findall('connection')
                     if c.get('tl') == site and c.get('from') in (f'e{i}', f'w{i+1}')}
            crossing = next(e.get('id') for e in net.findall('edge')
                            if e.get('function') == 'crossing' and e.get('id').startswith(':' + site + '_'))
            vehicle = ''.join('G' if j in links else 'r' for j in range(size))
            self.signals.append({'vehicle': vehicle, 'yellow': vehicle.replace('G', 'y'),
                                 'pedestrian': ''.join('r' if j in links else 'G' for j in range(size)),
                                 'to_pedestrian': 'r' * size, 'clearance': 'r' * size, 'crossing': crossing})
        command = [single.binary('sumo-gui' if gui else 'sumo'), '--net-file', str(ROOT / 'network/corridor.net.xml'),
                   '--route-files', str(self.route_file), '--step-length', '1', '--seed', str(seed),
                   '--time-to-teleport', '-1', '--no-step-log', 'true', '--collision.action', 'warn',
                   '--tripinfo-output', str(self.folder / 'tripinfo.xml'), '--tripinfo-output.write-unfinished', 'true']
        if gui:
            settings = ET.parse(single.ROOT / 'view.xml')
            if capture:
                (self.folder / 'frames').mkdir()
                start, duration = capture
                for t in range(start, start + duration, 2):
                    ET.SubElement(settings.getroot(), 'snapshot', file=(self.folder / 'frames' / f'{t:04d}.png').as_posix(), time=str(t))
            settings.write(self.folder / 'view.xml', encoding='utf-8')
            command += ['--start', '--quit-on-end', '--delay', str(delay), '--gui-settings-file', str(self.folder / 'view.xml')]
        self.connection = single.start_sumo(command, 'four-crossings-' + uuid.uuid4().hex, self.folder)
        for site, signal in zip(SITES, self.signals):
            self.connection.trafficlight.setRedYellowGreenState(site, signal['vehicle'])
        if gui:
            self.connection.gui.setBoundary('View #0', -10, -20, 330, 80)
            self.connection.poi.add('status', 160, 83, (235, 241, 230, 255), poiType='Four crossings DQN', width=.1, height=.1)
            self.lamps = self.draw_signals()
        self.snapshot = self.read_state()
        self.raw_return = self.cost_sum = 0.0

    def draw_signals(self):
        lamps = []
        for i, site in enumerate(SITES):
            center = 70 + i * 60
            self.connection.poi.add('label-' + site, center, 55, (235, 241, 230, 255), poiType=site, width=.1, height=.1)
            for suffix, x, y, group, aspects in [
                ('west', center - 7, 10, 'vehicle', ['red', 'yellow', 'green']),
                ('east', center + 10, 35, 'vehicle', ['red', 'yellow', 'green']),
                ('north', center + 6, 31, 'person', ['red', 'green']),
                ('south', center - 3, 12, 'person', ['red', 'green'])]:
                top = y + (len(aspects) - 1) * 3
                shape = [(x-2, y-2), (x+2, y-2), (x+2, top+2), (x-2, top+2)]
                self.connection.polygon.add(site + suffix, shape, (25, 30, 35, 255), fill=True, layer=10)
                for j, aspect in enumerate(aspects):
                    ident = site + suffix + aspect
                    self.connection.poi.add(ident, x, top-j*3, (45, 50, 50, 255), layer=20, width=2.5, height=2.5)
                    lamps.append((ident, i, group, aspect))
        return lamps

    def update_signals(self):
        colors = {'red': (245,55,55,255), 'yellow': (255,190,30,255), 'green': (45,205,100,255)}
        for ident, i, group, aspect in self.lamps:
            stage = self.controls[i].stage
            current = ('green' if stage == 'vehicle' else 'yellow' if stage == 'yellow' else 'red') if group == 'vehicle' else ('green' if stage == 'pedestrian' else 'red')
            self.connection.poi.setColor(ident, colors[aspect] if aspect == current else (45,50,50,255))

    def read_state(self):
        c = self.connection
        vehicles, people = c.vehicle.getIDList(), c.person.getIDList()
        self.departed['vehicle'].update(c.simulation.getDepartedIDList())
        self.departed['person'].update(c.simulation.getDepartedPersonIDList())
        self.arrived['vehicle'].update(c.simulation.getArrivedIDList())
        self.arrived['person'].update(c.simulation.getArrivedPersonIDList())
        v_wait = {v: c.vehicle.getWaitingTime(v) for v in vehicles}
        p_wait = {p: c.person.getWaitingTime(p) for p in people}
        roads = {p: c.person.getRoadID(p) for p in people}
        next_edges = {p: c.person.getNextEdge(p) for p in people}
        stopped_v, stopped_p = {v for v in vehicles if v_wait[v] > 0}, {p for p in people if p_wait[p] > 0}
        for kind, ids, stopped in [('vehicle', vehicles, stopped_v), ('person', people, stopped_p)]:
            for ident in ids:
                self.wait[kind][ident] = self.wait[kind].get(ident, 0) + (int(ident in stopped) if self.time else 0)
        self.stops += len(stopped_v - self.previous_stopped)
        self.previous_stopped = stopped_v
        self.collisions += c.simulation.getCollidingVehiclesNumber()
        self.teleports += c.simulation.getStartingTeleportNumber()
        pending = sum(t < self.time and ident not in self.departed['vehicle'] for ident, t in self.planned['vehicle'].items())
        local = []
        for i, site in enumerate(SITES):
            crossing = self.signals[i]['crossing']
            waiting = [p for p in stopped_p if self.person_site[p] == i and next_edges[p] == crossing]
            lanes = [f'e{i}_0', f'w{i+1}_0']
            stopped_here = [v for lane in lanes for v in c.lane.getLastStepVehicleIDs(lane) if v in stopped_v]
            local.append({'waiting': waiting, 'crossing': [p for p in people if roads[p] == crossing],
                          'stopped_v': len(stopped_here), 'oldest_p': max((p_wait[p] for p in waiting), default=0),
                          'oldest_v': max((v_wait[v] for v in stopped_here), default=0),
                          'q_n': sum(self.ped_origin[p] == 'N' + site for p in waiting),
                          'q_s': sum(self.ped_origin[p] == 'S' + site for p in waiting),
                          'halts': [c.lane.getLastStepHaltingNumber(l) for l in lanes],
                          'counts': [c.lane.getLastStepVehicleNumber(l) for l in lanes]})
        return {'vehicle_ids': vehicles, 'person_ids': people, 'stopped_v': len(stopped_v),
                'stopped_p': len(stopped_p), 'pending_v': pending, 'sites': local}

    def observe(self):
        values = [self.time / single.HORIZON]
        for local, control in zip(self.snapshot['sites'], self.controls):
            values += [local['halts'][0]/12, local['halts'][1]/12, local['counts'][0]/16, local['counts'][1]/16,
                       local['q_n']/15, local['q_s']/15, local['oldest_p']/60, local['oldest_v']/60,
                       len(local['crossing'])/10, control.elapsed/60]
            values += [float(control.stage == stage) for stage in single.STAGES]
        values += [self.snapshot['pending_v']/10]
        return np.clip(values, 0, 2).astype(np.float32)

    def mask(self):
        masks = [control.mask(len(local['waiting']), local['stopped_v'], local['oldest_p'])
                 for control, local in zip(self.controls, self.snapshot['sites'])]
        return np.array([all(mask[bit] for mask, bit in zip(masks, bits)) for bits in ACTIONS])

    def step(self, action):
        if not self.mask()[action]:
            raise ValueError('Joint action violates a local crossing constraint')
        bits = ACTIONS[action]
        local_trace, costs = [], []
        for i, (control, local, bit) in enumerate(zip(self.controls, self.snapshot['sites'], bits)):
            before = control.stage
            changed, gate, cost = control.request(bit, local['oldest_p'])
            costs.append(cost)
            local_trace.append({'site': SITES[i], 'action': int(bit), 'stage_before': before,
                                'target_changed': bool(changed), 'oldest_ped_wait': local['oldest_p'],
                                'cost_gate': gate, 'switch_cost': cost})
        cost = float(np.mean(costs))
        if self.gui:
            waits = ' '.join(f'{SITES[i]}:{s["oldest_p"]:.0f}s' for i, s in enumerate(self.snapshot['sites']))
            self.connection.poi.setType('status', f'{self.variant.upper()} t={self.time}s | {waits} | cost {cost:.3f}')
        stopped_seconds = 0
        for _ in range(single.DECISION):
            tick = []
            for site, control, signal, local in zip(SITES, self.controls, self.signals, self.snapshot['sites']):
                occupied = bool(local['crossing'])
                control.advance(occupied)
                state = signal[control.stage]
                self.connection.trafficlight.setRedYellowGreenState(site, state)
                tick.append({'site': site, 'stage': control.stage, 'elapsed': control.elapsed,
                             'crossing_occupied_before': occupied, 'signal': state})
            if self.gui:
                self.update_signals()
            self.tick_trace.append({'time': self.time, 'sites': tick})
            self.connection.simulationStep()
            self.time += 1
            for control in self.controls:
                control.elapsed += 1
            self.snapshot = self.read_state()
            stopped_seconds += self.snapshot['stopped_v'] + self.snapshot['pending_v'] + 2*self.snapshot['stopped_p']
        reward = -stopped_seconds / 100 - cost
        self.raw_return -= stopped_seconds / 100
        self.cost_sum += cost
        self.trace.append({'time': self.time-single.DECISION, 'action_id': int(action), 'actions': bits.tolist(),
                           'sites': local_trace, 'oldest_ped_wait': max(r['oldest_ped_wait'] for r in local_trace),
                           'switch_cost': cost, 'reward': reward})
        return self.observe(), reward, self.time >= single.HORIZON, self.mask()

    def finish(self):
        return super().finish(switches=sum(c.switches for c in self.controls),
                              extra={'crossing_count': 4, 'site_switches': {s:c.switches for s,c in zip(SITES,self.controls)}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('build')
    train = sub.add_parser('train')
    train.add_argument('--variant', choices=['basic','priority','adaptive'], required=True)
    train.add_argument('--episodes', type=int, default=30)
    train.add_argument('--seed', type=int, default=42)
    train.add_argument('--out', type=Path, required=True)
    for name in ['evaluate', 'view']:
        p = sub.add_parser(name)
        p.add_argument('--model', type=Path, default=ROOT / 'results/train-adaptive/model.pt')
        p.add_argument('--out', type=Path, required=True)
        p.add_argument('--profiles', nargs='+', choices=single.PROFILES, default=['ped-burst'] if name == 'view' else single.PROFILES)
        p.add_argument('--seeds', nargs='+', type=int, default=[1001] if name == 'view' else [1001,1002,1003])
        p.add_argument('--delay', type=int, default=80)
        p.add_argument('--capture', nargs=2, type=int)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.command == 'build':
        print(build())
    elif args.command == 'train':
        if args.episodes < 2 or args.seed < 0:
            parser.error('Use at least two episodes and a nonnegative seed')
        single.train(args, environment=Environment, obs_size=OBS_SIZE, actions=16, checkpoint_schema=schema)
    else:
        if args.delay < 0 or min(args.seeds) < 0:
            parser.error('Delay and seeds must be nonnegative')
        if args.capture and (args.command != 'view' or args.capture[0] < 1 or args.capture[1] < 2 or sum(args.capture) >= single.HORIZON):
            parser.error('Capture must fit inside the GUI simulation')
        single.evaluate(args, environment=Environment, checkpoint_schema=schema)


if __name__ == '__main__':
    main()
