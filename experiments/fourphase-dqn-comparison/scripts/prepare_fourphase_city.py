"""Prepare a city display copy of the audited scenario, without running SUMO."""

import argparse
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from common import ROOT

sys.path.insert(0, str(ROOT))
from src.traffic.experiments import sha256, write_json
from src.traffic.fourphase.city_scene import CityGeometry
from src.traffic.fourphase.scenario import TLS, verify_scenario, write_xml


def prepare_city(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    manifest = verify_scenario(source)
    if output.exists():
        raise ValueError("Choose a new output folder; existing view inputs are preserved")
    root = ET.parse(source / "network.net.xml").getroot()
    junction = root.find(f"junction[@id='{TLS}']")
    center = (float(junction.attrib["x"]), float(junction.attrib["y"]))
    geometry = CityGeometry(center, manifest["settings"]["arm_length_m"]).build()
    output.mkdir(parents=True)
    copied = {}
    for name in ("network.net.xml", "settings.json"):
        shutil.copy2(source / name, output / name)
        copied[name] = sha256(source / name)
    for case in manifest["cases"]:
        relative = Path(case["folder"])
        (output / relative).mkdir(parents=True)
        for name in ("demand.rou.xml", "demand.json", "run.sumocfg"):
            path = relative / name
            shutil.copy2(source / path, output / path)
            copied[str(path)] = sha256(source / path)
        config = ET.parse(source / relative / "view.sumocfg").getroot()
        ET.SubElement(config.find("input"), "additional-files", value="../../../city.add.xml")
        write_xml(output / relative / "view.sumocfg", config)
    geometry.write(output / "city.add.xml")
    shutil.copy2(ROOT / "configs/fourphase_city.view.xml", output / "view.xml")
    scene = {"kind": "fourphase_city_display_v1", "center": center, "polygon_count": len(geometry.shapes),
             "signal_lamps": geometry.signal_lamps,
             "signals": "4 four-aspect heads (red/yellow/left arrow/straight green), reading 8 actual movement links",
             "source": str(source), "source_manifest_sha256": sha256(source / "manifest.json"),
             "physics_identical_sha256": copied, "standalone": "scenery and native signal bars; custom lamps unlit until Python connects"}
    if any(sha256(output / name) != digest for name, digest in copied.items()):
        raise ValueError("A traffic input changed while preparing the visual copy")
    write_json(output / "scene.json", scene)
    files = sorted(path for path in output.rglob("*") if path.is_file())
    write_json(output / "manifest.json", {"schema_version": 1, "kind": "synthetic_fourphase_city_v1",
               "status": "display prepared; GUI validation pending", "settings": manifest["settings"],
               "network_audit": manifest["network_audit"], "cases": manifest["cases"],
               "source_manifest_sha256": scene["source_manifest_sha256"],
               "sha256": {str(path.relative_to(output)): sha256(path) for path in files}})
    return scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("sumo/fourphase"))
    parser.add_argument("--output", type=Path, default=Path("sumo/fourphase_city"))
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT / "sumo") or output == ROOT / "sumo":
        parser.error("Choose a new output folder under sumo/")
    scene = prepare_city(ROOT / args.source, output)
    print(f"도시 화면 입력 생성 완료: {output}")
    print(f"주변 건물·공원·주차장·가로수와 4색 신호등 4개, 표시 도형 {scene['polygon_count']}개")
    print("도로·수요·고정신호는 기존 검증 입력과 동일합니다. 실시간 신호등은 view_fourphase.py로 연결하세요.")


if __name__ == "__main__":
    main()
