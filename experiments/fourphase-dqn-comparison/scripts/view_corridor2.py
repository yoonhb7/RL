"""Drive the Mac corridor2 GUI from the Linux fixed/queue/DQN console."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from common import ROOT

sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18813)
    parser.add_argument("--controller", choices=("fixed", "queue", "dqn"), default="queue")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--controller-file", type=Path, default=Path("src/traffic/corridor_controller.py"))
    parser.add_argument("--scenario", type=Path, default=Path("sumo/corridor2"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--delay", type=float, default=0.1)
    args = parser.parse_args()
    import traci
    from src.envs.corridor_env import CorridorTrafficEnv
    from src.envs.toy_console import ToyEnvSession
    from src.traffic.corridor import read_scenario
    from src.traffic.corridor_gui import CorridorGui
    from src.traffic.live_session import load_controller, run_console

    if args.controller == "dqn" and args.model is None:
        parser.error("--controller dqn requires --model")
    if args.model is not None and args.controller != "dqn":
        parser.error("--model requires --controller dqn")
    controller_path = (ROOT / (args.model or args.controller_file)).resolve()
    if not controller_path.is_relative_to(ROOT):
        parser.error("Controller/model must stay inside this project")
    if args.controller == "dqn":
        from src.agents.dqn import DQNController
        manifest = json.loads((controller_path.parent / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("kind") != "synthetic_corridor2":
            parser.error("Use a corridor2 model, not the previous single-junction model")
        settings = manifest["env_settings"]

        def loader(path):
            from stable_baselines3 import DQN
            model = DQN.load(str(path), device="cpu")
            if model.observation_space.shape != (31,) or model.action_space.n != 4:
                raise ValueError("Expected 31 observations and 4 actions")
            return DQNController(model), "dqn:" + hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    else:
        settings = read_scenario((ROOT / args.scenario).resolve())

        def loader(path):
            if args.controller == "queue":
                return load_controller(path, "choose_action")
            return SimpleNamespace(choose_action=lambda observation, info: 0), "fixed"
    connection = env = None
    try:
        connection = traci.connect(host=args.host, port=args.port, numRetries=3)
        presentation = CorridorGui(connection, controller=args.controller.upper())
        env = CorridorTrafficEnv(connection=connection, settings=settings, wall_delay=args.delay,
                                 control_mode="fixed" if args.controller == "fixed" else "agent", observer=presentation)
        session = ToyEnvSession(env, controller_path, seed=args.seed, controller_loader=loader, presentation=presentation)
        print("연결 완료. sumo>에서 resume / action 0–3 / view A / view B / help")
        session.print_status()
        run_console(session)
    finally:
        if env is not None:
            env.close()
        if connection is not None:
            try:
                connection.close(wait=False)
            except (traci.TraCIException, traci.FatalTraCIError, OSError):
                pass


if __name__ == "__main__":
    main()
