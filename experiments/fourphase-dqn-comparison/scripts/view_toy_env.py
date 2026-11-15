"""Inspect Gymnasium state/action/reward in the Mac SUMO window."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT

sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18813)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--warmup", type=int, help="Override warm-up (default: configs/toy.json)")
    parser.add_argument("--delay", type=float, default=0.1)
    parser.add_argument("--mac-config", help="Config path on Mac, normally detected automatically")
    parser.add_argument("--model", type=Path, help="Saved DQN .zip; loads its frozen environment settings")
    parser.add_argument("--output", type=Path, help="New result folder inside the project")
    parser.add_argument("--no-visuals", action="store_true", help="Disable the custom road scene")
    args = parser.parse_args()
    try:
        import traci
        from src.envs.toy_console import ToyEnvSession
        from src.envs.toy_env import ToyTrafficEnv
        from src.traffic.live_session import run_console
    except ModuleNotFoundError as error:
        print(f"필요한 패키지가 없습니다: {error.name}. .venv/bin/python -m pip install -r requirements.txt", file=sys.stderr)
        return 1

    controller_path = ROOT / "src" / "traffic" / "live_controller.py"
    controller_loader = None
    settings = {} if args.warmup is None else {"warmup_seconds": args.warmup}
    if args.model:
        from src.agents.dqn import load_dqn_controller, model_env_settings
        controller_path = (ROOT / args.model).resolve()
        settings = model_env_settings(controller_path)
        if args.warmup is not None and args.warmup != settings["warmup_seconds"]:
            parser.error("모델 확인에는 학습과 같은 Warm-up을 사용해야 합니다. --warmup 옵션을 빼세요")
        controller_loader = load_dqn_controller

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = (ROOT / (args.output or Path(f"results/env/mac_seed_{args.seed}_{stamp}"))).resolve()
    if not output.is_relative_to(ROOT):
        parser.error("출력 폴더는 프로젝트 안에 있어야 합니다")
    if output.exists() and any(output.iterdir()):
        parser.error("결과 폴더가 비어 있지 않습니다. 새 --output을 지정하세요")
    connection = None
    env = None
    try:
        connection = traci.connect(host=args.host, port=args.port, numRetries=3)
        presentation = None
        if not args.no_visuals:
            from src.traffic.gui_presentation import ToyGuiPresentation
            presentation = ToyGuiPresentation(connection, controller="DQN" if args.model else "RULE")
        env = ToyTrafficEnv(connection=connection, remote_config=args.mac_config, settings=settings,
                            wall_delay=args.delay, observer=presentation)
        output.mkdir(parents=True, exist_ok=True)
        print("Mac 연결 성공:", connection.getVersion(), flush=True)
        print(f"환경 초기화와 Warm-up {env.warmup}초를 진행합니다.", flush=True)
        with (output / "transitions.jsonl").open("w", encoding="utf-8") as handle:
            def record(event):
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                handle.flush()

            (output / "settings.json").write_text(json.dumps(env.settings, indent=2) + "\n", encoding="utf-8")
            record({"event": "metadata", "sumo_version": connection.getVersion(), "settings": env.settings})
            session = ToyEnvSession(env, controller_path, seed=args.seed, record=record,
                                    controller_loader=controller_loader, presentation=presentation)
            print("제어 코드/모델:", controller_path, flush=True)
            print("연결 유지·일시정지 상태입니다. action 0, action 1, status, resume, help를 입력하세요.", flush=True)
            print("기록:", output / "transitions.jsonl", flush=True)
            session.print_status()
            run_console(session)
    except KeyboardInterrupt:
        print("초기 연결/환경 준비를 취소했습니다.", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"실행 오류: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    finally:
        if env is not None:
            env.close()
        if connection is not None:
            try:
                connection.close(wait=False)
            except (OSError, traci.exceptions.TraCIException):
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
