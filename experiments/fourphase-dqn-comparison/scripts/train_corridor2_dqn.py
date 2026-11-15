"""Train one central DQN on synthetic corridor cases, using validation only for selection."""

import argparse
import importlib.metadata
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT

sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("sumo/corridor2"))
    parser.add_argument("--config", type=Path, default=ROOT / "configs/corridor2_dqn.json")
    parser.add_argument("--profiles", nargs="+", help="Override the selected traffic profiles")
    parser.add_argument("--timesteps", type=int)
    parser.add_argument("--seed", type=int, help="Network/exploration seed; demand seed splits stay fixed")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    from stable_baselines3.common.env_checker import check_env
    from stable_baselines3.common.monitor import Monitor
    from src.agents.corridor_evaluation import run_episode
    from src.agents.dqn import create_dqn, read_dqn_config
    from src.agents.plots import plot_training
    from src.agents.training import ToyTrainingCallback
    from src.envs.corridor_env import CorridorTrafficEnv
    from src.traffic.corridor import prepare_run
    from src.traffic.experiments import case_paths, write_json

    config = read_dqn_config(args.config, timesteps=args.timesteps, device=args.device)
    if args.seed is not None:
        if args.seed < 0:
            parser.error("seed must be nonnegative")
        config["seed"] = args.seed
    profiles = args.profiles or config["profiles"]
    if len(set(profiles)) != len(profiles):
        parser.error("profiles must be unique")
    config["profiles"] = profiles
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = (ROOT / (args.output or Path(f"results/corridor2/seed_{config['seed']}_{stamp}"))).resolve()
    source = (ROOT / args.scenario).resolve()
    if not folder.is_relative_to(ROOT / "results") or not source.is_relative_to(ROOT):
        parser.error("Scenario/output must stay inside this project, with output under results/")
    manifest = prepare_run(folder, source, config, profiles)
    first_config, _ = case_paths(folder, manifest["cases"]["train"][0])
    routes = [case_paths(folder, case)[1] for case in manifest["cases"]["train"]]
    env = CorridorTrafficEnv(sumo_config=first_config, route_files=routes, settings=manifest["env_settings"])
    monitor = callback = model = None
    started = time.monotonic()
    summary = {"status": "running", "requested_timesteps": config["total_timesteps"], "seed": config["seed"],
               "python": platform.python_version(), "profiles": profiles,
               "packages": {name: importlib.metadata.version(name) for name in
                            ("stable-baselines3", "torch", "gymnasium", "numpy", "eclipse-sumo")}}
    write_json(folder / "training_summary.json", summary)
    try:
        check_env(env, warn=True)
        monitor = Monitor(env, filename=str(folder / "monitor.csv"))
        model = create_dqn(monitor, config)
        callback = ToyTrainingCallback(folder, manifest, episode_runner=run_episode)
        print(f"학습 시작: {folder}\n관측 31개 / 공동 행동 4개 / profile={profiles}", flush=True)
        model.learn(total_timesteps=config["total_timesteps"], callback=callback, log_interval=5)
        model.save(str(folder / "model.zip"))
        callback.validate()
        summary.update(status="completed", best_validation_return=callback.best_score)
    except KeyboardInterrupt:
        summary["status"] = "interrupted"
        if model is not None:
            model.save(str(folder / "interrupted_model.zip"))
    except Exception as error:
        summary.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        if model is not None:
            summary.update(actual_timesteps=model.num_timesteps, optimizer_updates=model._n_updates)
        summary["elapsed_wall_seconds"] = time.monotonic() - started
        write_json(folder / "training_summary.json", summary)
        if callback is not None:
            callback.close()
        if monitor is not None:
            monitor.close()
        else:
            env.close()
    plot_training(folder)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["status"] == "completed" else 130


if __name__ == "__main__":
    raise SystemExit(main())
