"""Build auditable inputs from a frozen OSM extract, without changing toy inputs."""

import copy
import hashlib
import json
import math
import random
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_xml(path, root):
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def read_config(path=None):
    config = json.loads(Path(path or ROOT / "configs/sejong2.json").read_text(encoding="utf-8"))
    if not 0 <= config["warmup_seconds"] < config["demand_end_seconds"] <= config["duration_seconds"]:
        raise ValueError("Expected 0 <= warmup < demand end <= duration")
    if config["step_length_seconds"] != 1:
        raise ValueError("This baseline records one-second samples")
    if len(config["junctions"]) != 2 or len({j["id"] for j in config["junctions"]}) != 2:
        raise ValueError("Two distinct target junctions are required")
    for port, values in config["ports"].items():
        rate = values["vehicles_per_hour"]
        if not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate < 0:
            raise ValueError(f"Invalid rate for {port}")
        weights = config["destination_weights"][port]
        if not weights or any(destination == port or destination not in config["ports"]
                              or not math.isfinite(weight) or weight <= 0
                              for destination, weight in weights.items()):
            raise ValueError(f"Invalid destination weights for {port}")
    return config


def clipped_refs(refs, nodes, bbox):
    """Retain the in-box run and one outside geometry point at each end.

    The extra points avoid inventing coordinates. Disconnected in-box runs fail
    explicitly instead of introducing a shortcut across a missing road segment.
    """
    west, south, east, north = bbox
    inside = [i for i, ref in enumerate(refs)
              if west <= float(nodes[ref].attrib["lon"]) <= east
              and south <= float(nodes[ref].attrib["lat"]) <= north]
    if not inside:
        return []
    if inside != list(range(inside[0], inside[-1] + 1)):
        raise ValueError("Selected way leaves and re-enters the clip box; split it explicitly")
    return refs[max(0, inside[0] - 1):min(len(refs), inside[-1] + 2)]


def prepare_osm(config, folder):
    source = (ROOT / config["osm_source"]).resolve()
    if not source.is_relative_to(ROOT) or digest(source) != config["osm_sha256"]:
        raise ValueError("OSM source hash differs from the frozen configuration")
    original = ET.parse(source).getroot()
    nodes = {node.attrib["id"]: node for node in original.findall("node")}
    ways = {way.attrib["id"]: way for way in original.findall("way")}
    subset = ET.Element("osm", version="0.6", generator="RL Term Project OSM subset",
                        attribution="OpenStreetMap contributors", license="https://opendatacommons.org/licenses/odbl/1-0/")
    selected, used_nodes, assumptions = [], set(), []
    for way_id, family in config["selected_ways"].items():
        source_way = ways[way_id]
        refs = clipped_refs([item.attrib["ref"] for item in source_way.findall("nd")], nodes,
                            config["clip_bbox_lon_lat"])
        if len(refs) < 2:
            raise ValueError(f"Selected OSM way {way_id} has no usable in-box section")
        tags = {item.attrib["k"]: item.attrib["v"] for item in source_way.findall("tag")}
        patch = {"way_id": way_id, "name": tags.get("name", ""), "source_tags": dict(tags), "assumed": {}}
        if "lanes" not in tags:
            one_way = tags.get("oneway") in {"yes", "true", "1", "-1"}
            key = "arterial_oneway" if one_way else "side_two_way_total"
            tags["lanes"] = str(config["missing_lane_defaults"][key])
            patch["assumed"]["lanes"] = tags["lanes"]
        # Speed is an explicit experimental assumption, including where an OSM
        # value is present; record both the source tag and the replacement.
        tags["maxspeed"] = str(config["assumed_speed_kmh"][family])
        patch["assumed"]["maxspeed_kmh"] = tags["maxspeed"]
        way = ET.Element("way", id=way_id, version="1")
        for ref in refs:
            ET.SubElement(way, "nd", ref=ref)
        for key, value in sorted(tags.items()):
            ET.SubElement(way, "tag", k=key, v=value)
        selected.append(way)
        used_nodes.update(refs)
        assumptions.append(patch)
    for junction in config["junctions"]:
        missing = set(junction["osm_nodes"]) - used_nodes
        if missing:
            raise ValueError(f"Target join contains absent OSM nodes: {sorted(missing)}")
    for node_id in sorted(used_nodes, key=int):
        node = nodes[node_id]
        # Retain coordinates, but not intermediate traffic-light/crossing tags.
        # Exactly two assumed controllers are declared by the explicit joins.
        ET.SubElement(subset, "node", id=node_id, version="1", lat=node.attrib["lat"], lon=node.attrib["lon"])
    subset.extend(selected)
    write_xml(folder / "sejong.selected.osm.xml", subset)
    joins = ET.Element("nodes")
    targets = []
    for item in config["junctions"]:
        ET.SubElement(joins, "join", id=item["id"], nodes=" ".join(item["osm_nodes"]),
                      type="traffic_light", tl=item["id"], tlType="static", reset="true")
        coordinates = [(float(nodes[ref].attrib["lon"]), float(nodes[ref].attrib["lat"]))
                       for ref in item["osm_nodes"]]
        targets.append({**item, "longitude": sum(p[0] for p in coordinates) / len(coordinates),
                        "latitude": sum(p[1] for p in coordinates) / len(coordinates)})
    write_xml(folder / "sejong.joins.nod.xml", joins)
    write_json(folder / "assumptions.json", {"data_status": "OSM geometry with synthetic operational assumptions",
               "junctions": targets, "way_parameters": assumptions, "limitations": config["limitations"]})
    return targets


