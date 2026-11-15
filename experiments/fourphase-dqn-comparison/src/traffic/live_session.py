"""Single-threaded TraCI session with a persistent terminal command interface."""

import codecs
import hashlib
import json
import math
import os
import select
import shlex
import signal
import sys
import time
import types
from pathlib import Path

from traci.exceptions import FatalTraCIError


DIRECTIONS = ("north", "south", "east", "west")
MIN_GREEN_SECONDS = 10.0
MAX_GREEN_SECONDS = 60.0
EXPECTED_STATES = ("GGrr", "yyrr", "rrrr", "rrGG", "rryy", "rrrr")
HELP = """resume       자동 진행 재개
pause        일시정지 (연결 유지)
step [N]     N개 스텝 진행 후 대기 (기본 1; 현재 시나리오의 1스텝=1초)
reload       저장한 live_controller.py를 다시 읽기; 일시정지 유지
reset        Mac의 시나리오를 0초부터 다시 불러오기; 일시정지 유지
status       시간, 신호, 대기행렬, 제어 코드 버전 확인
delay 0.1    스텝 사이 대기시간 변경 (초, 0이면 최대 속도)
help         명령어 보기
quit         연결 종료 (SUMO에 종료 요청)
Ctrl+C       일시정지 (연결 유지), Ctrl+D는 quit과 같음"""


def load_controller(path, required_function="green_seconds"):
    """Compile fresh source without stale bytecode or modifying the active module."""
    path = Path(path)
    source = path.read_bytes()
    module = types.ModuleType("_live_traffic_controller")
    module.__file__ = str(path)
    exec(compile(source, str(path), "exec"), module.__dict__)
    if not callable(getattr(module, required_function, None)):
        raise ValueError(f"제어 파일에 {required_function} 함수가 필요합니다")
    return module, hashlib.sha256(source).hexdigest()[:12]


def valid_green_seconds(value):
    if isinstance(value, bool):
        raise ValueError("녹색시간은 bool이 아닌 숫자여야 합니다")
    duration = float(value)
    if not math.isfinite(duration) or not MIN_GREEN_SECONDS <= duration <= MAX_GREEN_SECONDS:
        raise ValueError(f"녹색시간은 {MIN_GREEN_SECONDS:g}–{MAX_GREEN_SECONDS:g}초여야 합니다")
    return duration


