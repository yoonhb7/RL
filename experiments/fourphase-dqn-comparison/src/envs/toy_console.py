"""Persistent command interface for the discrete-action Gymnasium environment."""

import copy
import json
import math
import shlex

from src.traffic.live_session import load_controller


HELP = """action 0     유지 행동 1회 실행 (기본 시뮬레이션 5초)
action 1     전환 요청 1회 실행 (기본 시뮬레이션 5초)
step [N]     제어 파일의 행동으로 N번 진행 후 대기 (기본 1)
resume       제어 파일의 행동으로 자동 진행
pause        일시정지, 연결 유지
reload       선택한 제어 코드 또는 학습 모델을 다시 읽기
reset        시나리오 재시작 + Warm-up; 연결 유지
status       상태, 직전 행동/보상, 누적 보상 확인
delay 0.1    시뮬레이션 1초마다 기다릴 실제 시간 변경
view overview|junction  도로와 주변 풍경 / 교차로 확대
colors fleet|waiting|speed  차량 색상 모드
screenshot [Mac경로]  다음 진행 시 Mac에 화면 저장
help         명령어 목록
quit         최종 종료
Ctrl+C       일시정지 (진행 중인 제어 구간을 마친 뒤 적용)"""


class ToyEnvSession:
    # Pacing happens inside env.step(), once per simulated second.
    delay = 0.0

    def __init__(self, env, controller_path, *, seed=42, emit=print, record=None, controller_loader=None,
                 presentation=None):
        self.env = env
        self.presentation = presentation
        self.controller_path = controller_path
        self.controller_loader = controller_loader or (lambda path: load_controller(path, "choose_action"))
        self.seed = seed
        self.emit = emit
        self.record = record or (lambda event: None)
        self.running = False
        self.steps_left = 0
        self.closed = False
        self.manual_action = None
        self.done = False
        self.episode = 0
        self.last_reward = None
        self.controller, self.controller_version = self.controller_loader(controller_path)
        self.observation, self.info = self.env.reset(seed=seed)
        self._record_reset()
        self._display_mode()

    def _display_mode(self):
        if self.presentation is not None:
            mode = "FINISHED" if self.done else "RUNNING" if self.advancing else "PAUSED"
            self.presentation.set_status(mode, self.episode)

    @property
    def advancing(self):
        return self.running or self.steps_left > 0

    def pause(self):
        self.running = False
        self.steps_left = 0
        self.manual_action = None
        self._display_mode()

    def _record_reset(self):
        self.record({"event": "reset", "episode": self.episode, "controller": self.controller_version,
                     "observation": self.observation.tolist(), "info": self.info})

    def print_status(self):
        self.emit(json.dumps({
            "mode": "running" if self.advancing else "paused", "episode": self.episode,
            "controller": self.controller_version, "observation": self.observation.tolist(),
            "reward": self.last_reward, "done": self.done, "info": self.info,
        }, ensure_ascii=False))

    def reload_controller(self):
        self.pause()
        try:
            candidate, version = self.controller_loader(self.controller_path)
            action = candidate.choose_action(self.observation.copy(), copy.deepcopy(self.info))
        except OSError as error:
            raise ValueError(f"제어 파일을 읽지 못했습니다. 기존 코드 유지: {error}") from error
        if isinstance(action, bool) or not self.env.action_space.contains(action):
            raise ValueError(f"choose_action은 정수 0–{self.env.action_space.n - 1}을 반환해야 합니다. 기존 코드를 유지합니다")
        self.controller, self.controller_version = candidate, version
        self._display_mode()
        self.record({"event": "reload", "episode": self.episode, "controller": version,
                     "time_s": self.info["raw_observation"]["time_s"]})
        self.emit(f"reload 완료: {version}. 차량과 시각을 유지합니다. step/resume으로 진행하세요.")

    def tick(self):
        if self.done:
            self.pause()
            self.emit("에피소드가 끝났습니다. reset으로 다시 시작하세요. 연결은 유지됩니다.")
            return
        if self.manual_action is None:
            action = self.controller.choose_action(self.observation.copy(), copy.deepcopy(self.info))
        else:
            action = self.manual_action
        if isinstance(action, bool) or not self.env.action_space.contains(action):
            raise ValueError(f"choose_action은 정수 0–{self.env.action_space.n - 1}을 반환해야 합니다")
        previous = self.observation.copy()
        self._display_mode()
        observation, reward, terminated, truncated, info = self.env.step(int(action))
        self.observation, self.info, self.last_reward = observation, info, reward
        self.done = terminated or truncated
        self.record({
            "event": "transition", "episode": self.episode, "controller": self.controller_version,
            "observation": previous.tolist(), "action": int(action), "reward": reward,
            "next_observation": observation.tolist(), "terminated": terminated, "truncated": truncated,
            "info": info,
        })
        self.emit(json.dumps({
            "time_s": info["raw_observation"]["time_s"], "action": info["action"], "reward": reward,
            "episode_return": info["episode_return"], "phase": info["raw_observation"]["phase_index"],
            "queues": info["raw_observation"]["queues"], "forced_switches": info["forced_switches"],
        }, ensure_ascii=False))
        if self.steps_left:
            self.steps_left -= 1
        if self.done:
            self.pause()
            self.emit("에피소드 종료 시각에 도달했습니다. 연결을 유지한 채 reset을 기다립니다.")
        self._display_mode()

    def command(self, line):
        words = shlex.split(line)
        if not words:
            return
        command, *arguments = words
        command = command.lower()
        if command in {"help", "status", "pause", "resume", "reload", "reset", "quit"} and arguments:
            raise ValueError(f"{command}에는 인수가 없습니다")
        if command == "help":
            self.emit(getattr(self.env, "console_help", HELP))
        elif command == "status":
            self.print_status()
        elif command == "pause":
            self.pause()
            self.emit("일시정지했습니다. 연결은 유지됩니다.")
        elif command == "resume":
            if self.done:
                self.emit("reset 후 다시 시작하세요")
            else:
                self.running, self.steps_left, self.manual_action = True, 0, None
                self._display_mode()
                self.emit("제어 코드의 행동으로 진행합니다. pause로 일시정지하세요.")
        elif command == "step":
            if len(arguments) > 1:
                raise ValueError("사용법: step 또는 step 10")
            count = int(arguments[0]) if arguments else 1
            if count <= 0:
                raise ValueError("step 수는 양수여야 합니다")
            self.pause()
            self.steps_left = count
            self._display_mode()
        elif command == "action":
            if (len(arguments) != 1 or not arguments[0].isdigit()
                    or not self.env.action_space.contains(int(arguments[0]))):
                raise ValueError(f"사용법: action 0–{self.env.action_space.n - 1}")
            self.pause()
            self.manual_action = int(arguments[0])
            self.steps_left = 1
            # A manual command is one complete transition. Pasting multiple
            # action lines must not overwrite an action waiting in the queue.
            try:
                self.tick()
            finally:
                self.pause()
        elif command == "reload":
            self.reload_controller()
        elif command == "reset":
            self.pause()
            self.observation, self.info = self.env.reset(seed=self.seed)
            self.done, self.last_reward = False, None
            self.episode += 1
            self._record_reset()
            self._display_mode()
            self.print_status()
        elif command == "delay":
            if len(arguments) != 1:
                raise ValueError("사용법: delay 0.1")
            delay = float(arguments[0])
            if not math.isfinite(delay) or delay < 0:
                raise ValueError("delay는 유한한 0 이상의 값이어야 합니다")
            self.env.wall_delay = delay
            self.emit(f"시뮬레이션 1초마다 실제 {delay:g}초 대기합니다")
        elif command == "quit":
            self.pause()
            self.closed = True
        elif command in {"view", "colors", "screenshot"}:
            if self.presentation is None:
                raise ValueError("화면 명령은 시각화를 활성화한 Mac 콘솔에서 사용합니다")
            self.emit(self.presentation.command(command, arguments))
        else:
            raise ValueError("알 수 없는 명령입니다. help를 입력하세요")
