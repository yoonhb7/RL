"""Offline learning curves from saved episode and optimizer logs; no model loading."""

import json
import math
import statistics
from collections import deque


LEVELS = ("low", "medium", "high")
ALGORITHMS = ("dqn", "double_dqn", "dueling_dqn")
LABELS = ("DQN", "Double DQN", "Dueling DQN")
COLORS = ("#2563eb", "#ea580c", "#16a34a")


def finite(value, name):
    if isinstance(value, bool) or value is None or not math.isfinite(value):
        raise ValueError(f"Non-finite learning log value: {name}")
    return value


def reward_series(episodes, window=10):
    if type(window) is not int or window < 2:
        raise ValueError("Reward window must be at least two episodes")
    histories = {level: deque(maxlen=window) for level in LEVELS}
    result = []
    previous_decision = 0
    for index, episode in enumerate(episodes, 1):
        if episode["episode"] != index or episode["global_decisions"] <= previous_decision:
            raise ValueError("Episode logs must be complete and ordered")
        if episode["level"] not in histories or not episode["checks"] or not all(v is True for v in episode["checks"].values()):
            raise ValueError("Invalid or failed training episode")
        previous_decision = episode["global_decisions"]
        row = {key: episode[key] for key in ("episode", "level", "global_decisions", "raw_reward_sum",
               "mean_R1", "epsilon", "replay_size", "optimizer_updates")}
        for key in ("raw_reward_sum", "mean_R1", "epsilon"):
            finite(row[key], key)
        history = histories[row["level"]]
        history.append(row["raw_reward_sum"])
        row["return_ma"] = statistics.mean(history)
        # An incomplete initial window is not a zero-variance result.
        row["return_sd"] = statistics.stdev(history) if len(history) == window else None
        row["window_episodes"] = len(history)
        result.append(row)
    return result


def percentile90(values):
    ordered = sorted(values)
    position = .9 * (len(ordered) - 1)
    lower = math.floor(position)
    return ordered[lower] + (ordered[math.ceil(position)] - ordered[lower]) * (position - lower)


def update_series(updates, learning_starts, bin_size=500):
    if type(bin_size) is not int or bin_size < 1:
        raise ValueError("Decision bin size must be positive")
    bins, exploration = [], []
    losses, q_values, targets = [], [], []
    previous_epsilon, previous_decision, update_count = 1., 0, 0
    first, last = None, None

    def flush():
        if last is None:
            return
        bins.append({"decision_first": first, "decision_last": last["decision"],
                     "updates_in_bin": len(losses),
                     "loss_mean": statistics.mean(losses) if losses else None,
                     "loss_p90": percentile90(losses) if losses else None,
                     "mean_q": statistics.mean(q_values) if q_values else None,
                     "mean_target": statistics.mean(targets) if targets else None,
                     "epsilon_after_decision": last["epsilon"], "replay_size": last["replay_size"],
                     "optimizer_updates": last["optimizer_updates"]})

    for row in updates:
        decision = row["decision"]
        if decision != previous_decision + 1:
            raise ValueError("Optimizer logs have missing or duplicate decisions")
        if last is not None and (decision - 1) // bin_size != (last["decision"] - 1) // bin_size:
            flush()
            losses, q_values, targets = [], [], []
            first = None
        if first is None:
            first = decision
        epsilon = finite(row["epsilon"], "epsilon")
        if not 0 <= epsilon <= 1:
            raise ValueError("Invalid epsilon")
        # The update log stores epsilon AFTER each decision. Behavior used the
        # previous schedule value, except for uniform initial collection.
        behavior_epsilon = 1. if decision <= learning_starts else previous_epsilon
        if decision % 100 == 0 or decision in (1, learning_starts, learning_starts + 1):
            exploration.append({"decision": decision, "behavior_epsilon": behavior_epsilon})
        if row["loss"] is not None:
            loss = finite(row["loss"], "loss")
            if loss < 0:
                raise ValueError("Huber loss cannot be negative")
            losses.append(loss)
            q_values.append(finite(row["mean_q"], "mean_q"))
            targets.append(finite(row["mean_target"], "mean_target"))
            update_count += 1
        if row["optimizer_updates"] != update_count:
            raise ValueError("Optimizer update counter differs from logged losses")
        last, previous_decision, previous_epsilon = row, decision, epsilon
    flush()
    if last is not None and (not exploration or exploration[-1]["decision"] != last["decision"]):
        exploration.append({"decision": last["decision"], "behavior_epsilon": behavior_epsilon})
    return bins, exploration


