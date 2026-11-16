"""Run real SUMO checks of the corrected ATT protocol; this is not a trained-model benchmark."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT

sys.path.insert(0, str(ROOT))
from src.agents.fourphase_evaluation import run_episode
from src.traffic.experiments import sha256, write_json
from src.traffic.fourphase.scenario import read_settings


class ProtocolCheckPolicy:
    algorithm = "untrained_hold_until_forced_protocol_check"

    def choose(self, state, mask, *, greedy=True):
        return 0 if mask[0] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels", nargs="+", choices=("low", "medium", "high"), default=["low", "medium", "high"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = (ROOT / (args.output or Path(f"results/att_check_{stamp}"))).resolve()
    if not output.is_relative_to(ROOT / "results") or output == ROOT / "results":
        parser.error("Use a new output folder under results/")
    output.mkdir(parents=True, exist_ok=False)
    settings, records = read_settings(), []
    for level in args.levels:
        case_folder = ROOT / "sumo/fourphase/cases" / level / "seed_42"
        original_hash = sha256(case_folder / "demand.rou.xml")
        case = {"id": f"{level}_seed42", "level": level, "demand_seed": 42, "sumo_seed": 42}
        result = run_episode(case_folder, case, settings, output / case["id"], policy=ProtocolCheckPolicy())
        if sha256(case_folder / "demand.rou.xml") != original_hash:
            raise RuntimeError("The source demand was modified")
        records.append(result)
        write_json(output / "summary.json", {"purpose": "untrained_ATT_protocol_check", "runs": records})
        print(json.dumps({"level": level, "ATT_s": result["metrics"]["ATT_s"],
                          "counts_at_3600": result["counts"], "drain": result["drain"],
                          "all_checks_pass": all(result["checks"].values())}, ensure_ascii=False), flush=True)
    print(f"ATT check results: {output}", flush=True)


if __name__ == "__main__":
    main()
