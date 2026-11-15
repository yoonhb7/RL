"""Shared, split-aware result accounting and plots for validation and held-out tests."""

import csv
import hashlib
import json
import math
import statistics
from pathlib import Path


LEVELS = ("low", "medium", "high")
CONTROLLERS = ("fixed", "dqn", "double_dqn", "dueling_dqn")
LABELS = ("Fixed-time", "DQN", "Double DQN", "Dueling DQN")
COLORS = ("#64748b", "#2563eb", "#ea580c", "#16a34a")
METRICS = ("J_s_per_due_vehicle", "ATT_completed_s", "AQL_in_vehicles", "throughput_vehicles",
           "W_stop_in_vehicle_s", "W_pending_vehicle_s")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inside(folder, relative):
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder):
        raise ValueError(f"Input path is outside its run: {path}")
    return path


def case_signature(manifest, split="validation"):
    cases = manifest["cases"][split]
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError(f"Duplicate {split} case IDs")
    return {case["id"]: {key: case[key] for key in
            ("level", "demand_seed", "sumo_seed", "scheduled_due", "sha256")} for case in cases}


def checked_records(summary, manifest, controller, *, split="validation"):
    expected = case_signature(manifest, split)
    records = summary["runs"]
    if summary["split"] != split or len(records) != len(expected):
        raise ValueError(f"Use the complete {split} set; other splits or partial results cannot be substituted")
    if len({run["case_id"] for run in records}) != len(records) or {r["case_id"] for r in records} != set(expected):
        raise ValueError(f"{split} cases are missing or duplicated")
    for run in records:
        case = expected[run["case_id"]]
        if any(run[key] != case[key] for key in ("level", "demand_seed", "sumo_seed")):
            raise ValueError("Case identity differs from its manifest")
        label = "fixed" if controller == "fixed" else f"{controller}_greedy"
        if run["controller"] != label or run["status"] != "completed" or run.get("failure") is not None:
            raise ValueError("Wrong controller or abnormal run; cases must not be silently excluded")
        if not run["checks"] or not all(value is True for value in run["checks"].values()):
            raise ValueError("A run failed its checks")
        if run["time_s"] != manifest["env_settings"]["duration_seconds"]:
            raise ValueError("Observation window changed")
        counts, metrics = run["counts"], run["metrics"]
        if counts["scheduled_due"] != case["scheduled_due"] or counts["scheduled_due"] <= 0:
            raise ValueError("Scheduled demand differs from the frozen inputs")
        for key in METRICS:
            value = metrics[key]
            if value is None and key == "ATT_completed_s" and counts["arrived"] == 0:
                continue
            if isinstance(value, bool) or value is None or not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid metric: {key}")
        expected_j = (metrics["W_stop_in_vehicle_s"] + metrics["W_pending_vehicle_s"]) / counts["scheduled_due"]
        if not math.isclose(metrics["J_s_per_due_vehicle"], expected_j, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("J does not match stop/pending burden")
    return records


def aggregate(records, controller, training_seed):
    rows = []
    for level in LEVELS:
        group = [run for run in records if run["level"] == level]
        if not group:
            raise ValueError("Every controller needs all three traffic levels")
        row = {"controller": controller, "training_seed": training_seed, "level": level, "cases": len(group)}
        for key in METRICS:
            values = [run["metrics"][key] for run in group]
            row[key] = statistics.mean(values) if all(v is not None for v in values) else None
            row[f"{key}_sd_demand"] = statistics.stdev(values) if len(values) > 1 and all(v is not None for v in values) else None
        for key in ("scheduled_due", "departed", "arrived", "unfinished", "pending_due"):
            row[key] = statistics.mean(run["counts"][key] for run in group)
        row["switches"] = statistics.mean(run["switches"] for run in group)
        rows.append(row)
    return rows


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_traffic_metrics(report, output):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(12, 8), dpi=160)
    panels = (("J_s_per_due_vehicle", "J (s / due vehicle), lower is better"),
              ("ATT_completed_s", "Completed ATT (s), lower is better"),
              ("AQL_in_vehicles", "Mean queue (vehicles), lower is better"),
              ("throughput_vehicles", "Throughput (vehicles / 3600 s), higher is better"))
    for axis, (key, title) in zip(figure.subplots(2, 2).flat, panels):
        for index, (controller, label, color) in enumerate(zip(CONTROLLERS, LABELS, COLORS)):
            positions = [level_index + (index - 1.5) * .2 for level_index in range(3)]
            rows = [next(row for row in report["rows"] if row["controller"] == controller and row["level"] == level) for level in LEVELS]
            axis.bar(positions, [row[key] if row[key] is not None else math.nan for row in rows],
                     width=.18, color=color, alpha=.8, label=label)
            for position, level in zip(positions, LEVELS):
                values = [case[key] for case in report["cases"] if case["controller"] == controller and case["level"] == level and case[key] is not None]
                axis.scatter([position + (i - (len(values) - 1) / 2) * .025 for i in range(len(values))],
                             values, s=14, facecolors="white", edgecolors=color, linewidths=.9, zorder=3)
        axis.set(title=title, xticks=range(3), xticklabels=("Low", "Medium", "High"), ylim=(0, None))
        axis.grid(axis="y", alpha=.2)
        axis.set_axisbelow(True)
    split = "held-out test" if report["split"] == "test" else "validation"
    figure.suptitle(f"Preliminary {split} | training seed {report['training_seed']}\nBars: demand-case means; dots: individual demand cases", fontsize=13)
    handles, labels = figure.axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", ncol=4, frameon=False)
    figure.tight_layout(rect=(0, .045, 1, .92))
    FigureCanvasAgg(figure).print_png(str(output / "traffic_metrics.png"))
