from __future__ import annotations

from pathlib import Path
import random
import xml.etree.ElementTree as ET

from .common import binary, read_json, run_command, write_json


def xml_write(path, root):
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def build(config_path, output):
    cfg = read_json(config_path)
    m = cfg["intersections"]
    if m not in (1, 2, 3):
        raise ValueError("intersections must be 1, 2 or 3")
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    nodes = ET.Element("nodes")
    coords = {"W": (-300, 0), "E": ((m - 1) * 400 + 300, 0)}
    for j in range(m):
        coords.update({f"J{j}": (j * 400, 0), f"N{j}": (j * 400, 300), f"S{j}": (j * 400, -300)})
    for node, (x, y) in coords.items():
        ET.SubElement(nodes, "node", id=node, x=str(x), y=str(y), type="traffic_light" if node.startswith("J") else "priority")
    edges = ET.Element("edges")
    chain = ["W"] + [f"J{j}" for j in range(m)] + ["E"]
    pairs = list(zip(chain, chain[1:])) + [(f"N{j}", f"J{j}") for j in range(m)] + [(f"S{j}", f"J{j}") for j in range(m)]
    for a, b in pairs:
        for source, target in [(a, b), (b, a)]:
            ET.SubElement(edges, "edge", id=f"{source}_{target}", **{"from": source, "to": target}, numLanes="1", speed="13.89", priority="2")
    connections = ET.Element("connections")
    tls = ET.Element("tlLogics")
    signals = []
    for j in range(m):
        node = f"J{j}"
        neighbors = [f"N{j}", f"S{j}", chain[j], chain[j + 2]]
        opposite = [1, 0, 3, 2]
        for idx, source in enumerate(neighbors):
            ET.SubElement(connections, "connection", **{"from": f"{source}_{node}", "to": f"{node}_{neighbors[opposite[idx]]}"}, fromLane="0", toLane="0", tl=node, linkIndex=str(idx))
        signal = {"id": node, "lanes": [f"{n}_{node}_0" for n in neighbors], "greens": ["GGrr", "rrGG"], "yellows": ["yyrr", "rryy"], "all_red_state": "rrrr", **{k: cfg[k] for k in ["min_green", "max_green", "yellow", "all_red", "fixed_green"]}}
        signals.append(signal)
        logic = ET.SubElement(tls, "tlLogic", id=node, type="static", programID="fixed", offset="0")
        for g in range(2):
            for state, duration in [(signal["greens"][g], cfg["fixed_green"]), (signal["yellows"][g], cfg["yellow"]), ("rrrr", cfg["all_red"])]:
                ET.SubElement(logic, "phase", duration=str(duration), state=state)
    for name, root in [("network.nod.xml", nodes), ("network.edg.xml", edges), ("network.con.xml", connections), ("network.tll.xml", tls)]:
        xml_write(out / name, root)
    run_command([binary("netconvert"), "--node-files", str(out / "network.nod.xml"), "--edge-files", str(out / "network.edg.xml"), "--connection-files", str(out / "network.con.xml"), "--tllogic-files", str(out / "network.tll.xml"), "--output-file", str(out / "network.net.xml"), "--no-turnarounds", "true"])
    # netconvert may reorder TLS indices (clockwise), even when linkIndex was
    # supplied. Derive every state from the FINAL connections, never input order.
    net_root = ET.parse(out / "network.net.xml").getroot()
    for signal in signals:
        actual = [c for c in net_root.findall("connection") if c.get("tl") == signal["id"]]
        size = max(int(c.get("linkIndex")) for c in actual) + 1
        greens = []
        for served_lanes in [signal["lanes"][:2], signal["lanes"][2:]]:
            chars = ["r"] * size
            for c in actual:
                if f"{c.get('from')}_{c.get('fromLane')}" in served_lanes:
                    chars[int(c.get("linkIndex"))] = "G"
            greens.append("".join(chars))
        signal["greens"] = greens
        signal["yellows"] = [g.replace("G", "y") for g in greens]
        signal["all_red_state"] = "r" * size
        states = []
        for g, y in zip(greens, signal["yellows"]):
            states += [g, y, signal["all_red_state"]]
        for logic in list(net_root.findall("tlLogic")) + list(tls.findall("tlLogic")):
            if logic.get("id") == signal["id"]:
                for phase, state in zip(logic.findall("phase"), states):
                    phase.set("state", state)
    xml_write(out / "network.net.xml", net_root)
    xml_write(out / "network.tll.xml", tls)
    paths = [{"id": "east", "edges": [f"{a}_{b}" for a, b in zip(chain, chain[1:])], "rate": cfg["ew_rate"]}, {"id": "west", "edges": [f"{a}_{b}" for a, b in zip(chain[::-1], chain[-2::-1])], "rate": cfg["ew_rate"]}]
    for j in range(m):
        for a, b in [("N", "S"), ("S", "N")]:
            paths.append({"id": f"{a}{j}", "edges": [f"{a}{j}_J{j}", f"J{j}_{b}{j}"], "rate": cfg["ns_rate"]})
    manifest = {"name": cfg["name"], "synthetic": True, "net_file": "network.net.xml", "signals": signals, "paths": paths, **{k: cfg[k] for k in ["demand_seconds", "horizon_seconds", "decision_seconds"]}}
    write_json(out / "manifest.json", manifest)
    routes = generate_demand(out, manifest, 1001)
    sumocfg = ET.Element("configuration")
    inputs = ET.SubElement(sumocfg, "input")
    ET.SubElement(inputs, "net-file", value="network.net.xml")
    ET.SubElement(inputs, "route-files", value=str(routes.relative_to(out)).replace("\\", "/"))
    time = ET.SubElement(sumocfg, "time")
    ET.SubElement(time, "end", value=str(manifest["horizon_seconds"]))
    xml_write(out / "view.sumocfg", sumocfg)
    return manifest


def generate_demand(directory, manifest, seed, scale=1.0):
    """Explicit departures are fixed before any controller runs. No stochastic flows."""
    directory = Path(directory)
    if not manifest.get("synthetic", False):
        if scale != 1.0:
            raise ValueError("Real scenarios require a separately calibrated route file for each demand level; --scale only supports synthetic demand.")
        return (directory / manifest["route_file"]).resolve()
    if scale <= 0:
        raise ValueError("demand scale must be positive")
    path = directory / "demand" / f"seed_{seed}_scale_{scale:g}.rou.xml"
    path.parent.mkdir(exist_ok=True)
    rng = random.Random(seed)
    root = ET.Element("routes")
    ET.SubElement(root, "vType", id="car", accel="2.6", decel="4.5", sigma="0.5", length="5", minGap="2.5", maxSpeed="13.89", speedFactor="1.0", speedDev="0")
    vehicles = []
    for route in manifest["paths"]:
        ET.SubElement(root, "route", id=route["id"], edges=" ".join(route["edges"]))
        rate = route["rate"] * scale
        if rate <= 0:
            continue
        t = rng.expovariate(rate / 3600)
        n = 0
        while t < manifest["demand_seconds"]:
            vehicles.append((round(t, 3), f"{route['id']}_{n}", route["id"]))
            t += rng.expovariate(rate / 3600)
            n += 1
    for depart, vid, route in sorted(vehicles):
        ET.SubElement(root, "vehicle", id=vid, type="car", route=route, depart=f"{depart:.3f}", departLane="best", departSpeed="max")
    xml_write(path, root)
    return path.resolve()
