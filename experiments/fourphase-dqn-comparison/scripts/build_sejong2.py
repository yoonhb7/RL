"""Convert the frozen Sejong OSM subset and generate a fixed-time baseline."""

import argparse
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT, binary

sys.path.insert(0, str(ROOT))
from src.traffic.sejong_network import (
    audit_incoming_programs, digest, discover_ports, fixed_programs, network_inventory, prepare_osm,
    read_config, write_demand, write_json, write_xml,
)


def convert(command, log_path):
    with log_path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-25:])
        raise RuntimeError(f"netconvert failed; see {log_path}\n{tail}")


def write_configuration(folder, config, *, gui=False):
    root = ET.Element("configuration")
    inputs = ET.SubElement(root, "input")
    ET.SubElement(inputs, "net-file", value="sejong.net.xml")
    ET.SubElement(inputs, "route-files", value="sejong.rou.xml")
    timing = ET.SubElement(root, "time")
    for name, value in (("begin", 0), ("end", config["duration_seconds"]), ("step-length", 1)):
        ET.SubElement(timing, name, value=str(value))
    processing = ET.SubElement(root, "processing")
    ET.SubElement(processing, "time-to-teleport", value="-1")
    ET.SubElement(processing, "collision.check-junctions", value="true")
    ET.SubElement(ET.SubElement(root, "random_number"), "seed", value=str(config["seed"]))
    if gui:
        ET.SubElement(ET.SubElement(root, "gui_only"), "gui-settings-file", value="sejong.view.xml")
    write_xml(folder / ("sejong.gui.sumocfg" if gui else "sejong.sumocfg"), root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/sejong2.json")
    parser.add_argument("--output", type=Path, default=Path("sumo/sejong2"))
    parser.add_argument("--seed", type=int, help="Demand and SUMO seed (default: config)")
    args = parser.parse_args()
    config = read_config(args.config)
    if args.seed is not None:
        if args.seed < 0:
            parser.error("seed must be nonnegative")
        config["seed"] = args.seed
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / "sumo"):
        parser.error("Output must be a new folder under sumo/")
    if folder.exists() and any(folder.iterdir()):
        parser.error("Output is not empty; choose a new --output (for example sumo/sejong2_v2)")
    converter = binary("netconvert")
    import sumolib
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / "config.json", config)
    print("1/4 OSM 도로 추출 및 가정 기록", flush=True)
    targets = prepare_osm(config, folder)
    signals = config["signals"]
    first_command = [converter, "--osm-files", str(folder / "sejong.selected.osm.xml"),
                     "--node-files", str(folder / "sejong.joins.nod.xml"),
                     "--output-file", str(folder / "sejong.draft.net.xml"),
                     "--keep-edges.by-vclass", "passenger", "--osm.turn-lanes", "true",
                     "--no-turnarounds", "true", "--tls.default-type", "static", "--tls.layout", signals.get("layout", "opposites"),
                     "--tls.green.time", str(signals["green_seconds"]),
                     "--tls.left-green.time", str(signals["left_green_seconds"]),
                     "--tls.yellow.time", str(signals["yellow_seconds"]),
                     "--tls.allred.time", str(signals["all_red_seconds"]),
                     "--output.original-names", "true"]
    print("2/4 도로 변환 및 두 교차로 연결", flush=True)
    convert(first_command, folder / "netconvert_import.log")
    write_xml(folder / "sejong.fixed.tll.xml", fixed_programs(folder / "sejong.draft.net.xml", config))
    second_command = [converter, "--sumo-net-file", str(folder / "sejong.draft.net.xml"),
                      "--tllogic-files", str(folder / "sejong.fixed.tll.xml"),
                      "--output-file", str(folder / "sejong.net.xml"), "--no-turnarounds", "true"]
    convert(second_command, folder / "netconvert_fixed.log")
    inventory = network_inventory(folder / "sejong.net.xml")
    if len(inventory) != 2 or {s["id"] for s in inventory} != {j["id"] for j in config["junctions"]}:
        raise ValueError("Final network does not contain exactly the two intended fixed signal programs")
    if any(not s["links"] or not s["phases"] or any(p["duration"] <= 0 for p in s["phases"])
           for s in inventory):
        raise ValueError("Invalid signal connections or phase durations")
    if signals.get("layout") == "incoming":
        signal_audit = audit_incoming_programs(folder / "sejong.net.xml", signals)
        write_json(folder / "signal_plan_audit.json", signal_audit)
    print("3/4 경계 진입·유출 및 유효 OD 경로 생성", flush=True)
    net = sumolib.net.readNet(str(folder / "sejong.net.xml"))
    ports = discover_ports(net, config)
    demand = write_demand(net, ports, config, folder, config["seed"])
    through = [route for route in demand["routes"].values()
               if all(any(net.getEdge(edge).getToNode().getID() == target["id"]
                          for edge in route["edges"]) for target in targets)]
    if not through:
        raise ValueError("No generated route traverses both target junctions")
    print("4/4 실행 설정·차로/현시 목록·입력 해시 저장", flush=True)
    write_configuration(folder, config)
    write_configuration(folder, config, gui=True)
    shutil.copy2(ROOT / "configs/sejong2.view.xml", folder / "sejong.view.xml")
    write_json(folder / "network_inventory.json", {"junctions": inventory, "ports": ports,
               "edge_count": len(net.getEdges()), "routes_crossing_both": len(through)})
    files = ("sejong.net.xml", "sejong.rou.xml", "sejong.sumocfg", "sejong.gui.sumocfg", "sejong.view.xml",
             "sejong.selected.osm.xml", "sejong.joins.nod.xml", "sejong.fixed.tll.xml",
             "config.json", "assumptions.json", "network_inventory.json", "demand.json")
    if signals.get("layout") == "incoming":
        files += ("signal_plan_audit.json",)
    manifest = {"schema_version": 1, "status": "built_not_simulated",
                "built_at_utc": datetime.now(timezone.utc).isoformat(), "config": config,
                "source_osm_sha256": config["osm_sha256"], "targets": targets,
                "commands": [first_command, second_command], "files_sha256": {name: digest(folder / name) for name in files},
                "attribution": "OpenStreetMap contributors, ODbL 1.0", "source_url": config["osm_url"]}
    write_json(folder / "manifest.json", manifest)
    print(json.dumps({"output": str(folder), "signals": [s["id"] for s in inventory],
                      "vehicles": demand["vehicle_count"], "unreachable_od": demand["unreachable_od"],
                      "data_status": "OSM geometry; assumed demand and signal plans; simulation pending"},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
