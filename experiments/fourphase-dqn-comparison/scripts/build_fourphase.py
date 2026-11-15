"""Build the new protected-left-turn scenario when explicitly run by the user."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from common import ROOT, binary

sys.path.insert(0, str(ROOT))
from src.traffic.experiments import sha256, write_json
from src.traffic.fourphase.scenario import (
    audit_network, read_settings, write_configuration, write_demand, write_network_inputs,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("sumo/fourphase"))
    parser.add_argument("--config", type=Path, default=ROOT / "configs/fourphase.json")
    args = parser.parse_args()
    folder = (ROOT / args.output).resolve()
    if not folder.is_relative_to(ROOT / "sumo") or folder == ROOT / "sumo" or folder.exists():
        parser.error("Choose a new folder under sumo/; existing scenarios are preserved")
    settings = read_settings(args.config)
    folder.mkdir(parents=True)
    write_json(folder / "settings.json", settings)
    write_network_inputs(folder, settings)
    command = [binary("netconvert"), "--node-files", str(folder / "network.nod.xml"),
               "--edge-files", str(folder / "network.edg.xml"), "--connection-files", str(folder / "network.con.xml"),
               "--tllogic-files", str(folder / "network.tll.xml"), "--no-turnarounds", "true",
               "--output-file", str(folder / "network.net.xml")]
    subprocess.run(command, check=True)
    audit = audit_network(folder / "network.net.xml", settings)
    shutil.copy2(ROOT / "configs/fourphase.view.xml", folder / "view.xml")
    cases = []
    for level in ("low", "medium", "high"):
        case = folder / "cases" / level / f"seed_{settings['pilot_seed']}"
        case.mkdir(parents=True)
        demand = write_demand(case, settings, level, settings["pilot_seed"])
        write_configuration(case, settings, settings["pilot_seed"])
        cases.append({"level": level, "seed": settings["pilot_seed"], "folder": str(case.relative_to(folder)),
                      "scheduled_due": demand["scheduled_due"]})
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    write_json(folder / "manifest.json", {"schema_version": 1, "kind": "synthetic_fourphase_v1",
               "status": "built; simulation validation pending", "settings": settings, "network_audit": audit,
               "netconvert_command": command, "cases": cases,
               "sha256": {str(path.relative_to(folder)): sha256(path) for path in files}})
    print(f"입력 생성 완료: {folder}")
    print("4방향 진입 8차로, 보호 좌회전 4현시, 내부 TLS 12단계, 관측 13개, 행동 2개")
    print("수요율은 파일럿 후보입니다. 다음: scripts/check_fourphase.py")


if __name__ == "__main__":
    main()
