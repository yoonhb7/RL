"""Frozen-checkpoint, common-input held-out evaluation for the three DQN variants."""

import json
import math
import statistics
import traceback
from datetime import datetime, timezone
from pathlib import Path

from src.agents.fourphase_data import case_path, split_seeds
from src.agents.fourphase_results import (COLORS, CONTROLLERS, LEVELS, METRICS, aggregate,
    case_signature, checked_records, digest, inside, plot_traffic_metrics, read_json, write_csv)
from src.traffic.experiments import write_json


GREEN_FIELDS = ("P0_NS_straight_s", "P1_NS_left_s", "P2_EW_straight_s", "P3_EW_left_s")
SIGNAL_FIELDS = GREEN_FIELDS + ("yellow_s", "all_red_s", "switches")


def prepare_test(run_folders):
    prepared, reference, common_config = [], None, None
    for value in run_folders:
        folder = Path(value).resolve()
        manifest = read_json(folder / "manifest.json")
        config = manifest["config"]
        training = read_json(folder / "training_summary.json")
        selection = read_json(folder / "selection.json")
        algorithm = manifest["algorithm"]
        if algorithm not in CONTROLLERS[1:] or any(item["algorithm"] == algorithm for item in prepared):
            raise ValueError("Provide exactly one run for DQN, Double DQN and pure Dueling")
        if (training["status"] != "completed" or training["algorithm"] != algorithm or
                config["algorithm"] != algorithm or training["seed"] != config["seed"] or
                training["episodes_completed"] != config["episodes"] or
                training["actual_decisions"] != config["episodes"] * 240):
            raise ValueError("Each source must be a completed, full-budget training run")
        shared = {key: value for key, value in config.items() if key != "algorithm"}
        if reference is None:
            reference, common_config = manifest, shared
        if (shared != common_config or manifest["env_settings"] != reference["env_settings"] or
                manifest["network_sha256"] != reference["network_sha256"] or
                manifest["episode_order"] != reference["episode_order"]):
            raise ValueError("Training seed, settings, road and training order must match")
        if (manifest["env_settings"]["duration_seconds"] != 3600 or manifest["observation_size"] != 13 or
                manifest["actions"] != {"0": "hold", "1": "next_phase"}):
            raise ValueError("Use the agreed 3600-second, 13-observation environment")
        seeds = split_seeds(config)
        test_pairs = [(case["level"], case["demand_seed"]) for case in manifest["cases"]["test"]]
        expected = {(level, seed) for level in LEVELS for seed in seeds["test"]}
        if len(seeds["test"]) != 5 or len(test_pairs) != len(expected) or set(test_pairs) != expected:
            raise ValueError("Test cases must be the three levels times five reserved demand seeds")
        other_seeds = {case["demand_seed"] for split in ("train", "validation") for case in manifest["cases"][split]}
        if other_seeds.intersection(seeds["test"]) or any(case["sumo_seed"] != case["demand_seed"] for case in manifest["cases"]["test"]):
            raise ValueError("Held-out demand must be disjoint and use its recorded simulation seed")
        if (case_signature(manifest, "test") != case_signature(reference, "test") or
                case_signature(manifest) != case_signature(reference)):
            raise ValueError("Frozen test or validation inputs differ between models")
        selected_folder = inside(folder, selection["folder"])
        if not selected_folder.is_relative_to(folder / "validation"):
            raise ValueError("Model selection must come from validation, never test")
        model = inside(folder, selection["checkpoint"])
        selected_summary = selected_folder / "summary.json"
        if digest(model) != selection["checkpoint_sha256"] or digest(selected_summary) != selection["validation_summary_sha256"]:
            raise ValueError("Selected checkpoint or validation summary changed")
        validation = read_json(selected_summary)
        if validation["split"] != "validation" or not math.isclose(validation["J_equal_level_mean"], selection["J"], rel_tol=1e-9):
            raise ValueError("Selected score does not match validation")
        checked_records(validation, manifest, algorithm)
        history_path = folder / "validations.jsonl"
        history = [json.loads(line) for line in history_path.read_text().splitlines() if line.strip()]
        if not history or any(not math.isfinite(row["J"]) or row["J"] < 0 for row in history):
            raise ValueError("Invalid validation selection history")
        best = min(history, key=lambda row: (row["J"], row["decisions"]))
        if (best["decisions"] != selection["decisions"] or best["folder"] != selection["folder"] or
                not math.isclose(best["J"], selection["J"], rel_tol=1e-9)):
            raise ValueError("Checkpoint must be the validation minimum, with earliest ties")
        paths = [folder / name for name in ("manifest.json", "training_summary.json", "selection.json", "network.net.xml")]
        paths += [model, selected_summary, history_path]
        if digest(folder / "network.net.xml") != manifest["network_sha256"]:
            raise ValueError("Frozen road changed")
        for case in manifest["cases"]["test"]:
            case_folder = case_path(folder, manifest, case)
            if case["scheduled_due"] <= 0:
                raise ValueError("Every test case needs positive scheduled demand")
            paths.extend(case_folder / name for name in case["sha256"])
        prepared.append({"algorithm": algorithm, "folder": folder, "manifest": manifest,
                         "model": model, "selection": selection,
                         "fingerprints": {str(path): digest(path) for path in paths}})
    if {item["algorithm"] for item in prepared} != set(CONTROLLERS[1:]):
        raise ValueError("All three algorithms are required")
    return sorted(prepared, key=lambda item: CONTROLLERS.index(item["algorithm"]))


