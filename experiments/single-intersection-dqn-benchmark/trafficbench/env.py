from __future__ import annotations
import bisect
import csv
import math
import os
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

import gymnasium as gym
import numpy as np
import traci
import traci.constants as tc

from .common import ROOT, digest, write_json
from .rewards import reward_value
from .scenario import DIRS, binary, build_network, prepare_demand, write_xml


class TrafficEnv(gym.Env):
    """One decision per green second; yellow is an uninterruptible three-second transition.

    step() can span 1 or 4 simulation seconds. Rewards and bootstraps use the same
    per-second discount (SMDP). Metrics always cover the entire common horizon.
    """
    metadata = {'render_modes': ['human']}

    def __init__(self, cfg, level='medium', reward='wtmin', demand_seed=1001,
                 split='eval', out=None, gui=False, delay=70):
        super().__init__()
        self.cfg, self.s = cfg, cfg['scenario']
        self.level, self.reward_name, self.demand_seed = level, reward, demand_seed
        self.split, self.gui, self.delay = split, gui, delay
        self.out = Path(out) if out else Path('results/episode-' + uuid.uuid4().hex[:8])
        self.out.mkdir(parents=True, exist_ok=True)
        self.action_space = gym.spaces.Discrete(2)
        self.observation_space = gym.spaces.Box(0, 10, shape=(13,), dtype=np.float32)
        self.conn = None
        self.label = 'bench-' + uuid.uuid4().hex
        self.horizon = self.s['demand_seconds'] + self.s['drain_seconds']
        self.streams = []
        self.visualizer = None

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.close()
        network = build_network(self.cfg)
        self.network_structure_sha256 = digest(ET.tostring(ET.parse(network).getroot(),encoding='unicode'))
        route, self.demand = prepare_demand(self.cfg, self.level, self.demand_seed, self.split)
        # SUMO inserts at the first integer tick >= requested departure, reporting it
        # after that tick. Quantization itself is not a congestion-induced pending second.
        self.expected_times = sorted(math.ceil(v['depart']) for v in self.demand['vehicles'].values())
        additional = ET.Element('additional')
        for d in DIRS:
            ET.SubElement(additional, 'laneAreaDetector', id='det_'+d, lane=d+'_in_0',
                          pos=str(-self.s['detector_length_m']), length=str(self.s['detector_length_m']),
                          freq=str(self.horizon+1), file=str((self.out/'detector-output.xml').resolve()))
        write_xml(self.out/'detectors.add.xml', additional)
        self.phase, self.green_age, self.clock = 0, 0, 0
        self.total_departed = self.total_arrived = self.switches = self.teleports = self.collisions = 0
        self.stopped_seconds = self.pending_seconds = self.vehicle_seconds = self.co2_mg = 0.0
        self.max_queue = self.maximum_wait = 0.0
        self.wait_by_vehicle, self.dir_stopped = {}, dict.fromkeys(DIRS, 0.0)
        self.reward_sum, self.discounted_reward_sum, self.decisions = 0.0, 0.0, 0
        self.log = (self.out/'sumo.log').open('w', encoding='utf-8')
        cmd = [binary('sumo-gui' if self.gui else 'sumo'), '--net-file', str(network.resolve()),
               '--route-files', str(route.resolve()), '--additional-files', str((self.out/'detectors.add.xml').resolve()),
               '--seed', str(self.demand_seed), '--step-length', '1', '--end', str(self.horizon+10),
               '--time-to-teleport', '-1', '--max-depart-delay', '-1', '--collision.action', 'warn',
               '--no-step-log', 'true', '--duration-log.disable', 'true',
               '--tripinfo-output', str((self.out/'tripinfo.xml').resolve()), '--tripinfo-output.write-unfinished', 'true']
        if self.gui:
            cmd += ['--start', '--quit-on-end', '--delay', str(self.delay), '--window-size', '1200,850',
                    '--gui-settings-file', str(ROOT/'configs/gui.xml')]
        try:
            traci.start(cmd, label=self.label, numRetries=3, stdout=self.log, doSwitch=False)
            self.conn = traci.getConnection(self.label)
            self.sumo_version = self.conn.getVersion()[1]
            links = self.conn.trafficlight.getControlledLinks('J')
            self.greens = []
            for phase in (0, 1):
                self.greens.append(''.join('G' if group[0][0][0] in ('NS' if phase == 0 else 'EW') else 'r' for group in links))
            self.conn.trafficlight.setRedYellowGreenState('J', self.greens[0])
            self.sec_file = (self.out/'seconds.csv').open('w', newline='', encoding='utf-8')
            self.dec_file = (self.out/'decisions.csv').open('w', newline='', encoding='utf-8')
            self.streams = [self.sec_file, self.dec_file]
            self.sec_log = csv.DictWriter(self.sec_file, fieldnames=['second','phase','yellow','active','stopped','pending','arrived','co2_mg','reward'])
            self.dec_log = csv.DictWriter(self.dec_file, fieldnames=['second','phase_before','action','phase_after','elapsed','raw_reward','learning_reward'])
            self.sec_log.writeheader()
            self.dec_log.writeheader()
            if self.gui:
                view = self.conn.gui.getIDList()[0]
                self.conn.gui.setSchema(view, 'benchmark')
                self.conn.gui.setOffset(view, *self.conn.junction.getPosition('J'))
                self.conn.gui.setZoom(view, 620)
                from .appearance import CityAppearance
                self.visualizer = CityAppearance(self.conn,self.out,self.level)
                self.visualizer.build()
            return self.observe(), {'scheduled': self.demand['scheduled'], 'route_sha256': self.demand['sha256']}
        except Exception:
            self.close()
            raise

    def observe(self):
        features = []
        for d in DIRS:
            det = 'det_'+d
            n = self.conn.lanearea.getLastStepVehicleNumber(det)
            occ = self.conn.lanearea.getLastStepOccupancy(det)
            speed = max(0.0, self.conn.lanearea.getLastStepMeanSpeed(det))
            features.extend([min(10, n), np.clip(occ/10, 0, 10), np.clip(speed/self.s['speed_limit_mps']*10, 0, 10)])
        return np.asarray(features+[self.phase], dtype=np.float32)

    def _tick(self, yellow=False):
        self.conn.simulationStep()
        self.clock += 1
        if self.gui and self.clock == 180 and os.environ.get('TRAFFICBENCH_NATIVE_SCREENSHOT') == '1':
            self.conn.gui.screenshot(self.conn.gui.getIDList()[0], str((self.out/'simulation.png').resolve()))
        departed = self.conn.simulation.getDepartedIDList()
        arrived = self.conn.simulation.getArrivedIDList()
        self.total_departed += len(departed)
        self.total_arrived += len(arrived)
        for vid in departed:
            self.wait_by_vehicle[vid] = 0.0
            self.conn.vehicle.subscribe(vid, (tc.VAR_SPEED, tc.VAR_CO2EMISSION))
        snapshots = self.conn.vehicle.getAllSubscriptionResults()
        speeds, stopped, emission = [], 0, 0.0
        for vid in self.conn.vehicle.getIDList():
            data = snapshots.get(vid)
            if not data:
                speed, co2 = self.conn.vehicle.getSpeed(vid), self.conn.vehicle.getCO2Emission(vid)
            else:
                speed, co2 = data[tc.VAR_SPEED], data[tc.VAR_CO2EMISSION]
            speeds.append(speed)
            emission += co2
            if speed < 0.1:
                stopped += 1
                self.wait_by_vehicle[vid] = self.wait_by_vehicle.get(vid, 0)+1
                self.dir_stopped[vid[0]] += 1
                self.maximum_wait = max(self.maximum_wait, self.wait_by_vehicle[vid])
        active = len(speeds)
        # Include vehicles due but blocked outside the network, not future departures.
        pending = max(0, bisect.bisect_left(self.expected_times, self.clock) - self.total_departed)
        weighted = sum(self.demand['vehicles'][vid]['route_length_m']/self.s['route_weight_reference_m'] for vid in arrived)
        r = reward_value(self.reward_name, stopped=stopped, active=active,
                         mean_speed=float(np.mean(speeds)) if speeds else 0,
                         speed_limit=self.s['speed_limit_mps'], arrived=len(arrived),
                         weighted_arrived=weighted, departed=len(departed))
        self.stopped_seconds += stopped
        self.pending_seconds += pending
        self.vehicle_seconds += active
        self.co2_mg += emission
        self.max_queue = max(self.max_queue, stopped)
        self.teleports += self.conn.simulation.getStartingTeleportNumber()
        self.collisions += self.conn.simulation.getCollidingVehiclesNumber()
        self.sec_log.writerow(dict(second=self.clock, phase=self.phase, yellow=int(yellow), active=active,
                                   stopped=stopped, pending=pending, arrived=len(arrived), co2_mg=emission, reward=r))
        if self.visualizer:
            self.visualizer.update()
        return r

    def step(self, action):
        if not self.action_space.contains(action):
            raise ValueError('Action must be 0 (hold) or 1 (switch).')
        if self.clock >= self.horizon:
            raise RuntimeError('Episode ended. Call reset().')
        before = self.phase
        elapsed, raw, learning = 0, 0.0, 0.0
        gamma = self.cfg['learning']['gamma_per_second']

        def advance(yellow):
            nonlocal elapsed, raw, learning
            r = self._tick(yellow)
            raw += r
            learning += gamma**elapsed * r
            elapsed += 1

        if action == 1:
            self.switches += 1
            yellow_state = ''.join('y' if x == 'G' else 'r' for x in self.greens[self.phase])
            self.conn.trafficlight.setRedYellowGreenState('J', yellow_state)
            for _ in range(min(self.s['yellow_s'], self.horizon-self.clock)):
                advance(True)
            if self.clock < self.horizon:
                self.phase = 1-self.phase
                self.green_age = 0
                self.conn.trafficlight.setRedYellowGreenState('J', self.greens[self.phase])
        if self.clock < self.horizon:
            advance(False)
            self.green_age += 1
        self.decisions += 1
        self.reward_sum += raw
        self.discounted_reward_sum += learning
        self.dec_log.writerow(dict(second=self.clock, phase_before=before, action=int(action), phase_after=self.phase,
                                   elapsed=elapsed, raw_reward=raw, learning_reward=learning))
        end = self.clock >= self.horizon
        # Finite evaluation episode: deliberately stop bootstrapping at its end, including residual vehicles.
        return self.observe(), learning, end, False, {'elapsed': elapsed, 'discount': gamma**elapsed, 'raw_reward': raw}

    def metrics(self):
        active = self.conn.vehicle.getIDCount()
        n = self.demand['scheduled']
        pending = n-self.total_departed
        seconds = max(1, self.clock)
        return {'level': self.level, 'requested_vph': self.s['loads_vph'][self.level],
                'realized_vph': self.demand['realized_vph'], 'demand_seed': self.demand_seed,
                'reward': self.reward_name, 'route_sha256': self.demand['sha256'], 'sumo_version': self.sumo_version,
                'network_structure_sha256': self.network_structure_sha256,
                'simulation_seconds': self.clock, 'scheduled': n, 'departed': self.total_departed,
                'arrived': self.total_arrived, 'remaining': active, 'not_departed': pending,
                'completion_rate': self.total_arrived/max(1,n),
                'observed_stopped_vehicle_seconds': self.stopped_seconds,
                'pending_vehicle_seconds': self.pending_seconds,
                'observed_wait_s_per_scheduled': self.stopped_seconds/max(1,n),
                'penalized_wait_s_per_scheduled': (self.stopped_seconds+self.pending_seconds)/max(1,n),
                'mean_queue_vehicles': self.stopped_seconds/seconds, 'max_queue_vehicles': self.max_queue,
                'max_observed_vehicle_wait_s': self.maximum_wait,
                'in_network_vehicle_seconds': self.vehicle_seconds, 'co2_g': self.co2_mg/1000,
                'signal_switches': self.switches, 'teleports': self.teleports, 'collisions': self.collisions,
                'raw_return': self.reward_sum, 'decisions': self.decisions,
                'direction_stopped_vehicle_seconds': self.dir_stopped}

    def close(self):
        visualizer=self.visualizer
        self.visualizer = None
        if self.conn is not None:
            try:
                self.conn.close()
            finally:
                self.conn = None
        for f in self.streams:
            f.close()
        self.streams = []
        if getattr(self, 'log', None) is not None:
            self.log.close()
            self.log = None
        if visualizer:
            visualizer.finish_preview()
