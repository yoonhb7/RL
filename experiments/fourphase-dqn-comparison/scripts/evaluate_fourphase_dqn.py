"""Compare the selected DQN and fixed-time on the same validation cases."""

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT

sys.path.insert(0, str(ROOT))
from src.agents.fourphase_data import LEVELS
from src.agents.fourphase_dqn import DQNPolicy
from src.agents.fourphase_evaluation import evaluate_cases
from src.traffic.experiments import sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    folder = (ROOT / args.run).resolve()
    if not folder.is_relative_to(ROOT / "results"):
        parser.error("Choose a project results folder")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    selection = json.loads((folder / "selection.json").read_text(encoding="utf-8"))
    model = folder / "best_model.pt"
    if sha256(model) != selection["checkpoint_sha256"]:
        raise ValueError("The selected checkpoint changed after validation selection")
    policy = DQNPolicy(model, expected_network_sha256=manifest["network_sha256"],
                       expected_settings=manifest["env_settings"])
    if policy.metadata["manifest_sha256"] != sha256(folder / "manifest.json"):
        raise ValueError("The frozen run manifest changed")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = (ROOT / args.output).resolve() if args.output else folder / "comparisons" / f"validation_{stamp}"
    if not output.is_relative_to(ROOT / "results") or output == ROOT / "results" or output.exists():
        parser.error("Choose a new output folder under results/")
    output.mkdir(parents=True)
    results = {}
    for name, controller in (("fixed", None), (policy.algorithm, policy)):
        results[name] = evaluate_cases(folder, manifest, "validation", output / name, policy=controller)
    fields = ("J_s_per_due_vehicle", "ATT_completed_s", "AQL_in_vehicles", "throughput_vehicles",
              "W_stop_in_vehicle_s", "W_pending_vehicle_s")
    rows = []
    for level in LEVELS:
        for controller, result in results.items():
            records = [r for r in result["runs"] if r["level"] == level]
            row = {"level": level, "controller": controller, "cases": len(records)}
            for key in fields:
                values = [r["metrics"][key] for r in records]
                row[key] = math.fsum(values) / len(values) if all(v is not None for v in values) else None
            for key in ("unfinished", "pending_due"):
                row[key] = math.fsum(r["counts"][key] for r in records) / len(records)
            rows.append(row)
    with (output / "comparison.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(output / "comparison.json", {"split": "validation", "selected_checkpoint": selection,
               "rows": rows, "test_cases_run": 0, "interpretation": "pilot; one trained policy, not final independent test"})
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    print(f"동일 검증 수요 비교: {output / 'comparison.csv'}")


if __name__ == "__main__":
    main()