def fixed_programs(path, config):
    root = ET.parse(path).getroot()
    programs = root.findall("tlLogic")
    expected = {item["id"] for item in config["junctions"]}
    if {p.attrib["id"] for p in programs} != expected or len(programs) != 2:
        raise ValueError("Conversion did not produce exactly the two requested signal controllers")
    offsets = {item["id"]: item["offset_seconds"] for item in config["junctions"]}
    patch = ET.Element("tlLogics")
    for program in programs:
        program = copy.deepcopy(program)
        program.set("type", "static")
        program.set("offset", str(offsets[program.attrib["id"]]))
        patch.append(program)
    return patch


def expected_fixed_phase(time_s, phases, offset_s=0):
    """Phase active when SUMO evaluates the beginning of a physical time step.

    simulationStep advances the clock after evaluating this phase. A queue row
    stamped t+1 therefore corresponds to the phase at t, including at boundaries.
    Offsets may place the first sample in a partially elapsed phase.
    """
    cycle = sum(phase["duration"] for phase in phases)
    if cycle <= 0 or any(phase["duration"] <= 0 for phase in phases):
        raise ValueError("Fixed phase durations must be positive")
    local_time = (time_s - offset_s) % cycle
    for index, phase in enumerate(phases):
        if local_time < phase["duration"]:
            return index
        local_time -= phase["duration"]
    raise ValueError("Invalid fixed program cycle")


def audit_incoming_programs(path, signals):
    """Reject permissive/conflicting greens and missing clearance in a new build.

    The selected network uses individual, ungrouped signal links. Under this
    explicit precondition the request and TLS indices have the same ordering.
    This is a static check, not evidence that a simulation is collision-free.
    """
    root = ET.parse(path).getroot()
    report = {}
    for program in root.findall("tlLogic"):
        signal_id = program.attrib["id"]
        connections = [item.attrib for item in root.findall("connection") if item.attrib.get("tl") == signal_id]
        by_index = {int(item["linkIndex"]): item for item in connections}
        node = next(item for item in root.findall("junction") if item.attrib["id"] == signal_id)
        foes = {int(item.attrib["index"]): item.attrib["foes"][::-1] for item in node.findall("request")}
        count = len(by_index)
        if (len(connections) != count or set(by_index) != set(range(count)) or set(foes) != set(by_index)
                or any(len(bits) != count for bits in foes.values())):
            raise ValueError(f"Cannot audit grouped or ambiguous request indices at {signal_id}")
        phases = program.findall("phase")
        green_phases, covered, origins = [], set(), set()
        for index, phase in enumerate(phases):
            state = phase.attrib["state"]
            if len(state) != count or set(state) - set("rGy"):
                raise ValueError(f"Unsupported/permissive signal state at {signal_id} phase {index}")
            green = [link for link, char in enumerate(state) if char == "G"]
            if not green:
                continue
            incoming = {by_index[link]["from"] for link in green}
            if len(incoming) != 1 or "y" in state:
                raise ValueError(f"More than one incoming approach receives green at {signal_id}")
            for position, left in enumerate(green):
                for right in green[position + 1:]:
                    a, b = by_index[left], by_index[right]
                    merging = a["to"] == b["to"] and a["toLane"] == b["toLane"] and a["fromLane"] != b["fromLane"]
                    if foes[left][right] == "1" or foes[right][left] == "1" or merging:
                        raise ValueError(f"Conflicting green links {left}/{right} at {signal_id}")
            yellow = phases[(index + 1) % len(phases)]
            red = phases[(index + 2) % len(phases)]
            if (yellow.attrib["state"] != "".join("y" if char == "G" else "r" for char in state)
                    or float(yellow.attrib["duration"]) != signals["yellow_seconds"]
                    or red.attrib["state"] != "r" * count
                    or float(red.attrib["duration"]) != signals["all_red_seconds"]):
                raise ValueError(f"Green phase lacks the configured yellow/all-red clearance at {signal_id}")
            covered.update(green)
            origins.update(incoming)
            green_phases.append(index)
        if (not green_phases or covered != set(by_index) or len(phases) != 3 * len(green_phases)
                or origins != {item["from"] for item in connections}):
            raise ValueError(f"Incomplete approach coverage at {signal_id}")
        report[signal_id] = {"green_phase_indices": green_phases, "approaches": sorted(origins),
                             "links": count, "all_links_served": True, "conflicting_green_pairs": 0,
                             "yellow_seconds": signals["yellow_seconds"], "all_red_seconds": signals["all_red_seconds"]}
    if not report:
        raise ValueError("No signal programs to audit")
    return report


