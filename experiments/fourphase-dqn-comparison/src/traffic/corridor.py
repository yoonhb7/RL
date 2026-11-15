"""Synthetic two-junction inputs, demand cases and frozen experiment manifests."""

import json
import math
import random
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from src.traffic.experiments import ROOT, sha256, validate_splits, write_json


SIGNALS = ("A", "B")
DIRECTIONS = ("north", "south", "east", "west")
INCOMING = {
    "A": ("A_north_in", "A_south_in", "B_to_A", "west_in"),
    "B": ("B_north_in", "B_south_in", "east_in", "A_to_B"),
}
ROUTES = {"west": ("west_in", "A_to_B", "east_out"), "east": ("east_in", "B_to_A", "west_out"),
          **{f"{j}_{d}": (f"{j}_{d}_in", f"{j}_{'south' if d == 'north' else 'north'}_out")
             for j in SIGNALS for d in ("north", "south")}}


def write_xml(path, root):
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def read_settings(path=None):
    settings = json.loads(Path(path or ROOT / "configs/corridor2.json").read_text(encoding="utf-8"))
    for key in ("duration_seconds", "warmup_seconds", "demand_end_seconds", "decision_interval_seconds",
                "min_green_seconds", "max_green_seconds", "fixed_green_seconds", "seed"):
        if isinstance(settings[key], bool) or not isinstance(settings[key], int) or settings[key] < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
    for key in ("junction_spacing_m", "boundary_length_m", "speed_m_s", "vehicle_space_meters"):
        if not math.isfinite(settings[key]) or settings[key] <= 0:
            raise ValueError(f"{key} must be positive and finite")
    if not 0 <= settings["warmup_seconds"] < settings["demand_end_seconds"] < settings["duration_seconds"]:
        raise ValueError("Expected warmup < demand end < horizon")
    if not 0 < settings["min_green_seconds"] <= settings["fixed_green_seconds"] <= settings["max_green_seconds"]:
        raise ValueError("Expected min <= fixed <= max green")
    if settings["step_length_seconds"] != 1 or settings["decision_interval_seconds"] <= 0:
        raise ValueError("Use 1-second simulation steps and a positive decision interval")
    cycle = 2 * (settings["fixed_green_seconds"] + 4)
    if not 0 <= settings["fixed_offset_B_seconds"] < cycle or settings["queue_hysteresis_vehicles"] < 0:
        raise ValueError("Expected 0 <= offset < cycle and nonnegative queue hysteresis")
    if not settings["profiles"] or any(not re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in settings["profiles"]):
        raise ValueError("Use nonempty profiles with simple lowercase names")
    for segments in settings["profiles"].values():
        cursor = 0
        for segment in segments:
            if segment["begin"] != cursor or not segment["begin"] < segment["end"]:
                raise ValueError("Profile segments must form one continuous departure schedule")
            if set(segment["rates"]) != set(ROUTES) or any(not math.isfinite(r) or r < 0 for r in segment["rates"].values()):
                raise ValueError("Every route requires a nonnegative finite rate")
            cursor = segment["end"]
        if cursor != settings["demand_end_seconds"]:
            raise ValueError("Profile must end at demand_end_seconds")
    return settings


def decode_action(action):
    if isinstance(action, bool) or not isinstance(action, int) or not 0 <= action < 4:
        raise ValueError("Joint action must be an integer 0–3")
    return action & 1, (action >> 1) & 1


def queue_action(observation, info):
    bits = []
    for signal_id in SIGNALS:
        item = info["raw_observation"]["junctions"][signal_id]
        phase, queues = item["phase_index"], item["queues"]
        ns, ew = queues["north"] + queues["south"], queues["east"] + queues["west"]
        current, other = (ns, ew) if phase == 0 else (ew, ns)
        bits.append(int(phase in (0, 3) and other > current + info["queue_hysteresis_vehicles"]))
    return bits[0] + 2 * bits[1]