def assert_frozen(prepared):
    for item in prepared:
        for path, expected in item["fingerprints"].items():
            if digest(path) != expected:
                raise ValueError(f"Frozen evaluation source changed: {path}")


def protocol_for(prepared):
    source = prepared[0]
    manifest = source["manifest"]
    return {"schema_version": 1, "stage": "preliminary_single_training_seed_test", "split": "test",
            "created_utc": datetime.now(timezone.utc).isoformat(), "training_seed": manifest["config"]["seed"],
            "training_seed_repeats": 1, "controllers": list(CONTROLLERS), "planned_simulations": 60,
            "cases_per_controller": 15, "epsilon": 0., "network_updates": False, "selection_allowed": False,
            "model_selection": "Frozen validation-J minimum; test never selects checkpoints or settings",
            "canonical_input_run": str(source["folder"]), "network_sha256": manifest["network_sha256"],
            "env_settings": manifest["env_settings"], "test_cases": manifest["cases"]["test"],
            "test_demand_seeds": manifest["config"]["test_demand_seeds"],
            "models": [{"algorithm": item["algorithm"], "run": str(item["folder"]), "checkpoint": str(item["model"]),
                        "selection": item["selection"], "fingerprints": item["fingerprints"]} for item in prepared]}


def signal_values(run):
    seconds = run["tls_phase_seconds"]
    if (len(seconds) != 12 or any(isinstance(value, bool) or not math.isfinite(value) or value < 0 for value in seconds)
            or not math.isclose(math.fsum(seconds), run["time_s"], abs_tol=1e-6) or
            type(run["switches"]) is not int or run["switches"] < 0):
        raise ValueError("Invalid signal exposure totals")
    return {**dict(zip(GREEN_FIELDS, seconds[::3])), "yellow_s": sum(seconds[1::3]),
            "all_red_s": sum(seconds[2::3]), "switches": run["switches"]}


