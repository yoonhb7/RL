"""Display RL1114 city graphics on Mac SUMO through the existing reverse tunnel."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT

sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18813)
    parser.add_argument("--delay", type=float, default=0.07)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    import traci
    from src.traffic.live_session import run_console
    from src.traffic.rl1114_scene.session import CityViewSession

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = (ROOT / (args.output or Path(f"results/rl1114_city/view_{stamp}"))).resolve()
    if not output.is_relative_to(ROOT / "results") or output.exists():
        parser.error("Choose a new output folder under results/")
    connection = None
    try:
        connection = traci.connect(host=args.host, port=args.port, numRetries=3)
        session = CityViewSession(connection, output, delay=args.delay)
        print("RL1114 도시 화면 연결 완료. 기본 고정신호 시연이며 학습하지 않습니다.")
        print("sumo>에서 resume / pause / reset / level high / view junction / help")
        session.print_status()
        run_console(session)
    except (traci.FatalTraCIError, OSError) as error:
        print(f"연결 오류: {error}\nMac SSH 터널과 --remote-port 8813인 SUMO를 확인하세요.", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            try:
                connection.close(wait=False)
            except (traci.TraCIException, traci.FatalTraCIError, OSError):
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
