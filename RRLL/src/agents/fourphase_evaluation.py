"""One complete, audited episode and equally weighted validation ATT (model-selection score)."""

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from src.envs.fourphase_env import FourPhaseTrafficEnv
from src.traffic.experiments import write_json
from src.traffic.fourphase.metrics import InvalidRun
from .fourphase_data import LEVELS, case_path


def complete_trip_metrics(summary, path, departed_ids, arrived_ids):
    trips = ET.parse(path).getroot().findall("tripinfo")
    completed = [t for t in trips if float(t.get("arrival", "-1")) >= 0]
    # ATT/AWT follow the CityFlow (TSCC 2019) and LibSignal definition: every vehicle that entered
    # the network counts. SUMO writes unfinished trips with duration = end - depart and
    # waitingTime accumulated until the end, so all tripinfo entries are used as they are.
    durations = [float(t.attrib["duration"]) for t in trips]
    if any(not math.isfinite(value) or value < 0 for value in durations):
        raise ValueError("Invalid trip duration")
    waits = [float(t.attrib["waitingTime"]) for t in trips]
    if any(not math.isfinite(value) or value < 0 for value in waits):
        raise ValueError("Invalid trip waiting time")
    summary["metrics"]["ATT_s"] = math.fsum(durations) / len(durations) if durations else None
    summary["metrics"]["AWT_s"] = math.fsum(waits) / len(waits) if waits else None
    summary["checks"].update(
        tripinfo_departed_ids_match=len(trips) == len(departed_ids) and {t.attrib["id"] for t in trips} == set(departed_ids),
        tripinfo_arrived_ids_match=len(completed) == len(arrived_ids) and {t.attrib["id"] for t in completed} == set(arrived_ids),
    )
    if not all(summary["checks"].values()):
        summary["status"] = "abnormal"
    return summary


def run_episode(case_folder, case, settings, output, *, policy, training=False, on_transition=None,
                record_seconds=False):
    """Run one full 3,600 s episode with a DQN policy (ε-greedy while training, greedy for validation)."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    samples = (output / "seconds.jsonl").open("w", encoding="utf-8") if record_seconds else None

    def sink(sample):
        if samples is not None:
            samples.write(json.dumps(sample, ensure_ascii=False) + "\n")

    kwargs = {"settings": settings, "tripinfo": output / "tripinfo.xml", "error_log": output / "sumo_warnings.log",
              "sample_sink": sink if record_seconds else None}
    env = FourPhaseTrafficEnv(case_folder, **kwargs)
    runtime = env.runtime
    summary = problem = None
    version = None
    try:
        state, info = env.reset(seed=case["sumo_seed"])
        version = runtime.connection.getVersion()
        while True:
            action = policy.choose(state, info["action_mask"], greedy=not training)
            next_state, reward, terminated, truncated, next_info = env.step(action)
            if terminated:
                raise RuntimeError("The continuing traffic task unexpectedly terminated")
            if on_transition is not None:
                on_transition(state, info, action, reward, next_state, next_info, terminated, truncated)
            if truncated:
                summary = next_info["episode"]
                summary["checks"]["truncation_retains_valid_next_mask"] = bool(next_info["action_mask"].any())
                break
            state, info = next_state, next_info
    except BaseException as error:
        problem = error
        event = getattr(error, "event", {"reason": str(error), "type": type(error).__name__})
        write_json(output / "failure.json", event)
        if runtime.metrics is not None and runtime.connection is not None:
            try:
                summary = runtime.summary(raw_return=env.raw_return, decisions=env.decisions)
                summary.update(status="abnormal", failure=event)
            except Exception:
                pass
    finally:
        try:
            runtime.close()  # Flush completed/unfinished tripinfo before parsing.
        except Exception as error:
            if problem is None:
                problem = error
                write_json(output / "failure.json", {"reason": str(error), "stage": "close"})
        if samples is not None:
            samples.close()
    if summary is not None:
        summary.update(case_id=case["id"], level=case["level"], demand_seed=case["demand_seed"],
                       sumo_seed=case["sumo_seed"], sumo_version=version,
                       controller=f"{policy.algorithm}_{'training' if training else 'greedy'}")
        if problem is None:
            try:
                complete_trip_metrics(summary, output / "tripinfo.xml", runtime.metrics.departed, runtime.metrics.arrived)
            except Exception as error:
                problem = error
                summary.update(status="abnormal", failure={"reason": str(error), "stage": "tripinfo"})
        write_json(output / "metrics.json", summary)
    if problem is not None:
        raise problem
    if summary is None or summary["status"] != "completed" or not all(summary["checks"].values()):
        event = {"reason": "episode_validation_failed", "checks": summary["checks"] if summary else {}}
        write_json(output / "failure.json", event)
        raise InvalidRun(event)
    return summary


def validation_score(records):
    levels = {}
    for level in LEVELS:
        selected = [r for r in records if r["level"] == level]
        if not selected or any(r["status"] != "completed" for r in selected):
            raise ValueError("All validation cases must finish; abnormal cases cannot be silently dropped")
        scores = [r["metrics"]["ATT_s"] for r in selected]
        if any(value is None or not math.isfinite(value) for value in scores):
            raise ValueError("Invalid validation ATT")
        levels[level] = math.fsum(scores) / len(scores)
    return math.fsum(levels.values()) / 3, levels


def evaluate_cases(folder, manifest, split, output, *, policy):
    """Greedy (ε=0) runs on the frozen validation cases; the score selects the best checkpoint."""
    if split != "validation":
        raise ValueError("Only the validation split is used during training")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for case in manifest["cases"][split]:
        print(f"  {split}: {case['id']} ({policy.algorithm})", flush=True)
        try:
            result = run_episode(case_path(folder, manifest, case), case, manifest["env_settings"],
                                 output / case["id"], policy=policy)
        except BaseException as error:
            metrics_file = output / case["id"] / "metrics.json"
            failed = json.loads(metrics_file.read_text()) if metrics_file.is_file() else {
                "case_id": case["id"], "level": case["level"], "status": "abnormal",
                "failure": {"type": type(error).__name__, "reason": str(error)}}
            failed["status"] = "abnormal"
            records.append(failed)
            write_json(output / "summary.json", {"split": split, "status": "failed", "runs": records,
                       "ATT_equal_level_mean": None, "completed": sum(r["status"] == "completed" for r in records),
                       "abnormal": sum(r["status"] != "completed" for r in records),
                       "unattempted": len(manifest["cases"][split]) - len(records)})
            raise
        records.append(result)
        write_json(output / "progress.json", {"finished": len(records), "total": len(manifest["cases"][split])})
    score, levels = validation_score(records)
    summary = {"split": split, "ATT_equal_level_mean": score, "ATT_by_level": levels, "runs": records,
               "completed": len(records), "abnormal": 0}
    write_json(output / "summary.json", summary)
    return summary
