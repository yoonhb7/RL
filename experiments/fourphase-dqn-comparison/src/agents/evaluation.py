"""Paired native-fixed/DQN evaluation with incomplete-vehicle accounting."""

import csv
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from src.traffic.experiments import case_paths, write_json
from src.traffic.metrics import summarize


def audit_signals(rows, minimum, maximum):
    violations = []
    previous = None
    start = None
    for row in rows:
        phase = row["phase_index"]
        phase_start = row["time_s"] - row["phase_elapsed_s"]
        if previous is None:
            previous, start = phase, phase_start
        elif phase != previous:
            if phase != (previous + 1) % 6:
                violations.append({"time": row["time_s"], "reason": "phase_order"})
            duration = phase_start - start
            valid = minimum - 1e-6 <= duration <= maximum + 1e-6 if previous in (0, 3) else math.isclose(
                duration, 3 if previous in (1, 4) else 1, abs_tol=1e-6,
            )
            if not valid:
                violations.append({"time": row["time_s"], "reason": "phase_duration", "phase": previous, "duration": duration})
            previous, start = phase, phase_start
    return violations


def run_episode(folder, case, settings, *, model=None, mode="agent", output=None):
    from src.envs.toy_env import ToyTrafficEnv

    if mode == "agent" and model is None:
        raise ValueError("Agent evaluation requires a model")
    config_path, route_path = case_paths(folder, case)
    output = Path(output) if output is not None else None
    if output is not None:
        output.mkdir(parents=True, exist_ok=False)
    env = ToyTrafficEnv(
        sumo_config=config_path, route_files=[route_path], settings=settings, control_mode=mode,
        tripinfo_path=output / "tripinfo.xml" if output else None, record_signals=output is not None,
    )
    samples, decisions = [], []
    try:
        observation, info = env.reset(seed=case["sumo_seed"])
        initial = dict(info["raw_observation"])
        version = env.connection.getVersion()
        while True:
            action = int(model.predict(observation, deterministic=True)[0]) if mode == "agent" else 0
            observation, reward, terminated, truncated, info = env.step(action)
            samples.extend(info["samples"])
            decisions.append({
                "time_s": info["raw_observation"]["time_s"], "action": action if mode == "agent" else "fixed",
                "reward": reward, "accepted": info["action"]["accepted"], "reason": info["action"]["reason"],
                "forced_switches": info["forced_switches"],
            })
            if terminated or truncated:
                break
    finally:
        env.close()  # Flush TripInfo, including unfinished vehicles, before parsing.
    result = {"episode_return": info["episode_return"], "final_info": info, "sumo_version": version}
    if output is None:
        return result

    schedule = {v.get("id"): float(v.get("depart")) for v in ET.parse(route_path).iter("vehicle")}
    metric_samples = [{"measured": True, "network_halting": s["halting_vehicles"], "step_seconds": 1} for s in samples]
    report = summarize(schedule, output / "tripinfo.xml", metric_samples, settings["warmup_seconds"], settings["duration_seconds"])
    counts = report["counts"]
    violations = audit_signals([initial, *samples], settings["min_green_seconds"], settings["max_green_seconds"])
    checks = {
        "vehicle_accounting": counts["scheduled_total"] == counts["arrived"] + counts["unfinished"] + counts["not_departed_due"] + counts["scheduled_after_end"],
        "active_matches_unfinished": info["vehicles_running"] == counts["unfinished"],
        "departures_match_tripinfo": info["departed_total"] == counts["departed"],
        "arrivals_match_tripinfo": info["arrived_total"] == counts["arrived"],
        "reward_matches_queue_integral": math.isclose(-info["episode_return"], report["metrics"]["network_queue_vehicle_seconds"]),
        "signal_constraints": not violations,
    }
    report.update({
        "controller": "dqn" if mode == "agent" else "fixed", "case": case, "sumo_version": version,
        "episode_return": info["episode_return"], "forced_switches": sum(d["forced_switches"] for d in decisions),
        "checks": checks, "signal_violations": violations,
    })
    write_json(output / "metrics.json", report)
    for filename, rows in (("queues.csv", samples), ("decisions.csv", decisions)):
        with (output / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    if not all(checks.values()):
        raise RuntimeError(f"평가 검증 실패: {output / 'metrics.json'}")
    return report
