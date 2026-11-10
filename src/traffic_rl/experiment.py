from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from .common import sha256, write_json
from .dqn import DQNAgent
from .env import CentralizedTrafficEnv


def write_csv(path, rows):
    if not rows:
        raise ValueError("no rows")
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def evaluate(directory, output, seeds, controllers, model=None, scale=1.0, gui=False, gui_delay_ms=1000):
    if len(set(seeds)) != len(seeds) or not seeds or min(seeds) < 0:
        raise ValueError("evaluation seeds must be distinct and nonnegative")
    if not controllers or len(set(controllers)) != len(controllers):
        raise ValueError("controllers must be nonempty and distinct")
    if "dqn" in controllers and model is None:
        raise ValueError("--model is required for dqn evaluation")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for seed in seeds:
        hashes = set()
        for controller in controllers:
            env = CentralizedTrafficEnv(directory, "rl" if controller == "dqn" else controller, gui=gui, output=output / controller / f"seed_{seed}", scale=scale, trace=True, gui_delay_ms=gui_delay_ms)
            try:
                agent = DQNAgent.load(model, env.checkpoint_schema) if controller == "dqn" else None
                if agent and seed in agent.metadata["training_seeds"]:
                    raise ValueError("Evaluation seed overlaps training seeds. Choose held-out seeds.")
                obs, info = env.reset(seed=seed)
                done = False
                while not done:
                    action = agent.act(obs, info["action_mask"]) if agent else int(np.flatnonzero(info["action_mask"])[0])
                    obs, _, terminated, truncated, info = env.step(action)
                    done = terminated or truncated
                row = dict(env.last_metrics)
                row["controller"] = controller
                rows.append(row)
                hashes.add(row["route_sha256"])
                if not row["count_balance_ok"] or not row["tripinfo_counts_match"]:
                    raise RuntimeError("Vehicle accounting mismatch. Inspect SUMO outputs before interpreting results.")
                if row["teleports"] or row["collision_events"]:
                    raise RuntimeError("Teleport or collision occurred; results require investigation.")
                print(f"{controller}, seed={seed}: wait={row['mean_wait_departed_censored_s']}, arrived={row['arrived']}, unfinished={row['unfinished']}, pending={row['not_departed']}", flush=True)
            finally:
                env.close()
        if len(hashes) != 1:
            raise RuntimeError("Paired demand hashes do not match")
    write_csv(output / "episodes.csv", rows)
    numeric = ["mean_wait_arrived_s", "mean_wait_departed_censored_s", "mean_travel_arrived_s", "arrived", "unfinished", "not_departed", "queue_vehicle_seconds", "pending_vehicle_seconds", "p95_queue_vehicles", "switches"]
    summaries = []
    for controller in controllers:
        subset = [r for r in rows if r["controller"] == controller]
        row = {"controller": controller, "n_seeds": len(subset)}
        for key in numeric:
            vals = [r[key] for r in subset if r[key] is not None]
            row[key + "_mean"] = float(np.mean(vals)) if vals else None
            row[key + "_std"] = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0 if vals else None
        summaries.append(row)
    write_csv(output / "summary.csv", summaries)
    paired = []
    baseline = "fixed" if "fixed" in controllers else "native" if "native" in controllers else None
    if baseline:
        for r in rows:
            if r["controller"] == baseline:
                continue
            fixed = next(f for f in rows if f["controller"] == baseline and f["seed"] == r["seed"])
            fw, rw = fixed["mean_wait_departed_censored_s"], r["mean_wait_departed_censored_s"]
            paired.append({"baseline_controller": baseline, "controller": r["controller"], "seed": r["seed"], "wait_reduction_percent": 100 * (fw - rw) / fw if fw and rw is not None else None, "arrived_delta": r["arrived"] - fixed["arrived"], "unfinished_delta": r["unfinished"] - fixed["unfinished"], "not_departed_delta": r["not_departed"] - fixed["not_departed"]})
    if paired:
        write_csv(output / "paired.csv", paired)
    write_json(output / "evaluation.json", {"seeds": seeds, "controllers": controllers, "model": str(model) if model else None, "model_sha256": sha256(model) if model else None, "scale": scale, "warmup_seconds": 0, "censored_wait_warning": "Departed-only lower-bound waiting average. Check arrived, unfinished, not_departed and pending time jointly.", "rows": rows, "summary": summaries})
    plot_evaluation(output, rows, controllers)
    return rows


def plot_evaluation(output, rows, controllers):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), constrained_layout=True)
    for ax, key, label in zip(axes, ["mean_wait_departed_censored_s", "arrived", "unfinished"], ["Observed wait / departed (s)", "Arrived vehicles", "Unfinished vehicles"]):
        for i, controller in enumerate(controllers):
            vals = [r[key] for r in rows if r["controller"] == controller and r[key] is not None]
            if vals:
                ax.bar(i, np.mean(vals), color=["#64748b", "#0891b2", "#ea580c", "#9333ea"][i % 4], alpha=0.7)
                ax.scatter([i] * len(vals), vals, color="#172554", s=16)
                if len(vals) > 1:
                    ax.errorbar(i, np.mean(vals), yerr=np.std(vals, ddof=1), color="#172554", capsize=5)
        ax.set_xticks(range(len(controllers)), controllers)
        ax.set_title(label)
        ax.grid(axis="y", alpha=0.2)
        ax.set_ylim(bottom=0)
        if key in ("arrived", "unfinished"):
            highest = max((r[key] for r in rows), default=0)
            ax.set_ylim(0, max(1, highest * 1.1))
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    fig.suptitle("Synthetic SUMO baseline | dots: held-out seeds | bars: mean +/- sample SD")
    fig.savefig(Path(output) / "comparison.png", dpi=160)
    plt.close(fig)


def plot_training(output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    output = Path(output)
    with (output / "training.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fig, ax = plt.subplots(figsize=(8, 3.8), constrained_layout=True)
    ax.plot([int(r["episode"]) for r in rows], [float(r["return"]) for r in rows], color="#0e7490", marker=".")
    ax.set(xlabel="Episode (different training demand seed)", ylabel="Episode return", title="Training return: exploratory policy, not evaluation performance")
    ax.grid(alpha=0.2)
    fig.savefig(output / "training.png", dpi=160)
    plt.close(fig)