def way_id(edge):
    match = re.match(r"^-?(\d+)(?:#.*)?$", edge.getID())
    if not match:
        raise ValueError(f"Unrecognized imported edge ID: {edge.getID()}")
    return match.group(1)


def is_fringe(node):
    neighbours = {edge.getFromNode().getID() for edge in node.getIncoming()}
    neighbours.update(edge.getToNode().getID() for edge in node.getOutgoing())
    neighbours.discard(node.getID())
    return len(neighbours) == 1


def discover_ports(net, config):
    edges = [edge for edge in net.getEdges() if edge.allows("passenger")]
    ports = {}
    for name, spec in config["ports"].items():
        incoming = [edge for edge in edges if way_id(edge) == spec["incoming_way"] and is_fringe(edge.getFromNode())]
        outgoing = [edge for edge in edges if way_id(edge) == spec["outgoing_way"] and is_fringe(edge.getToNode())]
        if len(incoming) != 1 or len(outgoing) != 1:
            raise ValueError(f"Port {name}: expected one entry and one exit; got "
                             f"{[e.getID() for e in incoming]} / {[e.getID() for e in outgoing]}")
        ports[name] = {"incoming": incoming[0].getID(), "outgoing": outgoing[0].getID()}
    return ports


def write_demand(net, ports, config, folder, seed):
    rng = random.Random(seed)
    root = ET.Element("routes")
    ET.SubElement(root, "vType", id="car", vClass="passenger", guiShape="passenger/sedan", accel="2.6",
                  decel="4.5", sigma="0.5", length="5", minGap="2.5", maxSpeed="13.89")
    routes, normalized, unreachable = {}, {}, []
    for origin, weights in config["destination_weights"].items():
        available = {}
        for destination, weight in weights.items():
            path, cost = net.getShortestPath(net.getEdge(ports[origin]["incoming"]),
                                             net.getEdge(ports[destination]["outgoing"]), vClass="passenger")
            if path is None:
                unreachable.append({"origin": origin, "destination": destination, "weight": weight})
                continue
            route_id = f"{origin}__{destination}"
            edge_ids = [edge.getID() for edge in path]
            routes[route_id] = {"edges": edge_ids, "length_m": cost}
            ET.SubElement(root, "route", id=route_id, edges=" ".join(edge_ids))
            available[destination] = weight
        if not available:
            raise ValueError(f"No destination reachable from {origin}")
        total = sum(available.values())
        normalized[origin] = {destination: weight / total for destination, weight in available.items()}
    vehicles, by_od = [], Counter()
    for origin, spec in config["ports"].items():
        rate = spec["vehicles_per_hour"]
        if rate == 0:
            continue
        departure, index = rng.expovariate(rate / 3600), 0
        destinations = sorted(normalized[origin])
        weights = [normalized[origin][destination] for destination in destinations]
        while departure < config["demand_end_seconds"]:
            destination = rng.choices(destinations, weights=weights)[0]
            route_id = f"{origin}__{destination}"
            rounded = math.floor(departure * 1000) / 1000
            vehicles.append((rounded, f"{origin}_{index:05d}", route_id))
            by_od[route_id] += 1
            departure += rng.expovariate(rate / 3600)
            index += 1
    for departure, vehicle_id, route_id in sorted(vehicles):
        ET.SubElement(root, "vehicle", id=vehicle_id, type="car", route=route_id,
                      depart=f"{departure:.3f}", departLane="best", departSpeed="max")
    write_xml(folder / "sejong.rou.xml", root)
    metadata = {"seed": seed, "source": "synthetic exponential arrivals and assumed OD weights",
                "vehicle_count": len(vehicles), "vehicles_by_od": dict(sorted(by_od.items())),
                "requested_destination_weights": config["destination_weights"],
                "normalized_reachable_weights": normalized, "unreachable_od": unreachable,
                "ports": ports, "routes": routes}
    write_json(folder / "demand.json", metadata)
    return metadata


def network_inventory(path):
    root = ET.parse(path).getroot()
    lanes = {edge.attrib["id"]: [lane.attrib for lane in edge.findall("lane")]
             for edge in root.findall("edge") if edge.attrib.get("function") != "internal"}
    connections = list(root.findall("connection"))
    inventory = []
    for program in root.findall("tlLogic"):
        signal_id = program.attrib["id"]
        phases = [{"duration": float(p.attrib["duration"]), "state": p.attrib["state"]}
                  for p in program.findall("phase")]
        links = [dict(item.attrib) for item in connections if item.attrib.get("tl") == signal_id]
        incoming = sorted({link["from"] for link in links})
        inventory.append({"id": signal_id, "program_id": program.attrib["programID"],
                          "offset_s": float(program.attrib.get("offset", 0)),
                          "cycle_s": sum(p["duration"] for p in phases), "phases": phases,
                          "incoming_edges": incoming,
                          "incoming_lanes": [lane["id"] for edge in incoming for lane in lanes[edge]],
                          "links": links})
    return inventory
