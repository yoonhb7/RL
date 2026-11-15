"""Generate reproducible explicit vehicle departures without changing a network."""

import json
import math
import random
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from src.traffic.safety_controller import DIRECTIONS


def write_demand(folder, config, seed):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    root = ET.Element("routes")
    ET.SubElement(root, "vType", id="car", vClass="passenger", accel="2.6", decel="4.5",
                  sigma="0.5", length="5", minGap="2.5", maxSpeed="13.89")
    opposite = {"north": "south", "south": "north", "east": "west", "west": "east"}
    end = config["demand_end_seconds"]
    if not math.isfinite(end) or end <= 0:
        raise ValueError("Demand end must be positive and finite")
    vehicles = []
    for direction in DIRECTIONS:
        ET.SubElement(root, "route", id=direction, edges=f"{direction}_in {opposite[direction]}_out")
        rate = config["flow_vehicles_per_hour"][direction]
        if not math.isfinite(rate) or rate < 0:
            raise ValueError("Flow must be finite and nonnegative")
        if rate == 0:
            continue
        departure = rng.expovariate(rate / 3600)
        index = 0
        while departure < end:
            text = f"{int(departure * 1000) / 1000:.3f}"
            vehicles.append((float(text), direction, index, text))
            departure += rng.expovariate(rate / 3600)
            index += 1
    for _, direction, index, text in sorted(vehicles):
        ET.SubElement(root, "vehicle", id=f"{direction}_{index:05d}", type="car", route=direction,
                      depart=text, departLane="0", departSpeed="max")
    ET.indent(root)
    ET.ElementTree(root).write(folder / "toy.rou.xml", encoding="utf-8", xml_declaration=True)
    metadata = {
        "seed": seed, "generation": "seeded exponential interarrival times, explicit vehicles",
        "vehicle_count": len(vehicles), "vehicles_by_approach": dict(Counter(row[1] for row in vehicles)),
        "config": config,
    }
    (folder / "demand.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata
