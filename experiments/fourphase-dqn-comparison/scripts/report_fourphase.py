"""Summarize cached validation results; never runs SUMO, training or test cases."""

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.agents.fourphase_learning import load_learning_logs, plot_learning_curves
from src.agents.fourphase_results import (CONTROLLERS, LABELS, LEVELS, METRICS, aggregate,
    case_signature, checked_records, digest, inside, plot_traffic_metrics, read_json, write_csv)


def collect(run_folders, fixed_run, fixed_summary):
    sources, selected, histories, learning = [], {}, {}, {}
    reference, common_config, training_seed = None, None, None
    for folder in run_folders:
        manifest = read_json(folder / "manifest.json")
        training = read_json(folder / "training_summary.json")
        selection = read_json(folder / "selection.json")
        algorithm = manifest["algorithm"]
        if algorithm not in CONTROLLERS[1:] or algorithm in selected or training["status"] != "completed":
            raise ValueError("Provide one completed run for each of DQN, Double and pure Dueling")
        config = {key: value for key, value in manifest["config"].items() if key != "algorithm"}
        if reference is None:
            reference, common_config, training_seed = manifest, config, training["seed"]
        if config != common_config or training["seed"] != training_seed or training["algorithm"] != algorithm:
            raise ValueError("This preliminary report requires one common training seed and shared settings")
        summary_path = inside(folder, selection["folder"]) / "summary.json"
        model = inside(folder, selection["checkpoint"])
        if digest(model) != selection["checkpoint_sha256"] or digest(summary_path) != selection["validation_summary_sha256"]:
            raise ValueError("A selected checkpoint or its validation results changed")
        summary = read_json(summary_path)
        if not math.isclose(summary["J_equal_level_mean"], selection["J"], rel_tol=1e-9):
            raise ValueError("Selection score differs from its validation summary")
        selected[algorithm] = (manifest, summary)
        history_path = folder / "validations.jsonl"
        histories[algorithm] = [json.loads(line) for line in history_path.read_text().splitlines() if line.strip()]
        history = histories[algorithm]
        if (not history or any(value["decisions"] <= 0 or not math.isfinite(value["J"]) or
                any(not math.isfinite(value["J_by_level"][level]) for level in LEVELS) for value in history) or
                any(right["decisions"] <= left["decisions"] for left, right in zip(history, history[1:]))):
            raise ValueError("Validation learning history is invalid or out of order")
        chosen = [value for value in history if value["decisions"] == selection["decisions"]]
        if len(chosen) != 1 or not math.isclose(chosen[0]["J"], selection["J"], rel_tol=1e-9):
            raise ValueError("The selected checkpoint is missing from the validation learning history")
        learning[algorithm] = load_learning_logs(folder, manifest["config"], training)
        learning[algorithm]["selected_decisions"] = selection["decisions"]
        sources.append({"controller": algorithm, "run": str(folder), "checkpoint": str(model),
                        "checkpoint_sha256": digest(model), "summary": str(summary_path),
                        "summary_sha256": digest(summary_path), "manifest_sha256": digest(folder / "manifest.json"),
                        "selection_sha256": digest(folder / "selection.json"), "history_sha256": digest(history_path),
                        "episodes_sha256": digest(folder / "episodes.jsonl"), "updates_sha256": digest(folder / "updates.jsonl")})
    if set(selected) != set(CONTROLLERS[1:]):
        raise ValueError("All three algorithms are required")
    fixed_summary = inside(fixed_run, fixed_summary)
    selected["fixed"] = (read_json(fixed_run / "manifest.json"), read_json(fixed_summary))
    sources.append({"controller": "fixed", "run": str(fixed_run), "summary": str(fixed_summary),
                    "summary_sha256": digest(fixed_summary), "manifest_sha256": digest(fixed_run / "manifest.json")})
    rows, cases = [], []
    for controller in CONTROLLERS:
        manifest, summary = selected[controller]
        if (manifest["network_sha256"] != reference["network_sha256"] or
                manifest["env_settings"] != reference["env_settings"] or
                case_signature(manifest) != case_signature(reference)):
            raise ValueError("Road, environment or validation inputs differ between controllers")
        folder = next(Path(source["run"]) for source in sources if source["controller"] == controller)
        if digest(folder / "network.net.xml") != manifest["network_sha256"]:
            raise ValueError("The frozen road network changed")
        for case in manifest["cases"]["validation"]:
            for name, expected in case["sha256"].items():
                if digest(inside(folder, Path(case["folder"]) / name)) != expected:
                    raise ValueError("A frozen validation input changed")
        records = checked_records(summary, manifest, controller)
        seed = None if controller == "fixed" else training_seed
        rows.extend(aggregate(records, controller, seed))
        for run in records:
            cases.append({"controller": controller, "training_seed": seed, "level": run["level"],
                          "demand_seed": run["demand_seed"], "case_id": run["case_id"],
                          **{key: run["metrics"][key] for key in METRICS}, **run["counts"], "switches": run["switches"]})
    return {"stage": "preliminary_cached_validation", "split": "validation", "training_seed": training_seed,
            "training_seed_repeats": 1, "new_simulations_run": 0, "test_cases_run": 0,
            "aggregation": "Per-case means within each level; J overall is the equally weighted level mean",
            "variability": "Traffic comparison SD/dots concern validation demand cases; learning-return SD concerns trailing same-level episodes. Neither is uncertainty across training seeds.",
            "ATT_scope": "Completed vehicles only; pending and unfinished counts are retained separately",
            "sources": sources, "rows": rows, "cases": cases, "validation_history": histories,
            "training_history": learning}


def plot_report(report, output):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    colors = ("#64748b", "#2563eb", "#ea580c", "#16a34a")
    plot_traffic_metrics(report, output)

    learning = Figure(figsize=(9, 5), dpi=160)
    axis = learning.subplots()
    for controller, label, color in zip(CONTROLLERS[1:], LABELS[1:], colors[1:]):
        values = report["validation_history"][controller]
        axis.plot([value["decisions"] for value in values], [value["J"] for value in values],
                  marker="o", markersize=4, label=label, color=color)
    fixed = statistics.mean(row["J_s_per_due_vehicle"] for row in report["rows"] if row["controller"] == "fixed")
    axis.axhline(fixed, color=colors[0], linestyle="--", label="Fixed-time")
    axis.set(title="Validation learning curves | one training seed", xlabel="Training decisions", ylabel="Equal-level validation J (s / due vehicle)", ylim=(0, None))
    axis.legend(frameon=False)
    axis.grid(alpha=.2)
    learning.tight_layout()
    FigureCanvasAgg(learning).print_png(str(output / "validation_curves.png"))
    plot_learning_curves(report, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs=3, type=Path, default=[Path(f"results/fourphase_dqn/{name}_seed42") for name in ("main", "double", "dueling")])
    parser.add_argument("--fixed-run", type=Path, default=Path("results/fourphase_dqn/pilot_seed42"))
    parser.add_argument("--fixed-summary", type=Path, help="Cached fixed/summary.json; default: latest validation comparison in --fixed-run")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    fixed_run = (ROOT / args.fixed_run).resolve()
    candidates = sorted(fixed_run.glob("comparisons/validation_*/fixed/summary.json"))
    fixed_summary = (ROOT / args.fixed_summary).resolve() if args.fixed_summary else (candidates[-1] if candidates else None)
    if fixed_summary is None:
        parser.error("No cached Fixed-time validation results; provide --fixed-summary")
    report = collect([(ROOT / folder).resolve() for folder in args.runs], fixed_run, fixed_summary)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = (ROOT / args.output).resolve() if args.output else ROOT / "results/fourphase_dqn/reports" / f"preview_seed{report['training_seed']}_{stamp}"
    if not output.is_relative_to(ROOT / "results") or output == ROOT / "results" or output.exists():
        parser.error("Choose a new folder under results/; existing outputs are preserved")
    output.mkdir(parents=True)
    (output / "comparison.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(output / "comparison.csv", report["rows"])
    write_csv(output / "cases.csv", report["cases"])
    for kind, filename in (("episodes", "learning_episodes.csv"), ("updates", "learning_updates.csv")):
        values = [{"controller": controller, **row} for controller, history in report["training_history"].items()
                  for row in history[kind]]
        write_csv(output / filename, values)
    plot_report(report, output)
    print("예비 검증 결과: 학습 시드 1개; 추가 학습·SUMO 실행·독립 테스트 없음")
    for row in report["rows"]:
        att = "N/A" if row["ATT_completed_s"] is None else f"{row['ATT_completed_s']:.2f}"
        print(f"{row['controller']:12} {row['level']:6} J={row['J_s_per_due_vehicle']:.2f} "
              f"ATT={att} AQL={row['AQL_in_vehicles']:.2f} throughput={row['throughput_vehicles']:.1f}")
    print(f"표·원시 결과·그래프 저장: {output}")


if __name__ == "__main__":
    main()
