"""Keep Mac SUMO connected while inspecting the new four-phase environment."""

import argparse
import json
import random
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT

sys.path.insert(0, str(ROOT))
from src.envs.fourphase_env import FourPhaseTrafficEnv
from src.traffic.experiments import write_json
from src.traffic.fourphase.runtime import FourPhaseRuntime
from src.traffic.fourphase.scenario import verify_scenario
from src.traffic.live_session import run_console


HELP = """resume           현재 fixed/random 정책으로 자동 진행
pause            일시정지, Mac 연결 유지
step [N]         시뮬레이션 N초 진행 (기본 1초)
action 0|1       random 모드에서 유효 행동 하나로 15초 진행
status           시간·현시·대기열·현재 유효 행동 확인
mode fixed|random|dqn  정책 변경 후 0초로 reset (dqn은 --model 필요)
reset            같은 수요를 0초부터 다시 시작, GUI 연결 유지
view city|junction|map  도시 전체 / 교차로 확대 / 전체 도로망 (도시 모드)
reload           주변 환경과 신호등·차량 표시 다시 읽기, 현재 시각·차량 유지
속도 조절        Mac SUMO 상단 Delay(ms): 1000≈실시간, 0=최대 속도
help             명령어 보기
quit             Python 연결 및 SUMO 시뮬레이션 종료
Ctrl+C           현재 1초 스텝을 마친 뒤 일시정지
3600초 도달 시 연결을 유지하며 reset을 기다립니다."""