class LiveSession:
    def __init__(self, connection, controller_path, *, end=1200, delay=0.1, mac_config=None, emit=print):
        self.connection = connection
        self.controller_path = Path(controller_path)
        self.end = end
        self.delay = delay
        self.emit = emit
        self.running = False
        self.steps_left = 0
        self.closed = False
        self.controller, self.controller_version = load_controller(self.controller_path)
        # This option belongs to the Mac SUMO process. Never expand it using Linux HOME.
        self.mac_config = mac_config or connection.simulation.getOption("configuration-file")
        self.seed = connection.simulation.getOption("seed")
        self.validate_network()
        if not self.mac_config:
            self.emit("시나리오 경로를 찾지 못했습니다. reset을 쓰려면 --mac-config로 Mac 경로를 지정하세요.")

    @property
    def advancing(self):
        return self.running or self.steps_left > 0

    def pause(self):
        self.running = False
        self.steps_left = 0

    def validate_network(self):
        lights = self.connection.trafficlight
        if set(lights.getIDList()) != {"center"}:
            raise ValueError("현재 개발 콘솔은 toy 사거리(center) 전용입니다")
        links = lights.getControlledLinks("center")
        if len(links) != 4 or any(
            len(links[index]) != 1 or links[index][0][0] != f"{direction}_in_0"
            for index, direction in enumerate(DIRECTIONS)
        ):
            raise ValueError("Mac 도로망의 신호 인덱스/차로 연결이 toy 시나리오와 다릅니다")
        program_id = lights.getProgram("center")
        program = next(p for p in lights.getAllProgramLogics("center") if p.programID == program_id)
        if tuple(p.state for p in program.phases) != EXPECTED_STATES:
            raise ValueError("남북→황색→전적색→동서→황색→전적색 신호 순서가 필요합니다")
        if any(program.phases[index].duration != duration for index, duration in ((1, 3), (2, 1), (4, 3), (5, 1))):
            raise ValueError("황색 3초, 전적색 1초인 toy 시나리오가 필요합니다")

    def observation(self):
        lights = self.connection.trafficlight
        lane = self.connection.lane
        return {
            "time_s": self.connection.simulation.getTime(),
            "phase_index": lights.getPhase("center"),
            "phase_elapsed_s": lights.getSpentDuration("center"),
            "signal_state": lights.getRedYellowGreenState("center"),
            "queues": {d: lane.getLastStepHaltingNumber(f"{d}_in_0") for d in DIRECTIONS},
            "vehicles": {d: lane.getLastStepVehicleNumber(f"{d}_in_0") for d in DIRECTIONS},
        }

    def print_status(self):
        status = self.observation()
        status.update(mode="running" if self.advancing else "paused", controller=self.controller_version)
        self.emit(json.dumps(status, ensure_ascii=False))

    def reload_controller(self):
        self.pause()
        try:
            candidate, version = load_controller(self.controller_path)
        except OSError as error:
            raise ValueError(f"제어 파일을 읽지 못했습니다. 기존 코드를 유지합니다: {error}") from error
        # Test both green branches before committing a replacement. No TraCI mutations.
        observation = self.observation()
        for phase in (0, 3):
            probe = {**observation, "phase_index": phase, "phase_elapsed_s": 0.0}
            try:
                valid_green_seconds(candidate.green_seconds(probe))
            except Exception as error:
                raise ValueError(f"새 제어 코드 검사 실패. 기존 코드를 유지합니다: {error}") from error
        self.controller, self.controller_version = candidate, version
        self.emit(f"reload 완료: {version}. 다음 step/resume부터 적용합니다. 현재 차량과 시각은 유지됩니다.")

    def reset(self):
        self.pause()
        if not self.mac_config:
            raise ValueError("reset에 필요한 Mac 시나리오 경로가 없습니다. --mac-config를 지정하세요")
        arguments = ["-c", self.mac_config, "--start"]
        if self.seed:
            arguments += ["--seed", self.seed]
        self.connection.load(arguments)
        self.validate_network()
        self.emit("reset 완료: 시나리오를 처음부터 불러왔습니다. 연결과 제어 코드를 유지합니다.")
        self.print_status()

    def tick(self):
        """One safe phase-boundary operation; only the console loop calls TraCI."""
        if self.connection.simulation.getTime() >= self.end:
            self.pause()
            self.emit(f"{self.end:g}초에 도달했습니다. reset으로 다시 시작할 수 있습니다. 연결은 유지됩니다.")
            return False
        observation = self.observation()
        if observation["phase_index"] in (0, 3):
            target = valid_green_seconds(self.controller.green_seconds(observation))
            remaining = max(0.0, target - observation["phase_elapsed_s"])
            # Set remaining, not total: repeated calls must not extend green forever.
            # Let SUMO enter its predefined yellow/all-red phases in sequence.
            self.connection.trafficlight.setPhaseDuration("center", remaining)
        self.connection.simulationStep()
        if self.steps_left:
            self.steps_left -= 1
        if self.connection.simulation.getTime() >= self.end:
            self.pause()
            self.emit(f"{self.end:g}초에서 일시정지했습니다. reset 명령을 기다립니다. 연결은 유지됩니다.")
        return True

    def command(self, line):
        words = shlex.split(line)
        if not words:
            return
        command, *arguments = words
        command = command.lower()
        if command in {"help", "status", "pause", "resume", "reload", "reset", "quit"} and arguments:
            raise ValueError(f"{command} 뒤에는 인수를 넣지 않습니다")
        if command == "help":
            self.emit(HELP)
        elif command == "status":
            self.print_status()
        elif command == "pause":
            self.pause()
            self.emit("일시정지했습니다. 연결은 유지됩니다.")
        elif command == "resume":
            if self.connection.simulation.getTime() >= self.end:
                self.emit("종료 시각에 도달했습니다. reset으로 먼저 초기화하세요.")
            else:
                self.running, self.steps_left = True, 0
                self.emit("자동 진행합니다. pause 또는 Ctrl+C로 일시정지할 수 있습니다.")
        elif command == "step":
            if len(arguments) > 1:
                raise ValueError("사용법: step 또는 step 10")
            count = int(arguments[0]) if arguments else 1
            if count <= 0:
                raise ValueError("step 수는 양의 정수여야 합니다")
            self.pause()
            self.steps_left = count
            self.emit(f"{count}개 스텝 진행 후 대기합니다.")
        elif command == "reload":
            self.reload_controller()
        elif command == "reset":
            self.reset()
        elif command == "delay":
            if len(arguments) != 1:
                raise ValueError("사용법: delay 0.1")
            value = float(arguments[0])
            if not math.isfinite(value) or value < 0:
                raise ValueError("delay는 유한한 0 이상의 초 단위 숫자여야 합니다")
            self.delay = value
            self.emit(f"스텝 사이 대기시간: {value:g}초")
        elif command == "quit":
            self.pause()
            self.closed = True
        else:
            raise ValueError("알 수 없는 명령입니다. help를 입력하세요")


