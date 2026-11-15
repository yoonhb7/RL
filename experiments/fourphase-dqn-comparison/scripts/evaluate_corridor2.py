"""Compare fixed, queue rule and optional DQN on matched held-out cases."""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT

sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("sumo/corridor2"))
    parser.add_argument("--run", type=Path, help="Completed corridor2 DQN run; uses its frozen test cases")
    parser.add_argument("--profiles", nargs="+")
    parser.add_argument("--seeds", nargs="+", type=int, help="Baseline-only demand seeds")
    parser.add_argument("--controllers", nargs="+", choices=("fixed", "queue", "dqn"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.profiles and len(set(args.profiles)) != len(args.profiles):
        parser.error("profiles must be unique")
    from src.agents.corridor_evaluation import plot_results, run_episode, summarize_results
    from src.traffic.corridor import prepare_cases, read_scenario, relative_cases
    from src.traffic.experiments import sha256, write_json

    run = (ROOT / args.run).resolve() if args.run else None
    methods = args.controllers or (["fixed", "queue", "dqn"] if run else ["fixed", "queue"])
    if len(set(methods)) != len(methods):
        parser.error("controllers must be unique")
    if "dqn" in methods and run is None:
        parser.error("DQN evaluation requires --run")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = (ROOT / args.output).resolve() if args.output else run / "evaluation" if run else ROOT / f"results/corridor2/baseline_{stamp}"
    if not output.is_relative_to(ROOT / "results") or output.exists():
        parser.error("Choose a new output folder under results/")
    model = None
    if run:
        if not run.is_relative_to(ROOT):
            parser.error("run must be inside the project")
        manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("kind") != "synthetic_corridor2":
            parser.error("This evaluator requires a corridor2 training run")
        if args.seeds is not None:
            parser.error("--run uses frozen test seeds; omit --seeds")
        settings = manifest["env_settings"]
        selected = args.profiles or manifest["profiles"]
        if set(selected) - set(manifest["profiles"]):
            parser.error("Selected profiles are absent from the run's test split")
        cases = [case for case in manifest["cases"]["test"] if case["profile"] in selected]
        case_root = run
        if "dqn" in methods:
            from stable_baselines3 import DQN
            status = json.loads((run / "training_summary.json").read_text(encoding="utf-8"))
            if status["status"] != "completed":
                parser.error("Evaluate a normally completed run")
            model = DQN.load(str(run / "best_model.zip"), device="cpu")
            if model.observation_space.shape != (31,) or model.action_space.n != 4:
                parser.error("Model schema differs from corridor2")
        output.mkdir(parents=True)
    else:
        source = (ROOT / args.scenario).resolve()
        if not source.is_relative_to(ROOT):
            parser.error("scenario must be inside this project")
        settings = read_scenario(source)
        selected = args.profiles or list(settings["profiles"])
        seeds = args.seeds or [1000, 1001, 1002]
        if len(set(seeds)) != len(seeds) or any(seed < 0 for seed in seeds):
            parser.error("seeds must be unique and nonnegative")
        output.mkdir(parents=True)
        cases = relative_cases(prepare_cases(output / "cases", source, settings, selected, seeds), output)
        case_root = output
    if not cases:
        parser.error("No cases selected")
    write_json(output / "manifest.json", {"kind": "corridor2_evaluation", "source_run": str(run) if run else None,
               "settings": settings, "controllers": methods, "cases": cases,
               "model_sha256": sha256(run / "best_model.zip") if model is not None else None})
    rows = []
    for case in cases:
        for method in methods:
            print(f"[평가] {case['profile']} seed={case['demand_seed']} controller={method}", flush=True)
            report = run_episode(case_root, case, settings, mode="agent" if method == "dqn" else method,
                                 model=model if method == "dqn" else None,
                                 output=output / "cases_results" / case["profile"] / f"seed_{case['demand_seed']}" / method)
            rows.append({"profile": case["profile"], "method": method, "demand_seed": case["demand_seed"],
                         **report["counts"], **report["metrics"], "episode_return": report["episode_return"]})
    with (output / "comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    groups = summarize_results(rows)
    write_json(output / "summary.json", {"profiles": groups, "variation": "sample SD across demand cases for one training seed"})
    plot_results(output, groups)
    print(json.dumps({"output": str(output), "profiles": groups}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