def build_comparison(protocol, results):
    if (protocol["split"] != "test" or protocol["selection_allowed"] is not False or
            protocol["cases_per_controller"] != 15 or protocol["planned_simulations"] != 60 or
            len(protocol["test_cases"]) != 15):
        raise ValueError("Use the frozen 15-case held-out test protocol")
    if set(results) != set(CONTROLLERS):
        raise ValueError("All four controllers must finish before comparison")
    manifest = {"env_settings": protocol["env_settings"], "cases": {"test": protocol["test_cases"]}}
    rows, cases, signals = [], [], []
    versions = set()
    for controller in CONTROLLERS:
        summary = results[controller]
        if summary.get("selection_allowed") is not False:
            raise ValueError("Test results must forbid checkpoint selection")
        records = checked_records(summary, manifest, controller, split="test")
        seed = None if controller == "fixed" else protocol["training_seed"]
        rows.extend(aggregate(records, controller, seed))
        for run in records:
            allocation = signal_values(run)
            versions.add(tuple(run["sumo_version"]))
            cases.append({"controller": controller, "training_seed": seed, "level": run["level"],
                          "demand_seed": run["demand_seed"], "case_id": run["case_id"],
                          **{key: run["metrics"][key] for key in METRICS}, **run["counts"], **allocation})
        for level in LEVELS:
            group = [signal_values(run) for run in records if run["level"] == level]
            signals.append({"controller": controller, "level": level, "cases": len(group),
                            **{key: statistics.mean(value[key] for value in group) for key in SIGNAL_FIELDS}})
    if len(versions) != 1:
        raise ValueError("Controllers were evaluated with different SUMO versions")
    improvements = []
    for row in rows:
        if row["controller"] == "fixed":
            continue
        fixed = next(value for value in rows if value["controller"] == "fixed" and value["level"] == row["level"])
        change = {"controller": row["controller"], "level": row["level"]}
        for key in METRICS[:4]:
            before, after = fixed[key], row[key]
            sign = 1 if key == "throughput_vehicles" else -1
            change[f"{key}_improvement_pct"] = sign * 100 * (after - before) / before if before is not None and after is not None and before > 0 else None
        improvements.append(change)
    return {"stage": protocol["stage"], "split": "test", "training_seed": protocol["training_seed"],
            "training_seed_repeats": 1, "selection_allowed": False, "test_cases_run": len(cases),
            "sumo_version": list(next(iter(versions))), "rows": rows, "cases": cases, "signal_rows": signals,
            "improvements": improvements, "controller_summaries": results,
            "J_equal_level_mean": {name: statistics.mean(row["J_s_per_due_vehicle"] for row in rows if row["controller"] == name) for name in CONTROLLERS},
            "interpretation": "One training seed; means/SD/dots describe held-out demand cases, not independent training runs",
            "ATT_scope": "Equal-weight mean of completed-vehicle ATT per demand case; unfinished/pending remain separate",
            "signal_scope": "Total seconds in each phase during the observation window; not average green-interval duration"}


def plot_signal_operation(report, output):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(14, 8), dpi=160)
    axes = figure.subplots(2, 3)
    phase_colors = ("#2563eb", "#60a5fa", "#16a34a", "#86efac", "#eab308", "#dc2626")
    phase_labels = ("NS straight", "NS left", "EW straight", "EW left", "Yellow", "All-red")
    for column, level in enumerate(LEVELS):
        rows = [next(row for row in report["signal_rows"] if row["controller"] == controller and row["level"] == level) for controller in CONTROLLERS]
        bottom = [0.] * 4
        for key, label, color in zip(SIGNAL_FIELDS[:-1], phase_labels, phase_colors):
            values = [row[key] for row in rows]
            axes[0, column].bar(range(4), values, bottom=bottom, color=color, label=label)
            bottom = [a + b for a, b in zip(bottom, values)]
        axes[1, column].bar(range(4), [row["switches"] for row in rows], color=COLORS)
        axes[0, column].set(title=f"{level.capitalize()} demand: signal allocation", ylabel="Mean total seconds / evaluation window")
        axes[1, column].set(title=f"{level.capitalize()} demand: green-phase switches", ylabel="Mean switches / evaluation window", ylim=(0, None))
        for axis in axes[:, column]:
            axis.set_xticks(range(4), ("Fixed", "DQN", "Double", "Dueling"))
            axis.grid(axis="y", alpha=.15)
            axis.set_axisbelow(True)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", ncol=6, frameon=False)
    figure.suptitle("Held-out test | signal operation | one training seed", fontsize=13)
    figure.tight_layout(rect=(0, .045, 1, .95))
    FigureCanvasAgg(figure).print_png(str(output / "signal_operation.png"))


def write_test_report(report, output):
    write_json(output / "comparison.json", report)
    for filename, key in (("comparison.csv", "rows"), ("cases.csv", "cases"),
                          ("signal_operation.csv", "signal_rows"), ("improvement.csv", "improvements")):
        write_csv(output / filename, report[key])
    plot_traffic_metrics(report, output)
    plot_signal_operation(report, output)