def write_network_inputs(folder, settings):
    length, gap = settings["boundary_length_m"], settings["junction_spacing_m"]
    nodes = ET.Element("nodes")
    points = {"A": (length, length), "B": (length + gap, length), "west": (0, length),
              "east": (2 * length + gap, length),
              **{f"{j}_{d}": (length + (gap if j == "B" else 0), 2 * length if d == "north" else 0)
                 for j in SIGNALS for d in ("north", "south")}}
    for name, (x, y) in points.items():
        ET.SubElement(nodes, "node", id=name, x=str(x), y=str(y), type="traffic_light" if name in SIGNALS else "priority")
    edges = ET.Element("edges")
    definitions = {"west_in": ("west", "A"), "west_out": ("A", "west"), "east_in": ("east", "B"),
                   "east_out": ("B", "east"), "A_to_B": ("A", "B"), "B_to_A": ("B", "A")}
    for j in SIGNALS:
        for d in ("north", "south"):
            definitions[f"{j}_{d}_in"] = f"{j}_{d}", j
            definitions[f"{j}_{d}_out"] = j, f"{j}_{d}"
    for edge_id, (origin, destination) in definitions.items():
        ET.SubElement(edges, "edge", id=edge_id, attrib={"from": origin, "to": destination},
                      numLanes="1", speed=str(settings["speed_m_s"]))
    connections, programs = ET.Element("connections"), ET.Element("tlLogics")
    for j in SIGNALS:
        outgoing = (f"{j}_south_out", f"{j}_north_out", "west_out" if j == "A" else "B_to_A",
                    "A_to_B" if j == "A" else "east_out")
        plan = ET.SubElement(programs, "tlLogic", id=j, type="static", programID="fixed",
                             offset=str(settings["fixed_offset_B_seconds"] if j == "B" else 0))
        for duration, state in ((settings["fixed_green_seconds"], "GGrr"), (3, "yyrr"), (1, "rrrr"),
                                (settings["fixed_green_seconds"], "rrGG"), (3, "rryy"), (1, "rrrr")):
            ET.SubElement(plan, "phase", duration=str(duration), state=state)
        for index, (incoming, target) in enumerate(zip(INCOMING[j], outgoing)):
            attributes = {"from": incoming, "to": target, "fromLane": "0", "toLane": "0"}
            ET.SubElement(connections, "connection", attributes)
            ET.SubElement(programs, "connection", {**attributes, "tl": j, "linkIndex": str(index)})
    for name, root in (("corridor2.nod.xml", nodes), ("corridor2.edg.xml", edges),
                       ("corridor2.con.xml", connections), ("corridor2.tll.xml", programs)):
        write_xml(folder / name, root)


def write_demand(folder, settings, profile, seed):
    rng, root, vehicles = random.Random(seed), ET.Element("routes"), []
    ET.SubElement(root, "vType", id="car", vClass="passenger", guiShape="passenger/sedan", accel="2.6", decel="4.5",
                  sigma="0.5", length="5", minGap="2.5", maxSpeed=str(settings["speed_m_s"]))
    for origin, edges in ROUTES.items():
        ET.SubElement(root, "route", id=origin, edges=" ".join(edges))
        index = 0
        for segment in settings["profiles"][profile]:
            rate = segment["rates"][origin]
            if not rate:
                continue
            departure = segment["begin"] + rng.expovariate(rate / 3600)
            while departure < segment["end"]:
                rounded = math.floor(departure * 1000) / 1000
                vehicles.append((rounded, f"{origin}_{index:05d}", origin))
                index += 1
                departure += rng.expovariate(rate / 3600)
    for departure, vehicle_id, origin in sorted(vehicles):
        ET.SubElement(root, "vehicle", id=vehicle_id, type="car", route=origin, depart=f"{departure:.3f}",
                      departLane="0", departSpeed="max")
    write_xml(folder / "corridor2.rou.xml", root)
    metadata = {"seed": seed, "profile": profile, "vehicle_count": len(vehicles),
                "vehicles_by_origin": dict(Counter(v[2] for v in vehicles)), "segments": settings["profiles"][profile]}
    write_json(folder / "demand.json", metadata)
    return metadata


