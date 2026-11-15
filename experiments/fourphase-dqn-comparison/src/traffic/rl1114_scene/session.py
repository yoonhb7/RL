"""Persistent Mac viewing session for the copied city scene; no RL controller."""

import json
import math
import shlex
import types
from pathlib import PurePosixPath

from .common import ROOT


HELP = """resume / pause     자동 진행 / 일시정지
step [N]           시뮬레이션 N초 진행 후 정지 (기본 1)
reset              같은 Mac 창에서 처음부터 다시 시작
level low|medium|high  수요 변경 후 초기화
reload             저장한 appearance.py를 다시 읽어 화면만 다시 구성
view city|junction|map  도시 전체 / 교차로 확대 / 도로망 전체
status             시각·기본 신호·차량 수 확인
delay 0.07         시뮬레이션 1초당 실제 대기시간
quit               최종 종료
Ctrl+C             일시정지, 연결 유지
이 콘솔은 원본 도로의 기본 고정신호를 사용하며 학습하지 않습니다."""


class CityViewSession:
    def __init__(self, connection, output, *, delay=0.07):
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("delay must be finite and nonnegative")
        self.c, self.output, self.delay = connection, output, delay
        self.config = PurePosixPath(self.c.simulation.getOption("configuration-file"))
        self.level = self.config.parent.name
        if self.level not in ("low", "medium", "high") or self.config.name != "view.sumocfg":
            raise ValueError("Mac에서 rl1114_city/cases/medium/view.sumocfg를 열어주세요")
        self.seed = int(self.c.simulation.getOption("seed"))
        settings = json.loads((ROOT / "scene_settings.json").read_text(encoding="utf-8"))["scenario"]
        self.horizon = settings["demand_seconds"] + settings["drain_seconds"]
        self.closed = self.running = self.done = False
        self.steps_left = 0
        self.episode = -1
        self.camera = "city"
        self.scene = None
        self.reset()

    @property
    def advancing(self):
        return self.running or self.steps_left > 0

    def pause(self):
        self.running, self.steps_left = False, 0

    def _camera(self):
        cx, cy = self.c.junction.getPosition("J")
        if self.camera == "map":
            self.c.gui.setBoundary(self.view, 0, 0, 800, 700)
        else:
            width, height = (155, 112) if self.camera == "city" else (42, 30)
            self.c.gui.setBoundary(self.view, cx - width, cy - height, cx + width, cy + height)

    def reload_scene(self):
        self.pause()
        path = ROOT.parents[1] / "src/traffic/rl1114_scene/appearance.py"
        module = types.ModuleType("_rl1114_city_display")
        module.__file__ = str(path)
        module.__package__ = "src.traffic.rl1114_scene"
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
        # Original display IDs are city.*. Keep all traffic and native signals.
        for polygon in self.c.polygon.getIDList():
            if polygon.startswith("city."):
                self.c.polygon.remove(polygon)
        self.scene = module.CityAppearance(self.c, self.episode_output, self.level)
        self.scene.build()
        self.c.gui.setSchema(self.view, "benchmark")
        self._camera()

    def reset(self):
        self.pause()
        self.done = False
        self.c.load(["-c", str(self.config), "--seed", str(self.seed), "--begin", "0", "--step-length", "1",
                     "--route-steps", "0", "--start", "--no-step-log", "true", "--duration-log.disable", "true"])
        if set(self.c.trafficlight.getIDList()) != {"J"}:
            raise ValueError("Mac의 도로 파일이 RL1114 단일 교차로 J가 아닙니다")
        if not math.isclose(self.c.simulation.getDeltaT(), 1):
            raise ValueError("SUMO step-length must be 1 second")
        views = self.c.gui.getIDList()
        if not views:
            raise ValueError("SUMO GUI view not found")
        self.view = views[0]
        self.episode += 1
        self.episode_output = self.output / f"episode_{self.episode}_{self.level}"
        self.episode_output.mkdir(parents=True, exist_ok=False)
        self.reload_scene()

    def tick(self):
        if self.done:
            self.pause()
            return
        before = self.c.simulation.getTime()
        self.c.simulationStep()
        now = self.c.simulation.getTime()
        if not math.isclose(now - before, 1):
            raise RuntimeError("SUMO did not advance exactly one second")
        self.scene.update()
        if self.steps_left:
            self.steps_left -= 1
        if now >= self.horizon:
            self.done = True
            self.pause()
            print("종료 시각에 도달했습니다. reset 또는 level high로 다시 볼 수 있습니다.")

    def print_status(self):
        print(json.dumps({"level": self.level, "time_s": self.c.simulation.getTime(), "horizon_s": self.horizon,
                          "controller": "native SUMO fixed-time; no learning", "signal": self.c.trafficlight.getRedYellowGreenState("J"),
                          "vehicles": self.c.vehicle.getIDCount(), "paused": not self.advancing,
                          "done": self.done, "seed": self.seed, "mac_config": str(self.config)}, ensure_ascii=False))

    def command(self, line):
        words = shlex.split(line)
        if not words:
            return
        command, *arguments = words
        if command in ("resume", "pause", "reset", "reload", "status", "help", "quit") and arguments:
            raise ValueError(f"{command}에는 인수가 없습니다")
        if command == "resume":
            if self.done:
                print("reset 후 resume을 입력하세요")
            else:
                self.running, self.steps_left = True, 0
        elif command == "pause":
            self.pause()
        elif command == "step":
            if len(arguments) > 1:
                raise ValueError("step 또는 step 10")
            count = int(arguments[0]) if arguments else 1
            if count <= 0 or self.done:
                raise ValueError("양의 초를 입력하세요. 종료됐다면 reset이 필요합니다")
            self.pause()
            self.steps_left = count
        elif command == "reset":
            self.reset()
            self.print_status()
        elif command == "level":
            if len(arguments) != 1 or arguments[0] not in ("low", "medium", "high"):
                raise ValueError("level low / level medium / level high")
            self.level = arguments[0]
            self.config = self.config.parent.parent / self.level / "view.sumocfg"
            self.reset()
            self.print_status()
        elif command == "reload":
            self.reload_scene()
            print("화면 코드를 다시 읽었습니다. 시각과 차량은 유지되며 resume으로 진행합니다.")
        elif command == "view":
            if len(arguments) != 1 or arguments[0] not in ("city", "junction", "map"):
                raise ValueError("view city / view junction / view map")
            self.camera = arguments[0]
            self._camera()
        elif command == "delay":
            value = float(arguments[0]) if len(arguments) == 1 else -1
            if not math.isfinite(value) or value < 0:
                raise ValueError("delay 0.07처럼 유한한 0 이상의 값을 입력하세요")
            self.delay = value
        elif command == "status":
            self.print_status()
        elif command == "help":
            print(HELP)
        elif command == "quit":
            self.pause()
            self.closed = True
        else:
            raise ValueError("알 수 없는 명령입니다. help를 입력하세요")
