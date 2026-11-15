"""Build the main synthetic corridor; execution is initiated by the user."""

import argparse
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from common import ROOT, binary

sys.path.insert(0, str(ROOT))
from src.traffic.corridor import INCOMING, SIGNALS, make_case, read_settings, write_configuration, write_demand, write_network_inputs
from src.traffic.experiments import sha256, write_json
from src.traffic.safety_controller import EXPECTED_STATES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("sumo/corridor2"))
    parser.add_argument("--config", type=Path, default=ROOT / "configs/corridor2.json")
    args = parser.parse_args()
    settings = read_settings(args.config)
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / "sumo") or folder.exists():
        parser.error("Choose a new folder under sumo/; existing scenarios are preserved")
    folder.mkdir(parents=True)
    write_network_inputs(folder, settings)
    command = [binary("netconvert"), "--node-files", str(folder / "corridor2.nod.xml"),
               "--edge-files", str(folder / "corridor2.edg.xml"), "--connection-files", str(folder / "corridor2.con.xml"),
               "--tllogic-files", str(folder / "corridor2.tll.xml"), "--no-turnarounds", "true",
               "--output-file", str(folder / "corridor2.net.xml")]
    subprocess.run(command, check=True)
    root = ET.parse(folder / "corridor2.net.xml").getroot()
    if {p.attrib["id"] for p in root.findall("tlLogic")} != set(SIGNALS):
        raise ValueError("Expected exactly the two traffic signals A and B")
    for j in SIGNALS:
        program = next(p for p in root.findall("tlLogic") if p.attrib["id"] == j)
        if tuple(p.attrib["state"] for p in program.findall("phase")) != EXPECTED_STATES:
            raise ValueError(f"Unexpected phases at {j}")
        links = {int(c.attrib["linkIndex"]): c.attrib["from"] for c in root.findall("connection") if c.attrib.get("tl") == j}
        if links != dict(enumerate(INCOMING[j])):
            raise ValueError(f"Unexpected lane connection order at {j}")
    shutil.copy2(ROOT / "sumo/toy/toy.view.xml", folder / "corridor2.view.xml")
    write_configuration(folder, settings)
    write_configuration(folder, settings, gui=True)
    write_demand(folder, settings, "balanced", settings["seed"])
    for profile in settings["profiles"]:
        make_case(folder / "profiles" / profile / f"seed_{settings['seed']}", settings, profile, settings["seed"], folder)
    write_json(folder / "manifest.json", {"kind": "synthetic_corridor2", "settings": settings, "command": command,
               "status": "built_not_simulated", "sha256": {name: sha256(folder / name) for name in
                   ("corridor2.net.xml", "corridor2.sumocfg", "corridor2.gui.sumocfg", "corridor2.rou.xml", "corridor2.view.xml")}})
    print(f"입력 생성 완료: {folder}\nA/B 신호, 공동 행동 4개, 관측 31개. 아직 시뮬레이션은 하지 않았습니다.")


if __name__ == "__main__":
    main()
