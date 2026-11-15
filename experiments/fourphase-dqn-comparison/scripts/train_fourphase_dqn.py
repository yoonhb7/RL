"""Train masked DQN, Double DQN or pure Dueling; execution is initiated by the user."""

import argparse
import importlib.metadata
import json
import platform
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT

sys.path.insert(0, str(ROOT))
from src.agents.fourphase_data import ALGORITHMS, case_path, prepare_run, read_config
from src.agents.fourphase_dqn import DQNAgent
from src.agents.fourphase_evaluation import evaluate_cases, run_episode
from src.traffic.experiments import sha256, write_json


def plot_curves(folder):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    episodes = [json.loads(line) for line in (folder / "episodes.jsonl").read_text().splitlines()]
    updates = [json.loads(line) for line in (folder / "updates.jsonl").read_text().splitlines()]
    validations = [json.loads(line) for line in (folder / "validations.jsonl").read_text().splitlines()]
    fig = Figure(figsize=(12, 3.8), dpi=150)
    axes = fig.subplots(1, 3)
    axes[0].plot([e["global_decisions"] for e in episodes], [e["mean_R1"] for e in episodes], marker=".")
    axes[0].set(title="Training: mean R1 per episode", xlabel="Decisions", ylabel="Reward")
    losses = [u for u in updates if u["loss"] is not None]
    axes[1].plot([u["decision"] for u in losses], [u["loss"] for u in losses], alpha=.6, linewidth=.6)
    axes[1].set(title="Huber loss", xlabel="Decisions", ylabel="Loss")
    axes[2].plot([v["decisions"] for v in validations], [v["J"] for v in validations], marker="o")
    axes[2].set(title="Validation J (lower is better)", xlabel="Decisions", ylabel="s / due vehicle")
    fig.tight_layout()
    FigureCanvasAgg(fig).print_png(str(folder / "training.png"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("sumo/fourphase"))
    parser.add_argument("--config", type=Path, default=ROOT / "configs/fourphase_dqn.json")
    parser.add_argument("--episodes", type=int)
    parser.add_argument("--algorithm", choices=ALGORITHMS, help="Default: dqn; dueling_dqn is pure Dueling, without Double targets")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--device")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = read_config(args.config, episodes=args.episodes, seed=args.seed, device=args.device, algorithm=args.algorithm)
    budget = config["episodes"] * 240
    if budget <= config["learning_starts"]:
        parser.error("Use enough full episodes to perform updates after the initial 1000 decisions")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = (ROOT / (args.output or Path(f"results/fourphase_dqn/{config['algorithm']}_seed_{config['seed']}_{stamp}"))).resolve()
    source = (ROOT / args.scenario).resolve()
    if not folder.is_relative_to(ROOT / "results") or folder == ROOT / "results" or not source.is_relative_to(ROOT / "sumo"):
        parser.error("Use a project SUMO scenario and a new output folder under results/")
    agent = DQNAgent(config, budget)
    manifest = prepare_run(folder, source, config)
    metadata = {"env_settings": manifest["env_settings"], "network_sha256": manifest["network_sha256"],
                "manifest_sha256": sha256(folder / "manifest.json"), "episodes_completed": 0,
                "observation_size": 13, "action_count": 2, "selection": None}
    summary = {"status": "running", "algorithm": config["algorithm"], "seed": config["seed"], "requested_episodes": config["episodes"],
               "planned_decisions": budget, "episodes_completed": 0, "best_validation_J": None,
               "python": platform.python_version(), "packages": {name: importlib.metadata.version(name) for name in
                    ("torch", "numpy", "gymnasium", "traci", "eclipse-sumo")},
               "parameter_count": sum(p.numel() for p in agent.online.parameters()),
               "test_cases_run": 0, "training_level_counts": manifest["training_level_counts"],
               "epsilon_reaches_final_at_decision": budget * config["epsilon_fraction"]}
    write_json(folder / "training_summary.json", summary)
    started = time.monotonic()
    best = float("inf")
    current_case = None
    print(f"{config['algorithm']} 학습 시작: {folder}\n{config['episodes']} episodes / {budget} decisions / R1 / validation J", flush=True)
    print("학습은 Linux headless SUMO를 사용합니다. Mac SUMO와 SSH 터널은 필요 없습니다.", flush=True)
    with (folder / "transitions.jsonl").open("w", encoding="utf-8") as transitions, \
         (folder / "updates.jsonl").open("w", encoding="utf-8") as updates, \
         (folder / "episodes.jsonl").open("w", encoding="utf-8") as episodes_log, \
         (folder / "validations.jsonl").open("w", encoding="utf-8") as validations:
        try:
            for case in manifest["cases"]["train"]:
                current_case = case["id"]
                losses = []

                def observe(state, info, action, reward, next_state, next_info, terminated, truncated):
                    used_epsilon = 1.0 if agent.decisions < config["learning_starts"] else agent.epsilon
                    update = agent.observe(state, action, reward, next_state, terminated, truncated, next_info["action_mask"])
                    update.update(episode=case["episode"], level=case["level"])
                    updates.write(json.dumps(update) + "\n")
                    if update["loss"] is not None:
                        losses.append(update["loss"])
                    transitions.write(json.dumps({"decision": agent.decisions, "episode": case["episode"],
                        "case_id": case["id"], "state": state.tolist(), "action_mask": info["action_mask"].tolist(),
                        "action": action, "reward": reward, "next_state": next_state.tolist(), "terminated": terminated,
                        "truncated": truncated, "next_action_mask": next_info["action_mask"].tolist(),
                        "time_s": next_info["time_s"], "epsilon_used": used_epsilon}) + "\n")

                result = run_episode(case_path(folder, manifest, case), case, manifest["env_settings"],
                    folder / "episodes" / current_case, policy=agent, training=True, on_transition=observe)
                number = case["episode"]
                metadata["episodes_completed"] = summary["episodes_completed"] = number
                row = {"episode": number, "level": case["level"], "demand_seed": case["demand_seed"],
                       "global_decisions": agent.decisions, "optimizer_updates": agent.updates,
                       "target_copies": agent.target_copies, "epsilon": agent.epsilon,
                       "replay_size": agent.replay.size, "raw_reward_sum": result["raw_reward_sum"],
                       "mean_R1": result["raw_reward_sum"] / result["decision_count"],
                       "mean_loss": sum(losses) / len(losses) if losses else None, "metrics": result["metrics"],
                       "checks": result["checks"]}
                episodes_log.write(json.dumps(row) + "\n")
                for stream in (episodes_log, updates, transitions):
                    stream.flush()
                agent.save(folder / "last_model.pt", metadata)
                print(f"episode {number}/{config['episodes']} {case['level']} | decisions={agent.decisions} "
                      f"updates={agent.updates} epsilon={agent.epsilon:.3f} mean_R1={row['mean_R1']:.3f} "
                      f"J={result['metrics']['J_s_per_due_vehicle']:.3f}", flush=True)
                if number % config["validation_every_episodes"] == 0 or number == config["episodes"]:
                    relative = Path("validation") / f"step_{agent.decisions:06d}"
                    current_case = str(relative)
                    print("독립 검증 수요 9개에서 ε=0으로 평가합니다.", flush=True)
                    validation = evaluate_cases(folder, manifest, "validation", folder / relative, policy=agent)
                    score = validation["J_equal_level_mean"]
                    selected = score < best
                    validation_row = {"episode": number, "decisions": agent.decisions, "J": score,
                                      "J_by_level": validation["J_by_level"], "selected": selected, "folder": str(relative)}
                    validations.write(json.dumps(validation_row) + "\n")
                    validations.flush()
                    if selected:
                        best = score
                        metadata["selection"] = validation_row
                        agent.save(folder / "best_model.pt", metadata)
                        write_json(folder / "selection.json", {**validation_row, "checkpoint": "best_model.pt",
                            "checkpoint_sha256": sha256(folder / "best_model.pt"),
                            "validation_summary_sha256": sha256(folder / relative / "summary.json"),
                            "criterion": "minimum validation J only; earliest checkpoint on ties"})
                        summary.update(best_validation_J=score, best_validation_decisions=agent.decisions,
                                       selected_checkpoint="best_model.pt")
                    print(f"validation J={score:.3f}, best={best:.3f}", flush=True)
                write_json(folder / "training_summary.json", {**summary, "actual_decisions": agent.decisions,
                           "optimizer_updates": agent.updates, "elapsed_wall_seconds": time.monotonic() - started})
            summary["status"] = "completed"
        except KeyboardInterrupt:
            summary["status"] = "interrupted"
            agent.save(folder / "interrupted_model.pt", metadata)
        except Exception as error:
            summary.update(status="failed", error=f"{type(error).__name__}: {error}", failed_case=current_case)
            agent.save(folder / "failed_model.pt", metadata)
            (folder / "traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
            print(f"학습 중단: {summary['error']}\n기록: {folder / 'traceback.txt'}", file=sys.stderr, flush=True)
        finally:
            summary.update(actual_decisions=agent.decisions, optimizer_updates=agent.updates,
                           target_copies=agent.target_copies, replay_size=agent.replay.size,
                           elapsed_wall_seconds=time.monotonic() - started)
            write_json(folder / "training_summary.json", summary)
    if summary["status"] == "completed":
        try:
            plot_curves(folder)
        except Exception as error:
            summary["plot_error"] = str(error)
            write_json(folder / "training_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return {"completed": 0, "interrupted": 130, "failed": 1}[summary["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
