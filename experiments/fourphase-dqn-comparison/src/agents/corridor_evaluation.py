"""Matched three-controller evaluation for synthetic traffic cases."""

import csv
import math
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

from src.agents.evaluation import audit_signals
from src.traffic.corridor import SIGNALS, queue_action
from src.traffic.experiments import case_paths, write_json
from src.traffic.metrics import summarize
from src.traffic.safety_controller import EXPECTED_STATES


def audit_corridor_signal(records, minimum, maximum):
    """Audit complete phases plus the phase order and upper bounds at the ends."""
    first_phase = records[0]["phase_index"]
    first_change = next((i for i, r in enumerate(records) if r["phase_index"] != first_phase), len(records))
    violations = audit_signals(records[first_change:], minimum, maximum)
    if first_change < len(records) and records[first_change]["phase_index"] != (first_phase + 1) % 6:
        violations.append({"time": records[first_change]["time_s"], "reason": "first_phase_order"})
    for row in records:
        phase = row["phase_index"]
        bound = maximum if phase in (0, 3) else 3 if phase in (1, 4) else 1
        if row["phase_elapsed_s"] > bound + 1e-6:
            violations.append({"time": row["time_s"], "reason": "phase_upper_bound", "phase": phase})
        if row["signal_state"] != EXPECTED_STATES[phase]:
            violations.append({"time": row["time_s"], "reason": "phase_color_mismatch", "phase": phase})
    return violations


def run_episode(folder, case, settings, *, model=None, mode="agent", output=None):
    from src.envs.corridor_env import CorridorTrafficEnv

    if mode == "agent" and model is None:
        raise ValueError("DQN evaluation needs a model")
    if mode not in ("fixed", "queue", "agent"):
        raise ValueError("mode must be fixed, queue or agent")
    config, routes = case_paths(folder, case)
    output = Path(output) if output else None
    if output:
        output.mkdir(parents=True, exist_ok=False)
    env = CorridorTrafficEnv(sumo_config=config, route_files=[routes], settings=settings,
                             control_mode="fixed" if mode == "fixed" else "agent",
                             tripinfo_path=output / "tripinfo.xml" if output else None, record_signals=output is not None)
    samples, decisions = [], []
    try:
        observation, info = env.reset(seed=case["sumo_seed"])
        initial = info["raw_observation"]["junctions"]
        version = env.connection.getVersion()
        while True:
            action = 0 if mode == "fixed" else queue_action(observation, info) if mode == "queue" else int(model.predict(observation, deterministic=True)[0])
            observation, reward, terminated, truncated, info = env.step(action)
            samples.extend(info["samples"])
            decisions.append({"time_s": info["raw_observation"]["time_s"], "joint_action": action, "reward": reward,
                              **{f"{j}_{key}": info["action"][j][key] for j in SIGNALS for key in ("requested", "accepted", "reason")}})
            if terminated or truncated:
                break
    finally:
        env.close()
    if output is None:
        return {"episode_return": info["episode_return"], "final_info": info}
    schedule = {v.attrib["id"]: float(v.attrib["depart"]) for v in ET.parse(routes).iter("vehicle")}
    measured = [{"measured": True, "network_halting": s["halting_vehicles"], "step_seconds": 1} for s in samples]
    report = summarize(schedule, output / "tripinfo.xml", measured, settings["warmup_seconds"], settings["duration_seconds"])
    violations = {}
    for j in SIGNALS:
        records = [{"time_s": settings["warmup_seconds"], **initial[j]}]
        records += [{"time_s": s["time_s"], "phase_index": s[f"{j}_phase_index"],
                     "phase_elapsed_s": s[f"{j}_phase_elapsed_s"], "signal_state": s[f"{j}_signal_state"]} for s in samples]
        # The initial native phase may be partial due to the fixed offset.
        # Its start precedes the control window. Check its order/upper bound;
        # check full durations for the following complete phases.
        violations[j] = audit_corridor_signal(records, settings["min_green_seconds"], settings["max_green_seconds"])
    counts = report["counts"]
    checks = {"vehicle_accounting": counts["scheduled_total"] == counts["arrived"] + counts["unfinished"] + counts["not_departed_due"] + counts["scheduled_after_end"],
              "active_matches_unfinished": info["vehicles_running"] == counts["unfinished"],
              "departures_match_tripinfo": info["departed_total"] == counts["departed"],
              "arrivals_match_tripinfo": info["arrived_total"] == counts["arrived"],
              "reward_matches_queue_integral": math.isclose(-info["episode_return"], report["metrics"]["network_queue_vehicle_seconds"]),
              "signal_constraints": not any(violations.values()),
              # _advance_second raises on any collision/teleport, even in warm-up.
              "no_collision_or_teleport": True}
    report.update(controller="dqn" if mode == "agent" else mode, case=case, sumo_version=version,
                  episode_return=info["episode_return"], checks=checks, signal_violations=violations)
    write_json(output / "metrics.json", report)
    for name, rows in (("queues.csv", samples), ("decisions.csv", decisions)):
        with (output / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    if not all(checks.values()):
        raise RuntimeError(f"Evaluation checks failed: {output / 'metrics.json'}")
    return report


def summarize_results(rows):
    groups = {}
    for profile in sorted({r["profile"] for r in rows}):
        groups[profile] = {}
        for method in sorted({r["method"] for r in rows}):
            records = [r for r in rows if r["profile"] == profile and r["method"] == method]
            values = [r["cohort_mean_waiting_observed_s"] for r in records]
            if not records or any(v is None for v in values):
                raise ValueError("Cannot compare cases without departed cohort vehicles")
            groups[profile][method] = {"n_cases": len(records), "waiting_mean_s": statistics.fmean(values),
                "waiting_std_s": statistics.stdev(values) if len(values) > 1 else 0,
                "unfinished_mean": statistics.fmean(r["unfinished"] for r in records),
                "pending_mean": statistics.fmean(r["not_departed_due"] for r in records),
                "all_cohort_completed": all(r["cohort_unfinished"] == 0 and r["cohort_not_departed"] == 0 for r in records)}
        methods = groups[profile]
        if "fixed" in methods and "dqn" in methods:
            base, agent = methods["fixed"], methods["dqn"]
            agent["waiting_reduction_percent"] = (100 * (base["waiting_mean_s"] - agent["waiting_mean_s"]) / base["waiting_mean_s"]
                if base["all_cohort_completed"] and agent["all_cohort_completed"] and base["waiting_mean_s"] > 0 else None)
    return groups


def plot_results(folder, groups):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    profiles = list(groups)
    methods = list(groups[profiles[0]])
    fig, axes = plt.subplots(1, 2, figsize=(max(9, 2 * len(profiles)), 4))
    width = 0.8 / len(methods)
    for index, method in enumerate(methods):
        positions = [p - 0.4 + width * (index + 0.5) for p in range(len(profiles))]
        axes[0].bar(positions, [groups[p][method]["waiting_mean_s"] for p in profiles], width,
                    yerr=[groups[p][method]["waiting_std_s"] for p in profiles], label=method)
        axes[1].bar(positions, [groups[p][method]["unfinished_mean"] + groups[p][method]["pending_mean"] for p in profiles], width, label=method)
    axes[0].set_ylabel("Observed cohort waiting (s / vehicle)")
    axes[1].set_ylabel("Unfinished + pending vehicles")
    for ax in axes:
        ax.set_xticks(range(len(profiles)), profiles)
        ax.legend()
        ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(folder / "comparison.png", dpi=180)
    fig.savefig(folder / "comparison.svg")
    plt.close(fig)
