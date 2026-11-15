from __future__ import annotations
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import xml.etree.ElementTree as ET
from .common import ROOT, digest, file_hash, write_json

DIRS = ('N', 'E', 'S', 'W')
STRAIGHT = {'N': 'S', 'E': 'W', 'S': 'N', 'W': 'E'}
RIGHT = {'N': 'W', 'E': 'N', 'S': 'E', 'W': 'S'}


def binary(name):
    suffix = '.exe' if os.name == 'nt' else ''
    candidates = []
    if os.environ.get('SUMO_HOME'):
        candidates.append(Path(os.environ['SUMO_HOME']) / 'bin' / (name + suffix))
    resolved = shutil.which(name)
    if resolved:
        candidates.append(Path(resolved))
    try:
        import sumo
        candidates.append(Path(sumo.__file__).parent / 'bin' / (name + suffix))
    except ImportError:
        pass
    for p in candidates:
        if p.is_file():
            return str(p)
    raise FileNotFoundError(f'{name} not found. Install eclipse-sumo or configure SUMO_HOME/PATH.')


def write_xml(path, root):
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def build_network(cfg, out=None):
    s = cfg['scenario']
    out = Path(out) if out else ROOT / 'data' / ('network-' + digest(s['arm_lengths_m'])[:10])
    out.mkdir(parents=True, exist_ok=True)
    signature = digest({'arms': s['arm_lengths_m'], 'speed': s['speed_limit_mps']})
    marker = out / 'network_manifest.json'
    if marker.exists():
        m = json.loads(marker.read_text())
        if m['signature'] == signature and file_hash(out / 'network.net.xml') == m['sha256']:
            return out / 'network.net.xml'
    nodes, edges, cons = ET.Element('nodes'), ET.Element('edges'), ET.Element('connections')
    ET.SubElement(nodes, 'node', id='J', x='0', y='0', type='traffic_light')
    for d in DIRS:
        length = s['arm_lengths_m'][d]
        x, y = {'N': (0, length), 'E': (length, 0), 'S': (0, -length), 'W': (-length, 0)}[d]
        ET.SubElement(nodes, 'node', id=d, x=str(x), y=str(y), type='priority')
        ET.SubElement(edges, 'edge', id=d+'_in', **{'from': d, 'to': 'J', 'numLanes': '1', 'speed': str(s['speed_limit_mps'])})
        ET.SubElement(edges, 'edge', id=d+'_out', **{'from': 'J', 'to': d, 'numLanes': '1', 'speed': str(s['speed_limit_mps'])})
        for dest in (STRAIGHT[d], RIGHT[d]):
            ET.SubElement(cons, 'connection', **{'from': d+'_in', 'to': dest+'_out', 'fromLane': '0', 'toLane': '0'})
    for name, element in [('nodes.nod.xml', nodes), ('edges.edg.xml', edges), ('connections.con.xml', cons)]:
        write_xml(out/name, element)
    cmd = [binary('netconvert'), '--node-files', str(out/'nodes.nod.xml'), '--edge-files', str(out/'edges.edg.xml'),
           '--connection-files', str(out/'connections.con.xml'), '--output-file', str(out/'network.net.xml'),
           '--no-turnarounds', 'true', '--junctions.corner-detail', '5']
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr)
    write_json(marker, {'signature': signature, 'sha256': file_hash(out/'network.net.xml'), 'command': cmd})
    return out / 'network.net.xml'


def prepare_demand(cfg, level, seed, split='eval', directory=None):
    """Pre-generate explicit vehicles, independent of policy and SUMO insertion delays."""
    s = cfg['scenario']
    key = digest({'scenario': s, 'level': level, 'seed': seed, 'split': split})
    folder = Path(directory) if directory else ROOT / 'data' / 'routes' / key[:20]
    folder.mkdir(parents=True, exist_ok=True)
    routefile, metafile = folder/'demand.rou.xml', folder/'demand.json'
    if metafile.exists():
        meta = json.loads(metafile.read_text())
        if meta.get('key') == key and routefile.exists() and meta.get('sha256') == file_hash(routefile):
            return routefile, meta
    rng = random.Random(seed)
    rows = []
    for t in range(s['demand_seconds']):
        for d in DIRS:
            if rng.random() < s['loads_vph'][level] * s['direction_shares'][d] / 3600:
                dest = RIGHT[d] if rng.random() < s['right_turn_ratio'] else STRAIGHT[d]
                rows.append((t + rng.random(), d, dest))
    rows.sort()
    root = ET.Element('routes')
    ET.SubElement(root, 'vType', id='car', accel='2.6', decel='4.5', sigma='0.5', length='5',
                  minGap='2.5', maxSpeed=str(s['speed_limit_mps']), tau='1')
    for d in DIRS:
        for dest in (STRAIGHT[d], RIGHT[d]):
            ET.SubElement(root, 'route', id=f'{d}_{dest}', edges=f'{d}_in {dest}_out')
    meta_vehicles = {}
    for i, (t, d, dest) in enumerate(rows):
        vid = f'{d}_{i:06d}'
        ET.SubElement(root, 'vehicle', id=vid, type='car', route=f'{d}_{dest}', depart=f'{t:.3f}',
                      departLane='0', departSpeed='max', color={'N':'1,0.3,0.3','E':'0.2,0.6,1','S':'1,0.7,0','W':'0.2,0.8,0.4'}[d])
        # Single-path straight/right routes are shortest allowed routes here. Internal junction length excluded.
        meta_vehicles[vid] = {'depart': round(t, 3), 'origin': d, 'destination': dest,
                              'route_length_m': s['arm_lengths_m'][d]+s['arm_lengths_m'][dest]}
    write_xml(routefile, root)
    meta = {'key': key, 'level': level, 'seed': seed, 'split': split, 'requested_vph': s['loads_vph'][level],
            'scheduled': len(rows), 'realized_vph': len(rows)*3600/s['demand_seconds'],
            'vehicles': meta_vehicles, 'sha256': file_hash(routefile)}
    write_json(metafile, meta)
    return routefile, meta
