"""Train the first DQN on immutable training demand; never train on test cases."""

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
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "toy_dqn.json")
    parser.add_argument("--timesteps", type=int, help="Number of agent decisions (default 50000)")
    parser.add_argument("--device", help="Override cpu/cuda/auto")
    parser.add_argument("--output", type=Path, help="New experiment folder inside the project")
    args = parser.parse_args()
    try:
        from stable_baselines3.common.env_checker import check_env
        from stable_baselines3.common.monitor import Monitor
        from src.agents.dqn import create_dqn, read_dqn_config
        from src.agents.plots import plot_training
        from src.agents.training import ToyTrainingCallback
        from src.envs.toy_env import ToyTrafficEnv, read_settings
        from src.traffic.experiments import case_paths, prepare_run, write_json
    except ModuleNotFoundError as error:
        print(f"학습 패키지가 없습니다: {error.name}. requirements-dqn.txt를 설치하세요.", file=sys.stderr)
        return 1

    config = read_dqn_config(args.config, timesteps=args.timesteps, device=args.device)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = (ROOT / (args.output or Path(f"results/dqn/seed_{config['seed']}_{stamp}"))).resolve()
    if not folder.is_relative_to(ROOT):
        parser.error("결과는 프로젝트 폴더 안에 저장해야 합니다")
    settings = read_settings()
    manifest = prepare_run(folder, config, settings)
    first_config, _ = case_paths(folder, manifest["cases"]["train"][0])
    routes = [case_paths(folder, case)[1] for case in manifest["cases"]["train"]]
    env = ToyTrafficEnv(sumo_config=first_config, route_files=routes, settings=settings)
    monitored = None
    callback = None
    model = None
    started = time.monotonic()
    summary = {"status": "running", "requested_timesteps": config["total_timesteps"], "python": platform.python_version()}
    summary["packages"] = {name: importlib.metadata.version(name) for name in (
        "stable-baselines3", "torch", "gymnasium", "numpy", "eclipse-sumo", "matplotlib",
    )}
    write_json(folder / "training_summary.json", summary)
    try:
        print("학습 환경 API와 초기화를 검사합니다.", flush=True)
        check_env(env, warn=True)
        monitored = Monitor(env, filename=str(folder / "monitor.csv"))
        model = create_dqn(monitored, config)
        callback = ToyTrainingCallback(folder, manifest)
        print("학습 시작. 결과:", folder, flush=True)
        model.learn(total_timesteps=config["total_timesteps"], callback=callback, log_interval=5)
        model.save(str(folder / "model.zip"))
        callback.validate()  # Also validate the final optimizer update.
        summary.update(status="completed", best_validation_return=callback.best_score)
    except KeyboardInterrupt:
        summary.update(status="interrupted")
        if model is not None:
            model.save(str(folder / "interrupted_model.zip"))
        print("학습을 중단했습니다.", flush=True)
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
        if monitored is not None:
            monitored.close()
        else:
            env.close()
    plot_training(folder)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if (folder / "training_curve.png").is_file():
        print("학습 곡선:", folder / "training_curve.png")
    if summary["status"] == "completed":
        print("검증에서 선택한 모델:", folder / "best_model.zip")
    elif (folder / "interrupted_model.zip").is_file():
        print("중단 시점 모델:", folder / "interrupted_model.zip")
    return 0 if summary["status"] == "completed" else 130


if __name__ == "__main__":
    raise SystemExit(main())
