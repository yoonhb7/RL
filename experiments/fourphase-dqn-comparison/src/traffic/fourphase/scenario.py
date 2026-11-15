"""Frozen road, signal and Poisson departure inputs; no simulation on import."""

import json
import math
import random
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from src.traffic.experiments import ROOT, sha256, write_json


TLS = "center4"
DIRECTIONS = ("north", "south", "east", "west")
TURNS = ("straight", "left")
DESTINATIONS = {
    "north": ("south", "east"), "south": ("north", "west"),
    "east": ("west", "south"), "west": ("east", "north"),
}
# Signal index, state vector and lane order are deliberately identical.
MOVEMENTS = tuple((direction, turn) for direction in DIRECTIONS for turn in TURNS)
LANES = tuple(f"{direction}_in_{TURNS.index(turn)}" for direction, turn in MOVEMENTS)
GREEN_STATES = ("GrGrrrrr", "rGrGrrrr", "rrrrGrGr", "rrrrrGrG")
STATES = tuple(state for green in GREEN_STATES for state in (green, green.replace("G", "y"), "rrrrrrrr"))


def read_settings(path=None):
    settings = json.loads(Path(path or ROOT / "configs/fourphase.json").read_text(encoding="utf-8"))
    validate_settings(settings)
    return settings


def validate_settings(settings):
    locked = {"step_length_seconds": 1, "decision_interval_seconds": 15, "yellow_seconds": 3,
              "all_red_seconds": 1, "min_green_seconds": 11, "max_green_seconds": 60}
    for name, expected in locked.items():
        if type(settings[name]) is not int or settings[name] != expected:
            raise ValueError(f"This protocol requires {name}={expected}")
    horizon = settings["duration_seconds"]
    if type(horizon) is not int or horizon <= 0 or horizon % 15:
        raise ValueError("The external time limit must be a positive multiple of 15 seconds")
    if type(settings["pilot_seed"]) is not int or not 0 <= settings["pilot_seed"] < 2**31:
        raise ValueError("pilot_seed must be an integer in [0, 2**31)")
    if type(settings["demand_extension_seconds"]) is not int or settings["demand_extension_seconds"] < 15:
        raise ValueError("Generate at least one decision interval of demand beyond the observation window")
    for name in ("arm_length_m", "speed_m_s", "vehicle_length_m", "vehicle_min_gap_m"):
        if isinstance(settings[name], bool) or not math.isfinite(settings[name]) or settings[name] <= 0:
            raise ValueError(f"{name} must be positive and finite")
    greens = settings["fixed_green_seconds"]
    if len(greens) != 4 or any(type(g) is not int or not 11 <= g <= 60 for g in greens):
        raise ValueError("Fixed-time needs four integer green durations between 11 and 60 seconds")
    if not 0 < settings["left_turn_probability"] < 1:
        raise ValueError("left_turn_probability must be in (0, 1)")
    rates = settings["demand_rates_veh_h"]
    if set(rates) != {"low", "medium", "high"} or any(
        isinstance(rate, bool) or not math.isfinite(rate) or rate <= 0 for rate in rates.values()
    ) or not rates["low"] < rates["medium"] < rates["high"]:
        raise ValueError("Specify increasing, positive low/medium/high rates")


def write_xml(path, root):
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def connection_attributes(index):
    direction, turn = MOVEMENTS[index]
    lane = TURNS.index(turn)
    return {"from": f"{direction}_in", "to": f"{DESTINATIONS[direction][lane]}_out",
            "fromLane": str(lane), "toLane": str(lane)}


def write_network_inputs(folder, settings):
    length = settings["arm_length_m"]
    nodes, edges = ET.Element("nodes"), ET.Element("edges")
    positions = {TLS: (length, length), "north": (length, 2 * length), "south": (length, 0),
                 "east": (2 * length, length), "west": (0, length)}
    for name, (x, y) in positions.items():
        ET.SubElement(nodes, "node", id=name, x=str(x), y=str(y),
                      type="traffic_light" if name == TLS else "priority")
    for direction in DIRECTIONS:
        for suffix, origin, target in (("in", direction, TLS), ("out", TLS, direction)):
            ET.SubElement(edges, "edge", {"id": f"{direction}_{suffix}", "from": origin, "to": target,
                          "numLanes": "2", "speed": str(settings["speed_m_s"]), "spreadType": "right"})
    connections, logics = ET.Element("connections"), ET.Element("tlLogics")
    program = ET.SubElement(logics, "tlLogic", id=TLS, type="static", programID="fourphase", offset="0")
    for p, green in enumerate(settings["fixed_green_seconds"]):
        for offset, duration in enumerate((green, settings["yellow_seconds"], settings["all_red_seconds"])):
            ET.SubElement(program, "phase", duration=str(duration), state=STATES[3 * p + offset])
    for index in range(8):
        attrs = connection_attributes(index)
        ET.SubElement(connections, "connection", attrs)
        ET.SubElement(logics, "connection", {**attrs, "tl": TLS, "linkIndex": str(index)})
    for name, root in (("network.nod.xml", nodes), ("network.edg.xml", edges),
                       ("network.con.xml", connections), ("network.tll.xml", logics)):
        write_xml(folder / name, root)


