"""Run one local headless episode without DQN and record the transitions."""

import argparse
import json
import sys
from datetime import datetime, timezone

from common import ROOT

sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--policy", choices=("random", "hold", "switch"), default="random")
    parser.add_argument("--check-api", action="store_true", help="Also run Gymnasium's environment checker")
    args = parser.parse_args()
    try:
        from src.envs.toy_env import ToyTrafficEnv
    except ModuleNotFoundError as error:
        print(f"패키지가 없습니다: {error.name}. .venv/bin/python -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "results" / "env" / f"headless_seed_{args.seed}_{stamp}"
    env = ToyTrafficEnv()
    try:
        if args.check_api:
            from gymnasium.utils.env_checker import check_env
            check_env(env, skip_render_check=True)
        observation, info = env.reset(seed=args.seed)
        output.mkdir(parents=True, exist_ok=False)
        with (output / "transitions.jsonl").open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"event": "reset", "observation": observation.tolist(), "info": info}) + "\n")
            while True:
                action = int(env.action_space.sample()) if args.policy == "random" else int(args.policy == "switch")
                next_observation, reward, terminated, truncated, info = env.step(action)
                if not env.observation_space.contains(next_observation):
                    raise RuntimeError("관측값이 observation_space 범위를 벗어났습니다")
                handle.write(json.dumps({
                    "event": "transition", "observation": observation.tolist(), "action": action, "reward": reward,
                    "next_observation": next_observation.tolist(), "terminated": terminated, "truncated": truncated, "info": info,
                }) + "\n")
                observation = next_observation
                if terminated or truncated:
                    break
        report = {"policy": args.policy, "seed": args.seed, "terminated": terminated, "truncated": truncated,
                  "sumo_version": env.connection.getVersion(), "settings": env.settings, "final_info": info}
        (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("결과:", output)
    finally:
        env.close()


if __name__ == "__main__":
    main()
