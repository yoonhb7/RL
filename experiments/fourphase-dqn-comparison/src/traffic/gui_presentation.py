"""Road-focused SUMO scene for the Mac viewer, without information overlays.

Only GUI, polygon and vehicle appearance properties are changed. Metrics,
actions and rewards stay in the existing terminal console and result files.
"""

import math
from datetime import datetime, timezone
from pathlib import PurePosixPath

import traci.constants as tc

from src.traffic.safety_controller import DIRECTIONS


PREFIX = "_rlview/"
PALETTE = (
    (56, 189, 248, 255), (251, 146, 60, 255), (45, 212, 191, 255),
    (192, 132, 252, 255), (250, 204, 21, 255), (241, 245, 249, 255),
    (244, 114, 182, 255), (96, 165, 250, 255),
)
ON = {"r": (255, 83, 107, 255), "y": (255, 204, 66, 255), "g": (52, 232, 157, 255)}
OFF = {"r": (73, 36, 49, 255), "y": (73, 62, 34, 255), "g": (27, 63, 53, 255)}
SCHEMES = {"fleet": "RL Traffic", "waiting": "RL Waiting", "speed": "RL Speed"}


def fleet_color(vehicle_id):
    """Stable across processes/platforms, without using the simulator's RNG."""
    return PALETTE[sum((index + 1) * byte for index, byte in enumerate(vehicle_id.encode("utf-8"))) % len(PALETTE)]