def audit_network(path, settings):
    """Reject inferred extra turns or reordered controlled links after netconvert."""
    root = ET.parse(path).getroot()
    programs = root.findall("tlLogic")
    if len(programs) != 1 or programs[0].get("id") != TLS:
        raise ValueError("Expected exactly the center4 traffic light")
    phases = programs[0].findall("phase")
    expected_durations = tuple(d for green in settings["fixed_green_seconds"] for d in (green, 3, 1))
    if tuple(p.get("state") for p in phases) != STATES or tuple(float(p.get("duration")) for p in phases) != expected_durations:
        raise ValueError("Compiled TLS phases differ from the four-phase protocol")
    controlled = root.findall(f"connection[@tl='{TLS}']")
    if len(controlled) != 8:
        raise ValueError("Expected eight controlled movements, without inferred extra turns")
    for index in range(8):
        links = [c for c in controlled if c.get("linkIndex") == str(index)]
        if len(links) != 1 or any(links[0].get(k) != v for k, v in connection_attributes(index).items()):
            raise ValueError(f"Compiled link {index} differs from the movement/lane specification")
    ordinary = [e for e in root.findall("edge") if e.get("function") != "internal"]
    if {e.get("id") for e in ordinary} != {f"{d}_{s}" for d in DIRECTIONS for s in ("in", "out")}:
        raise ValueError("Expected eight boundary edges")
    if any(len(e.findall("lane")) != 2 for e in ordinary):
        raise ValueError("Every boundary edge must have two lanes")
    return {"tls": TLS, "controlled_links": 8, "internal_phases": 12,
            "incoming_lanes": list(LANES), "states": list(STATES)}


def write_demand(folder, settings, level, seed):
    rng, vehicles = random.Random(seed), []
    end = settings["duration_seconds"] + settings["demand_extension_seconds"]
    rate = settings["demand_rates_veh_h"][level]
    departure = rng.expovariate(rate / 3600)
    while departure < end:
        direction = rng.choice(DIRECTIONS)
        turn = "left" if rng.random() < settings["left_turn_probability"] else "straight"
        # SUMO advances on a 1-second grid. Align scheduled departures to that
        # grid so every depart < horizon has actually been considered at cutoff.
        vehicles.append((math.floor(departure), direction, turn))
        departure += rng.expovariate(rate / 3600)
    root = ET.Element("routes")
    ET.SubElement(root, "vType", id="car", vClass="passenger", guiShape="passenger/sedan", carFollowModel="Krauss",
                  length=str(settings["vehicle_length_m"]), minGap=str(settings["vehicle_min_gap_m"]),
                  accel="2.6", decel="4.5", sigma="0.5", tau="1.0", maxSpeed=str(settings["speed_m_s"]))
    for index, (direction, turn) in enumerate(MOVEMENTS):
        ET.SubElement(root, "route", id=f"{direction}_{turn}",
                      edges=f"{direction}_in {connection_attributes(index)['to']}")
    palette = ("41,166,218", "240,169,58", "230,92,112", "79,181,151")
    for index, (depart, direction, turn) in enumerate(vehicles):
        ET.SubElement(root, "vehicle", id=f"veh_{index:06d}", type="car", route=f"{direction}_{turn}",
                      depart=f"{depart:.3f}", departLane=str(TURNS.index(turn)), departSpeed="max",
                      color=palette[DIRECTIONS.index(direction)])
    write_xml(folder / "demand.rou.xml", root)
    due = [v for v in vehicles if v[0] < settings["duration_seconds"]]
    if not due:
        raise ValueError("The pilot case must contain departures before the time limit")
    metadata = {"level": level, "demand_seed": seed, "sumo_seed": seed, "rate_veh_h": rate,
                "status": settings["demand_status"], "observation_end_s": settings["duration_seconds"],
                "generation_end_s": end, "scheduled_total": len(vehicles), "scheduled_due": len(due),
                "scheduled_after_cutoff": len(vehicles) - len(due),
                "due_by_movement": dict(Counter(f"{d}_{t}" for _, d, t in due))}
    write_json(folder / "demand.json", metadata)
    return metadata


def write_configuration(folder, settings, seed):
    root = ET.Element("configuration")
    inputs = ET.SubElement(root, "input")
    for name, value in (("net-file", "../../../network.net.xml"), ("route-files", "demand.rou.xml")):
        ET.SubElement(inputs, name, value=value)
    timing = ET.SubElement(root, "time")
    for name, value in (("begin", 0), ("end", settings["duration_seconds"]), ("step-length", 1)):
        ET.SubElement(timing, name, value=str(value))
    processing = ET.SubElement(root, "processing")
    for name, value in (("max-depart-delay", "-1"), ("time-to-teleport", "-1"),
                        ("collision.action", "warn"), ("collision.check-junctions", "true")):
        ET.SubElement(processing, name, value=value)
    ET.SubElement(ET.SubElement(root, "random_number"), "seed", value=str(seed))
    write_xml(folder / "run.sumocfg", root)
    ET.SubElement(ET.SubElement(root, "gui_only"), "gui-settings-file", value="../../../view.xml")
    write_xml(folder / "view.sumocfg", root)


def verify_scenario(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    validate_settings(manifest["settings"])
    for name, expected in manifest["sha256"].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or sha256(path) != expected:
            raise ValueError(f"Scenario input has changed: {name}; build a new scenario version")
    return manifest