def load_learning_logs(folder, config, summary, *, window=10, bin_size=500):
    with (folder / "episodes.jsonl").open(encoding="utf-8") as stream:
        episodes = reward_series((json.loads(line) for line in stream if line.strip()), window)
    with (folder / "updates.jsonl").open(encoding="utf-8") as stream:
        updates, exploration = update_series((json.loads(line) for line in stream if line.strip()),
                                              config["learning_starts"], bin_size)
    if not episodes or not updates or len(episodes) != config["episodes"]:
        raise ValueError("Training learning curves require the complete episode log")
    if (episodes[-1]["global_decisions"] != updates[-1]["decision_last"] or
            updates[-1]["decision_last"] != summary["actual_decisions"] or
            updates[-1]["optimizer_updates"] != summary["optimizer_updates"]):
        raise ValueError("Learning log counters differ from the completed training summary")
    return {"reward_window": window, "update_bin_decisions": bin_size,
            "warmup_decisions": config["learning_starts"], "episodes": episodes,
            "updates": updates, "exploration": exploration,
            "variability": "Trailing sample SD of same-level episode returns within one learning run; not a confidence interval"}


def plot_learning_curves(report, output):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    histories = report["training_history"]
    window = histories[ALGORITHMS[0]]["reward_window"]
    reward = Figure(figsize=(14, 8), dpi=160)
    axes = reward.subplots(2, 3, sharex=True)
    for column, level in enumerate(LEVELS):
        for algorithm, label, color in zip(ALGORITHMS, LABELS, COLORS):
            values = [row for row in histories[algorithm]["episodes"] if row["level"] == level]
            x = [row["episode"] for row in values]
            axes[0, column].scatter(x, [row["raw_reward_sum"] for row in values], s=10, color=color, alpha=.18)
            axes[0, column].plot(x, [row["return_ma"] for row in values], label=label, color=color, linewidth=1.7)
            full = [row for row in values if row["return_sd"] is not None]
            axes[1, column].plot([row["episode"] for row in full], [row["return_sd"] for row in full], color=color)
        axes[0, column].set(title=f"{level.capitalize()} demand | episode return", ylabel="Sum of R1 (higher is better)")
        axes[1, column].set(title=f"{level.capitalize()} demand | local variability", xlabel="Training episode", ylabel="Trailing return SD", ylim=(0, None))
    for axis in axes.flat:
        axis.grid(alpha=.2)
    reward.suptitle(f"Learning curves | training seed {report['training_seed']}\nDots: raw returns; lines: trailing {window} same-demand-level episodes", fontsize=13)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    reward.legend(handles, labels, loc="lower center", ncol=3, frameon=False)
    reward.text(.5, .045, "SD describes local variability within one run, not uncertainty across training seeds.", ha="center", fontsize=9)
    reward.tight_layout(rect=(0, .075, 1, .92))
    FigureCanvasAgg(reward).print_png(str(output / "learning_curves.png"))

    diagnostic = Figure(figsize=(13, 8), dpi=160)
    axes = diagnostic.subplots(2, 2, sharex=True)
    for algorithm, label, color in zip(ALGORITHMS, LABELS, COLORS):
        data = histories[algorithm]
        trained = [row for row in data["updates"] if row["loss_mean"] is not None]
        x = [row["decision_last"] for row in trained]
        axes[0, 0].plot(x, [row["loss_mean"] for row in trained], color=color, label=label)
        axes[0, 0].plot(x, [row["loss_p90"] for row in trained], color=color, linestyle="--", alpha=.55)
        axes[0, 1].plot(x, [row["mean_q"] for row in trained], color=color)
        axes[0, 1].plot(x, [row["mean_target"] for row in trained], color=color, linestyle="--", alpha=.6)
        axes[1, 0].plot([row["decision"] for row in data["exploration"]],
                        [row["behavior_epsilon"] for row in data["exploration"]], color=color)
        axes[1, 1].plot([row["decision_last"] for row in data["updates"]], [row["replay_size"] for row in data["updates"]], color=color)
        axes[1, 1].plot([row["decision_last"] for row in data["updates"]], [row["optimizer_updates"] for row in data["updates"]], color=color, linestyle="--", alpha=.6)
    axes[0, 0].set(title="Huber loss: mean / 90th percentile", ylabel="Optimizer batch loss", ylim=(0, None))
    axes[0, 1].set(title="Replay-batch mean Q / TD target", ylabel="Value (logged batch averages)")
    axes[1, 0].set(title="Behavior exploration epsilon", xlabel="Training decisions", ylabel="Epsilon", ylim=(0, 1.05))
    axes[1, 1].set(title="Replay size / optimizer updates", xlabel="Training decisions", ylabel="Count", ylim=(0, None))
    warmup = histories[ALGORITHMS[0]]["warmup_decisions"]
    for axis in axes.flat:
        axis.axvspan(0, warmup, color="#94a3b8", alpha=.15)
        axis.grid(alpha=.2)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    diagnostic.legend(handles, labels, loc="lower center", ncol=3, frameon=False)
    diagnostic.suptitle(f"Training diagnostics | {histories[ALGORITHMS[0]]['update_bin_decisions']}-decision bins | one training seed", fontsize=13)
    diagnostic.text(.5, .055, "Solid/dashed: mean/p90 loss, Q/target, replay/updates. Shaded start: uniform collection, no learning.", ha="center", fontsize=9)
    diagnostic.text(.5, .035, "Overlapping epsilon and progress curves are expected under the shared training schedule.", ha="center", fontsize=9)
    diagnostic.tight_layout(rect=(0, .09, 1, .94))
    FigureCanvasAgg(diagnostic).print_png(str(output / "training_diagnostics.png"))

    validation = Figure(figsize=(14, 4.8), dpi=160)
    axes = validation.subplots(1, 3)
    for axis, level in zip(axes, LEVELS):
        for algorithm, label, color in zip(ALGORITHMS, LABELS, COLORS):
            values = report["validation_history"][algorithm]
            axis.plot([row["decisions"] for row in values], [row["J_by_level"][level] for row in values],
                      color=color, marker="o", markersize=3, label=label)
            chosen = next(row for row in values if row["decisions"] == histories[algorithm]["selected_decisions"])
            axis.scatter(chosen["decisions"], chosen["J_by_level"][level], marker="*", s=100, color=color, zorder=3)
        fixed = next(row["J_s_per_due_vehicle"] for row in report["rows"] if row["controller"] == "fixed" and row["level"] == level)
        axis.axhline(fixed, color="#64748b", linestyle="--", label="Fixed-time")
        axis.set(title=f"{level.capitalize()} demand", xlabel="Training decisions", ylabel="Validation J (lower is better)", ylim=(0, None))
        axis.grid(alpha=.2)
    handles, labels = axes[0].get_legend_handles_labels()
    validation.legend(handles, labels, loc="lower center", ncol=4, frameon=False)
    validation.suptitle("Greedy validation | fixed demand cases | stars: selected checkpoint | one training seed", fontsize=12)
    validation.tight_layout(rect=(0, .07, 1, .92))
    FigureCanvasAgg(validation).print_png(str(output / "validation_by_level.png"))
