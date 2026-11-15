"""Keep the Mac SUMO connection open while reloading the signal controller."""

import argparse
import math
import sys

from common import ROOT

sys.path.insert(0, str(ROOT))

import traci
from src.traffic.live_session import LiveSession, run_console


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18813)
    parser.add_argument("--delay", type=float, default=0.1, help="Wall-clock seconds between steps")
    parser.add_argument("--end", type=float, default=1200, help="Pause at this simulation time; keep connected")
    parser.add_argument("--mac-config", help="SUMO configuration path on the Mac (normally detected automatically)")
    args = parser.parse_args()
    if not math.isfinite(args.delay) or args.delay < 0:
        parser.error("--delay must be a finite nonnegative number")
    if not math.isfinite(args.end) or args.end <= 0:
        parser.error("--end must be a finite positive number")

    connection = None
    try:
        connection = traci.connect(host=args.host, port=args.port, numRetries=3)
        session = LiveSession(
            connection, ROOT / "src" / "traffic" / "live_controller.py",
            end=args.end, delay=args.delay, mac_config=args.mac_config,
        )
        print("Mac SUMO 연결 성공:", connection.getVersion(), flush=True)
        print("연결을 유지한 채 일시정지 중입니다. help 또는 resume을 입력하세요.", flush=True)
        print("수정할 파일:", session.controller_path, flush=True)
        session.print_status()
        run_console(session)
    except KeyboardInterrupt:
        print("연결 준비를 취소했습니다.", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"실행 오류: {type(error).__name__}: {error}", file=sys.stderr)
        print("SSH 터널과 Mac SUMO의 --remote-port 8813 --start 실행 상태를 확인하세요.", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            try:
                connection.close(wait=False)
            except (OSError, traci.exceptions.TraCIException):
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