class ConsoleInput:
    """Read buffered terminal or pipe input without threads touching TraCI."""
    def __init__(self, stream):
        self.fd = stream.fileno()
        self.decoder = codecs.getincrementaldecoder(stream.encoding or "utf-8")()
        self.buffer = ""
        self.eof = False

    def poll(self, timeout):
        # Return (has_event, line). A None line denotes EOF, never an idle timeout.
        if "\n" not in self.buffer and not self.eof:
            ready, _, _ = select.select([self.fd], [], [], timeout)
            if not ready:
                return False, None
            data = os.read(self.fd, 4096)
            self.buffer += self.decoder.decode(data, final=not data)
            self.eof = not data
        if "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            return True, line
        if self.eof:
            if self.buffer:
                line, self.buffer = self.buffer, ""
                return True, line
            return True, None
        return False, None


def run_console(session):
    reader = ConsoleInput(sys.stdin)
    pause_requested = False

    def request_pause(signum, frame):
        nonlocal pause_requested
        # Do not interrupt socket.recv halfway through a TraCI reply.
        pause_requested = True

    previous_handler = signal.signal(signal.SIGINT, request_pause)
    next_tick = time.monotonic()
    try:
        print("sumo> ", end="", flush=True)
        while not session.closed:
            if pause_requested:
                pause_requested = False
                session.pause()
                print("\n일시정지했습니다. 연결은 유지됩니다.\nsumo> ", end="", flush=True)
            try:
                timeout = min(max(0, next_tick - time.monotonic()), 0.1) if session.advancing else 0.1
                event, line = reader.poll(timeout)
                if event:
                    if line is None:
                        session.command("quit")
                    else:
                        session.command(line)
                        next_tick = time.monotonic() + session.delay
                        if not session.closed:
                            print("sumo> ", end="", flush=True)
                elif session.advancing and not pause_requested and time.monotonic() >= next_tick:
                    session.tick()
                    next_tick = time.monotonic() + session.delay
                    if not session.advancing:
                        print("\nsumo> ", end="", flush=True)
            except (FatalTraCIError, OSError):
                raise
            except Exception as error:
                session.pause()
                print(f"\n일시정지: {type(error).__name__}: {error}", flush=True)
                guidance = getattr(session, "error_help", "명령은 help로 확인하세요. 제어 코드는 수정 후 reload, 환경 오류는 reset하세요. 연결은 유지합니다.")
                print(f"{guidance}\nsumo> ", end="", flush=True)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