class ToyGuiPresentation:
    def __init__(self, connection, *, controller="RULE", emit=print):
        self.c, self.controller, self.emit = connection, controller, emit
        self.ready, self.disabled = False, False
        self.camera, self.color_mode = "overview", "fleet"
        self.cache = {}

    def __call__(self, event, env, **data):
        # Action/reward events still go to the console; they create no GUI labels.
        if event not in {"reset", "second"}:
            return
        if event == "reset":
            self.disabled, self.ready = False, False
        if self.disabled:
            return
        try:
            getattr(self, "_" + event)(env, **data)
        except Exception as error:
            self.disabled, self.ready = True, False
            self.emit(f"화면 장식을 중단했습니다: {type(error).__name__}: {error}. "
                      "제어 콘솔은 계속 사용할 수 있습니다. XML을 Mac에 복사한 뒤 reset으로 재시도하세요.")

    def _id(self, name):
        return PREFIX + name

    def _polygon(self, name, points, color, layer=100):
        self.c.polygon.add(self._id(name), points, color, fill=True, layer=layer)

    def _rect(self, name, x, y, width, height, color, layer=100):
        self._polygon(name, ((x - width / 2, y - height / 2), (x + width / 2, y - height / 2),
                             (x + width / 2, y + height / 2), (x - width / 2, y + height / 2)), color, layer)

    def _circle(self, name, x, y, radius, color, layer=102):
        self._polygon(name, [(x + radius * math.cos(i * math.tau / 20),
                              y + radius * math.sin(i * math.tau / 20)) for i in range(20)], color, layer)

    def _color(self, name, value):
        if self.cache.get(("color", name)) != value:
            self.c.polygon.setColor(self._id(name), value)
            self.cache["color", name] = value

    def _style_vehicle(self, vehicle_id):
        self.c.vehicle.setColor(vehicle_id, fleet_color(vehicle_id))
        self.c.vehicle.setShapeClass(vehicle_id, "passenger/sedan")

    def _reset(self, env, *, info):
        self.emit("차량과 신호등 중심의 도로 화면을 구성합니다.")
        views = self.c.gui.getIDList()
        if not views:
            raise ValueError("SUMO GUI의 열린 뷰가 없습니다")
        self.view, self.env = views[0], env
        self.cache.clear()
        self.active = set(self.c.vehicle.getIDList())
        self.c.trafficlight.subscribe("center", (tc.TL_RED_YELLOW_GREEN_STATE,))
        self.c.simulation.subscribe((tc.VAR_DEPARTED_VEHICLES_IDS, tc.VAR_ARRIVED_VEHICLES_IDS))
        for vehicle_id in sorted(self.active):
            self._style_vehicle(vehicle_id)
        self._streetscape()
        self._signals()
        self._set_camera(self.camera)
        self.c.gui.setSchema(self.view, SCHEMES[self.color_mode])
        self.ready = True
        self._second(env, now=info["raw_observation"]["time_s"], initial=True)
        self.emit("도로 화면 준비 완료. view junction / view overview / colors waiting / colors fleet")

    def _streetscape(self):
        # Fine details supplement the static scenery XML. Parked cars below are
        # polygons, not traffic objects. No signs, labels, or metric cards.
        for block, x, y in (("nw", 191, 304), ("ne", 307, 304), ("se", 307, 199)):
            for index in range(5):
                self._rect(f"building/{block}/window/{index}", x - 16 + index * 8, y - 15,
                           4.5, 2, (114, 161, 183, 255), -3)
        for index in range(4):
            self._rect(f"solar/{index}", 294 + index * 8, 207, 5.5, 6, (41, 81, 121, 255), -3)
            self._rect(f"solar/{index}/line", 294 + index * 8, 207, 0.3, 6, (122, 190, 220, 255), -2)
        for index in range(6):
            self._rect(f"awning/{index}", 286 + index * 8, 283.5, 7.5, 4,
                       (230, 146, 110, 255) if index % 2 else (250, 240, 221, 255), -3)
        for row, y in enumerate((288, 301, 314)):
            for side, x in enumerate((160, 339)):
                self._rect(f"parking/{side}/{row}", x, y, 6, 10, (195, 204, 198, 255), -5)
                self._rect(f"parking/{side}/{row}/line", x - 3, y, 0.4, 10, (247, 246, 229, 255), -4)
                self._rect(f"parked/{side}/{row}", x, y, 2.3, 5.1, PALETTE[(row + side * 3) % len(PALETTE)], -2)
                self._rect(f"parked/{side}/{row}/glass", x, y + 0.8, 1.8, 1.7, (38, 62, 83, 255), -1)
        self._circle("park/pond-border", 175, 211, 9, (188, 208, 190, 255), -5)
        self._circle("park/pond", 175, 211, 7, (123, 193, 208, 255), -4)
        self._circle("park/fountain", 175, 211, 2.5, (206, 237, 239, 255), -3)
        for index, (x, y) in enumerate(((202, 183), (203, 210), (177, 184))):
            self._rect(f"park/bench/{index}", x, y, 6, 1.4, (149, 111, 80, 255), -2)
            self._rect(f"park/bench/{index}/back", x, y + 1, 6, 0.5, (117, 91, 74, 255), -2)
        for index, (x, y) in enumerate(((226, 277), (274, 276), (226, 223), (274, 224))):
            self._circle(f"planter/{index}", x, y, 3.5, (168, 186, 166, 255), -3)
            self._circle(f"flowers/{index}", x, y, 2.5, (211, 136, 163, 255), -2)
        for index, offset in enumerate((170, 200, 300, 330)):
            for axis, x, y in (("ns", 260, offset), ("ew", offset, 240)):
                self._rect(f"streetlamp/{axis}/{index}/pole", x, y, 0.6, 3.5, (113, 131, 128, 255), -2)
                self._circle(f"streetlamp/{axis}/{index}/bulb", x, y + 1.8, 1.1, (255, 239, 187, 255), -1)

    def _signals(self):
        for direction in DIRECTIONS:
            shape = self.c.lane.getShape(f"{direction}_in_0")
            (px, py), (x, y) = shape[-2:]
            distance = math.hypot(x - px, y - py)
            dx, dy = (x - px) / distance, (y - py) / distance
            sx, sy = x - dx * 9 + dy * 8, y - dy * 9 - dx * 8
            self._rect(f"signal/{direction}/shadow", sx + 0.5, sy - 0.5, 5.5, 13, (17, 24, 39, 40), 108)
            self._rect(f"signal/{direction}/body", sx, sy, 5, 12.5, (31, 43, 53, 255), 109)
            for lamp, offset in (("r", 3.8), ("y", 0), ("g", -3.8)):
                self._circle(f"signal/{direction}/{lamp}", sx, sy + offset, 1.5, OFF[lamp], 111)
            self._rect(f"signal/{direction}/stop", x - dx, y - dy,
                       3.3 if abs(dy) > 0.5 else 0.5,
                       0.5 if abs(dy) > 0.5 else 3.3, OFF["r"], 2)
            ax, ay = x - dx * 9, y - dy * 9
            arrow = [(ax + dx * 3, ay + dy * 3), (ax - dx * 2 + dy * 1.1, ay - dy * 2 - dx * 1.1),
                     (ax - dx + dy * 0.35, ay - dy - dx * 0.35),
                     (ax - dx * 4 + dy * 0.35, ay - dy * 4 - dx * 0.35),
                     (ax - dx * 4 - dy * 0.35, ay - dy * 4 + dx * 0.35),
                     (ax - dx - dy * 0.35, ay - dy + dx * 0.35),
                     (ax - dx * 2 - dy * 1.1, ay - dy * 2 + dx * 1.1)]
            self._polygon(f"signal/{direction}/arrow", arrow, (52, 232, 157, 0), 2)

    def _second(self, env, *, now, initial=False):
        if not initial:
            simulation = self.c.simulation.getSubscriptionResults() or {}
            arrived = set(simulation.get(tc.VAR_ARRIVED_VEHICLES_IDS, ()))
            departed = set(simulation.get(tc.VAR_DEPARTED_VEHICLES_IDS, ()))
            self.active.update(departed)
            self.active.difference_update(arrived)
            for vehicle_id in sorted(departed - arrived):
                self._style_vehicle(vehicle_id)
        signal = self.c.trafficlight.getSubscriptionResults("center")
        state = signal[tc.TL_RED_YELLOW_GREEN_STATE]
        for index, direction in enumerate(DIRECTIONS):
            active_lamp = state[index].lower()
            for lamp in ("r", "y", "g"):
                self._color(f"signal/{direction}/{lamp}", ON[lamp] if lamp == active_lamp else OFF[lamp])
            self._color(f"signal/{direction}/stop", ON.get(active_lamp, OFF["r"]))
            self._color(f"signal/{direction}/arrow", (*ON["g"][:3], 160 if active_lamp == "g" else 0))

    def set_status(self, mode, episode):
        # Console status changes must not create information overlays.
        pass

    def _set_camera(self, mode):
        boundary = (135, 135, 365, 365) if mode == "overview" else (208, 208, 292, 292)
        self.c.gui.setBoundary(self.view, *boundary)

    def command(self, name, arguments):
        if not self.ready or self.disabled:
            raise ValueError("시각화가 준비되지 않았습니다. XML을 Mac에 복사하고 reset하거나 --no-visuals를 확인하세요")
        if name == "view":
            if len(arguments) != 1 or arguments[0] not in ("overview", "junction"):
                raise ValueError("사용법: view overview 또는 view junction")
            self._set_camera(arguments[0])
            self.camera = arguments[0]
            return f"화면: {self.camera}"
        if name == "colors":
            if len(arguments) != 1 or arguments[0] not in SCHEMES:
                raise ValueError("사용법: colors fleet / colors waiting / colors speed")
            self.c.gui.setSchema(self.view, SCHEMES[arguments[0]])
            self.color_mode = arguments[0]
            return f"차량 색상: {self.color_mode}"
        if len(arguments) > 1:
            raise ValueError("사용법: screenshot 또는 screenshot /Users/사용자/폴더/image.png")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = PurePosixPath(arguments[0]) if arguments else PurePosixPath(self.env.sumo_config).parent / f"toy_preview_{stamp}.png"
        if not path.is_absolute() or path.suffix.lower() not in {".png", ".svg", ".pdf"}:
            raise ValueError("Mac에 존재하는 폴더의 절대 경로와 .png / .svg / .pdf 확장자를 사용하세요")
        self.c.gui.screenshot(self.view, str(path))
        return f"다음 시뮬레이션 진행 시 Mac에 화면 저장 요청: {path}. step 또는 resume을 입력하세요."