class FourPhaseViewSession:
    error_help = "기록을 확인하고 reset으로 초기화하세요. 명령 목록은 help로 확인할 수 있습니다. 연결은 유지합니다."

    def __init__(self, connection, case, settings, output, mode, *, city=False, detailed_cars=False, policy=None):
        self.connection, self.case, self.settings, self.output = connection, case, settings, output
        self.delay = 0.0  # Only the Mac SUMO GUI controls pacing; no Python sleep.
        self.closed = self.running = False
        self.steps_left = 0
        self.mode = mode
        self.policy = policy
        if mode == "dqn" and policy is None:
            raise ValueError("DQN 표시에는 --model 체크포인트가 필요합니다")
        self.seed = settings["pilot_seed"]
        self.runtime = self.env = None
        self.city, self.detailed_cars = city, detailed_cars
        self.display = None
        self.camera = "city"
        self.episode = 0
        self._episode_mode = mode
        self._samples = None
        self.reset()

    @property
    def advancing(self):
        return self.running or self.steps_left > 0

    def pause(self):
        self.running, self.steps_left = False, 0

    def _sink(self, sample):
        if self.display is not None:
            self.display.update(signal_state=sample["signal_state"],
                                vehicles=set(self.runtime.metrics.departed) - set(self.runtime.metrics.arrived))
        self._samples.write(json.dumps(sample, ensure_ascii=False) + "\n")

    def reset(self):
        self.pause()
        if self.runtime is not None:
            self._save_summary("reset_before_cutoff")
        if self._samples is not None:
            self._samples.close()
        self.display = None  # runtime.reset reloads all static shapes on the Mac.
        self.episode += 1
        self._episode_mode = self.mode
        self.episode_folder = self.output / f"episode_{self.episode:03d}_{self.mode}"
        self.episode_folder.mkdir(parents=True)
        self._samples = (self.episode_folder / "seconds.jsonl").open("w", encoding="utf-8")
        kwargs = {"connection": self.connection, "settings": self.settings, "sample_sink": self._sink,
                  "use_subscriptions": True}
        self.env = FourPhaseTrafficEnv(self.case, **kwargs) if self.mode in ("random", "dqn") else None
        self.runtime = self.env.runtime if self.env else FourPhaseRuntime(self.case, mode="fixed", **kwargs)
        if self.env:
            self.state, self.info = self.env.reset(seed=self.seed)
        else:
            self.runtime.reset(self.seed)
        if self.city:
            self._attach_display()
        self.rng = random.Random(4242)
        self.output.mkdir(parents=True, exist_ok=True)
        print("reset 완료. SUMO 창과 SSH 터널은 유지됩니다.")

    def _attach_display(self):
        from src.traffic.fourphase.city_display import FourPhaseCityDisplay
        self.display = FourPhaseCityDisplay(self.connection, detailed_cars=self.detailed_cars,
                                           arm_length=self.settings["arm_length_m"])
        self.display.camera = self.camera
        self.display.attach()

    def reload_display(self):
        if not self.city:
            raise ValueError("도시 화면 시나리오를 --scenario sumo/fourphase_city로 여세요")
        self.pause()
        import importlib
        from src.traffic.fourphase import city_display, city_scene
        importlib.invalidate_caches()
        importlib.reload(city_scene)
        importlib.reload(city_display)
        for shape_id in self.connection.polygon.getIDList():
            if shape_id.startswith(city_scene.PREFIX):
                self.connection.polygon.remove(shape_id)
        self._attach_display()
        print("화면 코드 다시 읽기 완료. 현재 시각·신호·차량은 유지됩니다. resume으로 재개하세요.")

    def _save_summary(self, reason):
        if self.runtime is None or self.runtime.metrics is None:
            return
        result = self.runtime.summary(**({"raw_return": self.env.raw_return, "decisions": self.env.decisions} if self.env else {}))
        result["session_event"] = reason
        result["display_mode"] = self._episode_mode
        if self._episode_mode == "dqn":
            result["checkpoint_training_decisions"] = self.policy.decisions
            result["checkpoint_algorithm"] = self.policy.algorithm
        # A user reset/quit before cutoff is an intentional partial preview.
        if reason in ("reset_before_cutoff", "quit") and result["time_s"] < self.settings["duration_seconds"] and not result["failure"]:
            result["status"] = "partial_preview"
        write_json(self.episode_folder / "metrics.json", result)

    def print_status(self):
        c = self.runtime.controller
        data = {"mode": self.mode, "time_s": self.runtime.now, "tls_phase": c.phase,
                "green_phase": c.green, "phase_elapsed_s": c.elapsed,
                "queues": self.runtime.queues(),
                "pending_due": len(set(self.runtime.snapshot.pending) & self.runtime.metrics.due)}
        if self.env:
            data.update(action_mask=list(c.valid_actions()) if c.in_green and not self.env.action_in_progress else None,
                        action_in_progress=self.env.action_in_progress,
                        last_decision_observation=self.state.tolist())
        print(json.dumps(data, ensure_ascii=False))

    def tick(self):
        if self.runtime.now >= self.settings["duration_seconds"]:
            self.pause()
            return False
        try:
            if self.env:
                if not self.env.action_in_progress:
                    action = (self.policy.choose(self.state, self.info["action_mask"], greedy=True) if self.mode == "dqn"
                              else self.rng.choice([i for i, valid in enumerate(self.info["action_mask"]) if valid]))
                    self.env.begin_action(action)
                transition = self.env.advance_action_second()
                if transition is not None:
                    self.state, reward, terminated, truncated, self.info = transition
                    if not self.running:
                        print(f"action={self.info['requested_action']}, reward={reward:.3f}, time={self.info['time_s']:g}s")
            else:
                self.runtime.advance_second()
        except Exception as error:
            self.pause()
            if self.runtime.metrics.failure is None:
                self.runtime.metrics.failure = {"reason": str(error), "type": type(error).__name__,
                                                "time_s": self.runtime.metrics.last_sample["time_s"]
                                                if self.runtime.metrics.last_sample else 0}
            try:
                self._save_summary("execution_failure")
            except Exception:
                write_json(self.episode_folder / "failure.json", self.runtime.metrics.failure)
            raise
        if self.steps_left:
            self.steps_left -= 1
        if self.runtime.now >= self.settings["duration_seconds"]:
            self.pause()
            self._save_summary("time_limit")
            print("3600초 시간 제한에 도달했습니다. reset으로 다시 시작할 수 있습니다.")
        return True

    def command(self, line):
        words = shlex.split(line)
        if not words:
            return
        command, *args = words
        if command in ("help", "status", "pause", "resume", "reset", "reload", "quit") and args:
            raise ValueError(f"{command} 뒤에는 인수를 넣지 않습니다")
        if command == "help":
            print(HELP)
        elif command == "status":
            self.print_status()
        elif command == "pause":
            self.pause()
        elif command == "resume":
            if not self.runtime.ready or self.runtime.now >= self.settings["duration_seconds"]:
                raise ValueError("reset으로 먼저 환경을 초기화하세요")
            self.running, self.steps_left = True, 0
        elif command == "step":
            if len(args) > 1 or (args and int(args[0]) <= 0):
                raise ValueError("step [양의 구간 수]")
            self.pause()
            self.steps_left = int(args[0]) if args else 1
        elif command == "action":
            if self.mode != "random" or len(args) != 1 or args[0] not in ("0", "1"):
                raise ValueError("random 모드에서 action 0 또는 action 1")
            self.pause()
            if self.env.action_in_progress:
                raise ValueError("현재 15초 행동을 step/resume으로 마친 뒤 새 행동을 선택하세요")
            if not self.info["action_mask"][int(args[0])]:
                raise ValueError(f"현재 유효 행동은 {self.info['action_mask'].tolist()}입니다")
            self.env.begin_action(int(args[0]))
            self.steps_left = 15
        elif command == "mode":
            if len(args) != 1 or args[0] not in ("fixed", "random", "dqn"):
                raise ValueError("mode fixed / mode random / mode dqn")
            if args[0] == "dqn" and self.policy is None:
                raise ValueError("--model로 학습 모델을 먼저 불러오세요")
            self.mode = args[0]
            self.reset()
            self.print_status()
        elif command == "reset":
            self.reset()
            self.print_status()
        elif command == "reload":
            self.reload_display()
        elif command == "view":
            if not self.display or len(args) != 1:
                raise ValueError("도시 모드에서 view city / view junction / view map")
            self.display.set_camera(args[0])
            self.camera = args[0]
        elif command == "delay":
            print("Python은 추가 대기하지 않습니다. Mac SUMO 상단 Delay(ms)에서 조절하세요: 1000≈실시간, 0=최대 속도.")
        elif command == "quit":
            self.pause()
            self._save_summary("quit")
            self.closed = True
        else:
            raise ValueError("명령은 help로 확인하세요")

    def close(self):
        if self._samples is not None:
            self._samples.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("sumo/fourphase"))
    parser.add_argument("--level", choices=("low", "medium", "high"), default="medium")
    parser.add_argument("--mode", choices=("fixed", "random", "dqn"))
    parser.add_argument("--model", type=Path, help="New fourphase DQN .pt checkpoint; inference only")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18813)
    parser.add_argument("--delay", type=float, default=None,
                        help="Deprecated and ignored; adjust Delay(ms) in the Mac SUMO GUI")
    parser.add_argument("--autorun", action="store_true", help="Connect and resume continuous playback immediately")
    styles = parser.add_mutually_exclusive_group()
    styles.add_argument("--native-cars", action="store_true", help="Native detailed SUMO cars (the default)")
    styles.add_argument("--detailed-cars", action="store_true", help="Optional tracked polygon bodies; adds remote drawing work")
    args = parser.parse_args()
    if args.delay is not None:
        print("--delay는 적용하지 않습니다. 재생 속도는 Mac SUMO의 Delay(ms)에서 조절하세요.")
    scenario = (ROOT / args.scenario).resolve()
    manifest = verify_scenario(scenario)
    settings = manifest["settings"]
    mode = args.mode or ("dqn" if args.model else "fixed")
    if mode == "dqn" and not args.model:
        parser.error("--mode dqn requires --model")
    policy = None
    if args.model:
        from src.agents.fourphase_dqn import DQNPolicy
        policy = DQNPolicy(ROOT / args.model, expected_network_sha256=manifest["sha256"]["network.net.xml"],
                           expected_settings=settings)
    case = scenario / "cases" / args.level / f"seed_{settings['pilot_seed']}"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "results" / "fourphase" / f"view_{stamp}"
    import traci
    connection = session = None
    try:
        connection = traci.connect(host=args.host, port=args.port, numRetries=3)
        remote = Path(connection.simulation.getOption("configuration-file"))
        if remote.parent.name != case.name or remote.parent.parent.name != args.level:
            raise ValueError(f"Mac에서도 cases/{args.level}/{case.name}/view.sumocfg를 여세요")
        city = manifest["kind"] == "synthetic_fourphase_city_v1"
        session = FourPhaseViewSession(connection, case, settings, output, mode,
                                       city=city, detailed_cars=args.detailed_cars, policy=policy)
        print(f"4현시 화면 연결 완료. 정책={mode}. 화면 확인 중에는 신경망을 업데이트하지 않습니다.")
        if city:
            print("도시 배경·방향별 4색 신호등 4개 연결 완료. 직진·좌회전은 실제 TLS 상태를 표시합니다.")
        if policy is not None:
            print(f"학습 정책: {policy.algorithm}, 학습 decision={policy.decisions}")
        print("1초씩 진행합니다. 속도는 Mac SUMO 상단 Delay(ms)에서 조절하세요: 1000≈실시간, 0=최대 속도.")
        print(HELP)
        if args.autorun:
            session.command("resume")
        session.print_status()
        run_console(session)
    except (traci.TraCIException, traci.FatalTraCIError, OSError, ValueError) as error:
        print(f"연결/설정 오류: {error}", file=sys.stderr)
        return 1
    finally:
        if session is not None:
            session.close()
        if connection is not None:
            try:
                connection.close(wait=False)
            except (traci.TraCIException, traci.FatalTraCIError, OSError):
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