def disk_counts(output, protocol):
    expected = {case["id"] for case in protocol["test_cases"]}
    completed = abnormal = 0
    for controller in CONTROLLERS:
        path = output / controller / "summary.json"
        if not path.is_file():
            continue
        seen = set()
        for run in read_json(path).get("runs", []):
            if run["case_id"] not in expected or run["case_id"] in seen:
                continue
            seen.add(run["case_id"])
            if run["status"] == "completed" and run.get("checks") and all(run["checks"].values()):
                completed += 1
            else:
                abnormal += 1
    return {"completed": completed, "abnormal": abnormal, "attempted": completed + abnormal,
            "unattempted": protocol["planned_simulations"] - completed - abnormal}


def run_test(prepared, output, *, policy_factory=None, evaluator=None, reporter=None):
    if policy_factory is None:
        from src.agents.fourphase_dqn import DQNPolicy
        policy_factory = DQNPolicy
    if evaluator is None:
        from src.agents.fourphase_evaluation import evaluate_cases
        evaluator = evaluate_cases
    reporter = write_test_report if reporter is None else reporter
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    protocol = protocol_for(prepared)
    write_json(output / "protocol.json", protocol)  # Written before loading models or starting SUMO.
    state = {"status": "running", "stage": "loading_models", "split": "test", "selection_allowed": False,
             "training_seed": protocol["training_seed"], "planned_simulations": 60,
             "completed": 0, "abnormal": 0, "attempted": 0, "unattempted": 60, "current_controller": None}
    write_json(output / "summary.json", state)
    try:
        assert_frozen(prepared)
        policies = {"fixed": None}
        for item in prepared:
            state["current_controller"] = item["algorithm"]
            policy = policy_factory(item["model"], expected_network_sha256=item["manifest"]["network_sha256"],
                                    expected_settings=item["manifest"]["env_settings"])
            if (policy.algorithm != item["algorithm"] or policy.decisions != item["selection"]["decisions"] or
                    policy.metadata["manifest_sha256"] != item["fingerprints"][str(item["folder"] / "manifest.json")]):
                raise ValueError("Loaded policy differs from the frozen validation-selected run")
            policies[item["algorithm"]] = policy
        results = {}
        source = prepared[0]
        for index, controller in enumerate(CONTROLLERS, 1):
            state.update(stage="evaluation", current_controller=controller)
            write_json(output / "summary.json", state)
            assert_frozen(prepared)
            print(f"[{index}/4] {controller}: test 수요 15개, ε=0, 신경망 업데이트 없음", flush=True)
            results[controller] = evaluator(source["folder"], source["manifest"], "test", output / controller,
                                            policy=policies[controller])
            if results[controller].get("selection_allowed") is not False:
                raise ValueError("Held-out evaluation cannot select checkpoints")
            records = checked_records(results[controller], source["manifest"], controller, split="test")
            for record in records:
                signal_values(record)
            state.update(completed=index * 15, attempted=index * 15, unattempted=60 - index * 15)
            write_json(output / "summary.json", state)
        assert_frozen(prepared)
        state.update(stage="reporting", current_controller=None)
        write_json(output / "summary.json", state)
        report = build_comparison(protocol, results)
        reporter(report, output)
        state.update(status="completed", stage="completed", J_equal_level_mean=report["J_equal_level_mean"])
        write_json(output / "summary.json", state)
        return report
    except BaseException as error:
        state.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else
                     ("report_failed" if state["stage"] == "reporting" else "failed"),
                     error={"type": type(error).__name__, "message": str(error)}, **disk_counts(output, protocol))
        write_json(output / "summary.json", state)
        (output / "traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise


def replot_test(output):
    output = Path(output).resolve()
    protocol = read_json(output / "protocol.json")
    results = {controller: read_json(output / controller / "summary.json") for controller in CONTROLLERS}
    report = build_comparison(protocol, results)
    write_test_report(report, output)
    state = read_json(output / "summary.json")
    state.update(status="completed", stage="completed", current_controller=None, completed=60, attempted=60,
                 abnormal=0, unattempted=0, J_equal_level_mean=report["J_equal_level_mean"], error=None)
    write_json(output / "summary.json", state)
    return report
