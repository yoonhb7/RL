"""Prepare portable SUMO inputs using RL1114's unchanged vehicle generator."""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from common import ROOT as PROJECT

sys.path.insert(0, str(PROJECT))
from src.traffic.rl1114_scene.common import ROOT, file_hash, write_json
from src.traffic.rl1114_scene.scenario import DIRS, prepare_demand, write_xml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1001)
    parser.add_argument("--output", type=Path, default=ROOT / "cases")
    args = parser.parse_args()
    folder = (PROJECT / args.output).resolve()
    if args.seed < 0:
        parser.error("seed must be nonnegative")
    if not folder.is_relative_to(ROOT) or folder == ROOT or folder.exists():
        parser.error("새 출력 폴더를 sumo/rl1114_city/ 아래에 지정하세요. 기존 폴더는 보존합니다.")
    cfg = json.loads((ROOT / "scene_settings.json").read_text(encoding="utf-8"))
    settings = cfg["scenario"]
    horizon = settings["demand_seconds"] + settings["drain_seconds"]
    network = ROOT / "network/network.net.xml"
    net = ET.parse(network).getroot()
    if {j.get("id") for j in net.findall("tlLogic")} != {"J"}:
        raise ValueError("RL1114 단일 교차로 J 네트워크가 필요합니다")
    program = net.find("tlLogic")
    folder.mkdir(parents=True)
    reports = []
    for level in ("low", "medium", "high"):
        case = folder / level
        _, demand = prepare_demand(cfg, level, args.seed, "eval", directory=case)
        additional = ET.Element("additional")
        for direction in DIRS:
            ET.SubElement(additional, "laneAreaDetector", id=f"det_{direction}", lane=f"{direction}_in_0",
                          pos=str(-settings["detector_length_m"]), length=str(settings["detector_length_m"]),
                          freq=str(horizon + 1), file="detector-output.xml")
        write_xml(case / "detectors.add.xml", additional)
        configuration = ET.Element("configuration")
        inputs = ET.SubElement(configuration, "input")
        for name, value in (("net-file", Path(os.path.relpath(network, case)).as_posix()),
                            ("route-files", "demand.rou.xml"), ("additional-files", "detectors.add.xml")):
            ET.SubElement(inputs, name, value=value)
        timing = ET.SubElement(configuration, "time")
        for name, value in (("begin", 0), ("end", horizon + 10), ("step-length", 1)):
            ET.SubElement(timing, name, value=str(value))
        processing = ET.SubElement(configuration, "processing")
        for name, value in (("time-to-teleport", "-1"), ("max-depart-delay", "-1"), ("collision.action", "warn")):
            ET.SubElement(processing, name, value=value)
        ET.SubElement(ET.SubElement(configuration, "random_number"), "seed", value=str(args.seed))
        ET.SubElement(ET.SubElement(configuration, "gui_only"), "gui-settings-file",
                      value=Path(os.path.relpath(ROOT / "gui.xml", case)).as_posix())
        write_xml(case / "view.sumocfg", configuration)
        report = {"level": level, "seed": args.seed, "requested_vph": demand["requested_vph"],
                  "scheduled": demand["scheduled"], "horizon_seconds": horizon,
                  "source_commit": cfg["commit"], "network_sha256": file_hash(network),
                  "demand_sha256": demand["sha256"], "controller": "native SUMO fixed-time program",
                  "phases": [p.attrib for p in program.findall("phase")]}
        write_json(case / "scene.json", report)
        reports.append(report)
    write_json(folder / "preparation.json", {"status": "inputs_prepared_not_simulated", "cases": reports})
    print(json.dumps({"output": str(folder), "cases": reports}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
