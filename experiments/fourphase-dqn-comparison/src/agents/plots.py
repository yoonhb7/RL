"""Standalone figures; imported only by training/evaluation scripts."""

import csv
from pathlib import Path


def plot_training(folder):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    folder = Path(folder)
    if not (folder / "episodes.csv").is_file():
        return
    with (folder / "episodes.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return
    steps = [int(row["global_step"]) for row in rows]
    rewards = [float(row["episode_return"]) for row in rows]
    smoothed = [sum(rewards[max(0, i - 9):i + 1]) / len(rewards[max(0, i - 9):i + 1]) for i in range(len(rewards))]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(steps, rewards, alpha=0.35, label="Episode return")
    ax.plot(steps, smoothed, label="10-episode moving mean")
    ax.set(xlabel="Agent decisions", ylabel="Return (negative halted vehicle-seconds)")
    ax.grid(alpha=0.2)
    ax.legend()
    fig.tight_layout()
    fig.savefig(folder / "training_curve.png", dpi=180)
    fig.savefig(folder / "training_curve.svg")
    plt.close(fig)


def plot_comparison(folder, summary):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    folder = Path(folder)
    labels = ("fixed", "dqn")
    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    axes[0].bar(labels, [summary[k]["waiting_mean_s"] for k in labels],
                yerr=[summary[k]["waiting_std_s"] for k in labels], capsize=5)
    axes[0].set(ylabel="Observed waiting (s / vehicle)", title="Mean and sample standard deviation")
    axes[1].bar(labels, [summary[k]["unfinished_mean"] + summary[k]["pending_mean"] for k in labels])
    axes[1].set(ylabel="Vehicles", title="Unfinished + pending at horizon")
    for ax in axes:
        ax.grid(axis="y", alpha=0.2)
        ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(folder / "comparison.png", dpi=180)
    fig.savefig(folder / "comparison.svg")
    plt.close(fig)
