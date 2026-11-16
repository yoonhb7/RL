"""One complete, audited episode and equally weighted validation ATT (model-selection score)."""

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from src.envs.fourphase_env import FourPhaseTrafficEnv
from src.traffic.experiments import sha256, write_json
from src.traffic.fourphase.metrics import InvalidRun
from .fourphase_data import LEVELS, case_path


ATT_PROTOCOL = "scheduled_departure_to_arrival_all_due_v1"
DEFAULT_MAX_DRAIN_SECONDS = 14400


def write_evaluation_cohort(source, destination, horizon):
    """Copy a route file without future demand; never change the frozen source file."""
    tree = ET.parse(source)
    root = tree.getroot()
    for vehicle in list(root.findall("vehicle")):
        if float(vehicle.attrib["depart"]) >= horizon:
            root.remove(vehicle)
    tree.write(destination, encoding="utf-8", xml_declaration=True)


def complete_trip_metrics(summary, path, departed_ids, arrived_ids, *, scheduled, horizon, require_complete=False):
    trips = ET.parse(path).getroot().findall("tripinfo")
    completed = [t for t in trips if float(t.get("arrival", "-1")) >= 0]
    due = {vehicle: depart for vehicle, depart in scheduled.items() if depart < horizon}
    by_id = {t.attrib["id"]: t for t in trips}
    if not due or not set(by_id) <= set(due):
        raise ValueError("Tripinfo must contain only the nonempty scheduled evaluation cohort")
    durations = [float(t.attrib["duration"]) for t in trips]
    if any(not math.isfinite(value) or value < 0 for value in durations):
        raise ValueError("Invalid trip duration")
    waits = [float(t.attrib["waitingTime"]) for t in trips]
    if any(not math.isfinite(value) or value < 0 for value in waits):
        raise ValueError("Invalid trip waiting time")
    # The original entered-only, censored measurement is retained for diagnosis,
    # but is never used for checkpoint selection under the corrected protocol.
    summary["metrics"]["ATT_entered_tripinfo_s"] = math.fsum(durations) / len(durations) if durations else None
    elapsed, observed_wait, complete_elapsed, complete_wait = [], [], [], []
    for vehicle, requested in due.items():
        trip = by_id.get(vehicle)
        if trip is None:
            elapsed.append(horizon - requested)
            observed_wait.append(horizon - requested)
            continue
        depart = float(trip.attrib["depart"])
        arrival = float(trip.get("arrival", "-1"))
        delay = depart - requested
        if not math.isfinite(depart) or delay < -1e-6 or not math.isfinite(arrival):
            raise ValueError("Invalid departure or arrival time")
        elapsed.append((min(arrival, horizon) if arrival >= 0 else horizon) - requested)
        observed_wait.append(float(trip.attrib["waitingTime"]) + delay)
        if arrival >= 0:
            if not math.isclose(arrival - depart, float(trip.attrib["duration"]), abs_tol=1e-3):
                raise ValueError("Trip duration disagrees with departure/arrival")
            complete_elapsed.append(arrival - requested)
            complete_wait.append(float(trip.attrib["waitingTime"]) + delay)
    all_arrived = len(completed) == len(due) and set(by_id) == set(due)
    summary["metrics"].update(
        ATT_s=math.fsum(complete_elapsed) / len(due) if all_arrived else None,
        AWT_s=math.fsum(complete_wait) / len(due) if all_arrived else None,
        ATT_observed_due_s=math.fsum(elapsed) / len(due),
    )
    if not require_complete:
        summary["metrics"]["AWT_observed_due_s"] = math.fsum(observed_wait) / len(due)
    summary["ATT_protocol"] = {"name": ATT_PROTOCOL, "denominator": "all_departures_scheduled_before_cutoff",
                               "cohort_size": len(due), "all_arrived": all_arrived,
                               "includes_insertion_delay": True, "observation_cutoff_s": horizon}
    summary["checks"].update(
        tripinfo_departed_ids_match=len(trips) == len(departed_ids) and {t.attrib["id"] for t in trips} == set(departed_ids),
        tripinfo_arrived_ids_match=len(completed) == len(arrived_ids) and {t.attrib["id"] for t in completed} == set(arrived_ids),
    )
    if require_complete:
        summary["checks"]["ATT_all_scheduled_due_vehicles_arrived"] = all_arrived
    if not all(summary["checks"].values()):
        summary["status"] = "abnormal"
    return summary


def run_episode(case_folder, case, settings, output, *, policy, training=False, on_transition=None,
                record_seconds=False, max_drain_seconds=DEFAULT_MAX_DRAIN_SECONDS):
    """Train for 3,600 s; validation additionally clears the fixed cohort without learning."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    samples = (output / "seconds.jsonl").open("w", encoding="utf-8") if record_seconds else None

    def sink(sample):
        if samples is not None:
            samples.write(json.dumps(sample, ensure_ascii=False) + "\n")

    kwargs = {"settings": settings, "tripinfo": output / "tripinfo.xml", "error_log": output / "sumo_warnings.log",
              "sample_sink": sink if record_seconds else None}
    if not training:
        if type(max_drain_seconds) is not int or max_drain_seconds <= 0 or max_drain_seconds % 15:
            raise ValueError("Validation needs a positive drain limit divisible by 15")
        cohort_path = output / "evaluation_cohort.rou.xml"
        write_evaluation_cohort(Path(case_folder) / "demand.rou.xml", cohort_path, settings["duration_seconds"])
        kwargs.update(route_file_override=cohort_path, max_drain_seconds=max_drain_seconds)
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
                if not training:
                    runtime.start_drain()
                    state, info = next_state, next_info
                    while runtime.metrics.due != set(runtime.metrics.arrived):
                        action = policy.choose(state, info["action_mask"], greedy=True)
                        state, info = env.drain_step(action)
                    summary["drain"] = {"status": "completed", "seconds": runtime.now - settings["duration_seconds"],
                                        "end_time_s": runtime.now, "max_seconds": max_drain_seconds,
                                        "learning_updates": 0, "arrived": len(runtime.metrics.arrived),
                                        "cohort_sha256": sha256(cohort_path)}
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
                complete_trip_metrics(summary, output / "tripinfo.xml", runtime.metrics.departed, runtime.metrics.arrived,
                                      scheduled=runtime.metrics.scheduled, horizon=settings["duration_seconds"],
                                      require_complete=not training)
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
        if not selected or any(r["status"] != "completed" or
                               r.get("ATT_protocol", {}).get("name") != ATT_PROTOCOL or
                               not r.get("ATT_protocol", {}).get("all_arrived") for r in selected):
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
                                 output / case["id"], policy=policy,
                                 max_drain_seconds=manifest["config"].get("evaluation_max_drain_seconds", DEFAULT_MAX_DRAIN_SECONDS))
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
    summary = {"split": split, "ATT_protocol": ATT_PROTOCOL, "ATT_equal_level_mean": score, "ATT_by_level": levels, "runs": records,
               "completed": len(records), "abnormal": 0}
    write_json(output / "summary.json", summary)
    return summary
