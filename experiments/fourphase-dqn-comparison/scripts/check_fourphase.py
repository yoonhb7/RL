"""Run paired fixed-time/random-valid-action pilots and preserve all failures."""

import argparse
import json
import random
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT

sys.path.insert(0, str(ROOT))
from src.envs.fourphase_env import FourPhaseTrafficEnv
from src.traffic.experiments import sha256, write_json
from src.traffic.fourphase.runtime import FourPhaseRuntime
from src.traffic.fourphase.scenario import verify_scenario


def add_tripinfo(summary, path):
    trips = ET.parse(path).getroot().findall("tripinfo")
    completed = [t for t in trips if float(t.get("arrival", "-1")) >= 0]
    durations = [float(t.attrib["duration"]) for t in completed]
    summary["metrics"]["ATT_completed_s"] = sum(durations) / len(durations) if durations else None
    summary["checks"]["arrivals_match_tripinfo"] = len(completed) == summary["counts"]["arrived"]
    summary["checks"]["departures_match_tripinfo"] = len(trips) == summary["counts"]["departed"]
    if not all(summary["checks"].values()):
        summary["status"] = "abnormal"


def run_case(folder, case, settings, controller, policy_seed):
    folder.mkdir(parents=True)
    with (folder / "seconds.jsonl").open("w", encoding="utf-8") as samples, \
         (folder / "transitions.jsonl").open("w", encoding="utf-8") as transitions:
        def sink(sample):
            samples.write(json.dumps(sample, ensure_ascii=False) + "\n")

        kwargs = {"settings": settings, "tripinfo": folder / "tripinfo.xml", "sample_sink": sink,
                  "error_log": folder / "sumo_warnings.log"}
        env = FourPhaseTrafficEnv(case, **kwargs) if controller == "random" else None
        runtime = env.runtime if env else FourPhaseRuntime(case, mode="fixed", **kwargs)
        summary = None
        failure = None
        version = None
        try:
            case_seed = int(case.name.removeprefix("seed_"))
            if env:
                state, info = env.reset(seed=case_seed)
                rng = random.Random(policy_seed)
                while True:
                    valid = [i for i, allowed in enumerate(info["action_mask"]) if allowed]
                    action = rng.choice(valid)
                    next_state, reward, terminated, truncated, next_info = env.step(action)
                    transitions.write(json.dumps({"state": state.tolist(), "action": action, "reward": reward,
                        "next_state": next_state.tolist(), "terminated": terminated, "truncated": truncated,
                        "next_action_mask": next_info["action_mask"].tolist(), "time_s": next_info["time_s"]}) + "\n")
                    if terminated:
                        raise RuntimeError("A time-limit-only task returned terminated=True")
                    if truncated:
                        summary = next_info["episode"]
                        summary["checks"]["truncation_keeps_bootstrap_mask"] = bool(next_info["action_mask"].any())
                        break
                    state, info = next_state, next_info
            else:
                runtime.reset(case_seed)
                while runtime.connection.simulation.getTime() < settings["duration_seconds"]:
                    runtime.advance_second()
                summary = runtime.summary()
            version = runtime.connection.getVersion()
        except KeyboardInterrupt:
            failure = {"reason": "user_interrupt", "type": "KeyboardInterrupt"}
        except Exception as error:
            failure = getattr(error, "event", {"reason": str(error), "type": type(error).__name__})
        finally:
            if failure and runtime.metrics is not None and runtime.connection is not None:
                try:
                    summary = runtime.summary(**({"raw_return": env.raw_return, "decisions": env.decisions} if env else {}))
                except Exception:
                    pass  # A disconnected SUMO process may not answer final queries.
            try:
                runtime.close()  # Flush tripinfo before parsing it.
            except Exception as error:
                failure = failure or {"reason": str(error), "type": type(error).__name__, "stage": "close"}
        if summary is None:
            summary = {"status": "abnormal", "metrics": {}, "checks": {}, "counts": {}, "failure": failure}
        if failure:
            summary.update(status="abnormal", failure=failure)
        elif (folder / "tripinfo.xml").is_file():
            try:
                add_tripinfo(summary, folder / "tripinfo.xml")
            except (ET.ParseError, OSError, ValueError) as error:
                summary.update(status="abnormal", failure={"reason": str(error), "stage": "tripinfo"})
        else:
            summary.update(status="abnormal", failure={"reason": "missing_tripinfo"})
        summary.update(controller=controller, policy_seed=policy_seed if env else None, sumo_version=version,
                       case=str(case), route_sha256=sha256(case / "demand.rou.xml"),
                       phase="environment pilot; no neural-network training")
        if summary["checks"] and not all(summary["checks"].values()):
            summary["status"] = "abnormal"
        write_json(folder / "metrics.json", summary)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("sumo/fourphase"))
    parser.add_argument("--levels", nargs="+", choices=("low", "medium", "high"), default=["low", "medium", "high"])
    parser.add_argument("--controllers", nargs="+", choices=("fixed", "random"), default=["fixed", "random"])
    parser.add_argument("--policy-seed", type=int, default=4242)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    scenario = (ROOT / args.scenario).resolve()
    manifest = verify_scenario(scenario)
    settings = manifest["settings"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = (ROOT / (args.output or Path(f"results/fourphase/check_{stamp}"))).resolve()
    if not output.is_relative_to(ROOT / "results") or output == ROOT / "results" or output.exists():
        parser.error("Choose a new output folder under results/")
    output.mkdir(parents=True)
    write_json(output / "inputs.json", {"manifest": manifest, "scenario_manifest_sha256": sha256(scenario / "manifest.json"),
                                       "policy_seed": args.policy_seed, "command": sys.argv})
    records = []
    for level in dict.fromkeys(args.levels):
        for controller in dict.fromkeys(args.controllers):
            case = scenario / "cases" / level / f"seed_{settings['pilot_seed']}"
            result_folder = output / f"{level}_{controller}"
            result = run_case(result_folder, case, settings, controller, args.policy_seed)
            records.append({"level": level, "controller": controller, "status": result["status"],
                            "metrics": result["metrics"], "checks": result["checks"], "failure": result["failure"],
                            "folder": str(result_folder.relative_to(output))})
            print(json.dumps(records[-1], ensure_ascii=False, indent=2))
            write_json(output / "summary.json", {"runs": records, "completed": sum(r["status"] == "completed" for r in records),
                       "abnormal": sum(r["status"] != "completed" for r in records), "all_passed": all(r["status"] == "completed" for r in records)})
            if result["failure"] and result["failure"].get("reason") == "user_interrupt":
                return 130
    print(f"검증 결과: {output / 'summary.json'}")
    return 0 if all(r["status"] == "completed" for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