def write_configuration(folder, settings, *, gui=False):
    root, input_name = ET.Element("configuration"), "corridor2.gui.sumocfg" if gui else "corridor2.sumocfg"
    inputs = ET.SubElement(root, "input")
    ET.SubElement(inputs, "net-file", value="corridor2.net.xml")
    ET.SubElement(inputs, "route-files", value="corridor2.rou.xml")
    timing = ET.SubElement(root, "time")
    for name, value in (("begin", 0), ("end", settings["duration_seconds"]), ("step-length", 1)):
        ET.SubElement(timing, name, value=str(value))
    processing = ET.SubElement(root, "processing")
    ET.SubElement(processing, "time-to-teleport", value="-1")
    ET.SubElement(processing, "collision.check-junctions", value="true")
    ET.SubElement(ET.SubElement(root, "random_number"), "seed", value=str(settings["seed"]))
    if gui:
        ET.SubElement(ET.SubElement(root, "gui_only"), "gui-settings-file", value="corridor2.view.xml")
    write_xml(folder / input_name, root)


def make_case(folder, settings, profile, seed, source):
    folder.mkdir(parents=True, exist_ok=False)
    for filename in ("corridor2.net.xml", "corridor2.view.xml"):
        shutil.copy2(source / filename, folder / filename)
    case_settings = {**settings, "seed": seed}
    write_configuration(folder, case_settings)
    write_configuration(folder, case_settings, gui=True)
    return write_demand(folder, settings, profile, seed)


def prepare_cases(folder, source, settings, profiles, seeds):
    cases = []
    for profile in profiles:
        if profile not in settings["profiles"]:
            raise ValueError(f"Unknown traffic profile: {profile}")
        for seed in seeds:
            case_folder = folder / profile / f"seed_{seed}"
            metadata = make_case(case_folder, settings, profile, seed, source)
            cases.append({"profile": profile, "demand_seed": seed, "sumo_seed": seed, "vehicle_count": metadata["vehicle_count"],
                          "config": case_folder / "corridor2.sumocfg", "routes": case_folder / "corridor2.rou.xml",
                          "sha256": {name: sha256(case_folder / name) for name in
                                     ("corridor2.net.xml", "corridor2.sumocfg", "corridor2.rou.xml", "demand.json")}})
    return cases


def relative_cases(cases, folder):
    return [{**case, "config": str(case["config"].relative_to(folder)), "routes": str(case["routes"].relative_to(folder))}
            for case in cases]


def prepare_run(folder, source, config, profiles):
    validate_splits(config)
    settings = read_scenario(source)
    folder.mkdir(parents=True, exist_ok=False)
    manifest = {"kind": "synthetic_corridor2", "schema_version": 1, "algorithm": "vanilla DQN",
                "source_manifest_sha256": sha256(source / "manifest.json"), "observation_size": 31, "action_count": 4,
                "training_config": config, "env_settings": settings, "profiles": profiles, "cases": {}}
    for split in ("train", "validation", "test"):
        cases = prepare_cases(folder / "scenarios" / split, source, settings, profiles, config[f"{split}_demand_seeds"])
        manifest["cases"][split] = relative_cases(cases, folder)
    write_json(folder / "manifest.json", manifest)
    return manifest


def read_scenario(source):
    if not (source / "manifest.json").is_file():
        raise FileNotFoundError("먼저 .venv/bin/python scripts/build_corridor2.py를 실행하세요")
    source_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if source_manifest.get("kind") != "synthetic_corridor2":
        raise ValueError("Expected the main synthetic corridor2 scenario")
    for name, value in source_manifest["sha256"].items():
        if sha256(source / name) != value:
            raise ValueError(f"Scenario input changed: {name}")
    return source_manifest["settings"]
