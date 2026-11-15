"""Translate hold/switch requests into a signal's legal phase sequence."""

import math
from numbers import Integral


DIRECTIONS = ("north", "south", "east", "west")
EXPECTED_STATES = ("GGrr", "yyrr", "rrrr", "rrGG", "rryy", "rrrr")
GREEN_PHASES = (0, 3)


def validate_toy_network(connection):
    if set(connection.trafficlight.getIDList()) != {"center"}:
        raise ValueError("toy 환경에는 center 신호등 하나가 필요합니다")
    validate_signal(connection, "center", [f"{direction}_in_0" for direction in DIRECTIONS])


def validate_signal(connection, signal_id, incoming_lanes):
    lights = connection.trafficlight
    if signal_id not in lights.getIDList():
        raise ValueError(f"신호등을 찾지 못했습니다: {signal_id}")
    links = lights.getControlledLinks(signal_id)
    if len(incoming_lanes) != 4 or len(links) != 4 or any(
        len(links[index]) != 1 or links[index][0][0] != lane
        for index, lane in enumerate(incoming_lanes)
    ):
        raise ValueError(f"{signal_id}: 신호 인덱스와 진입 차로 연결이 일치하지 않습니다")
    program_id = lights.getProgram(signal_id)
    programs = lights.getAllProgramLogics(signal_id)
    program = next((item for item in programs if item.programID == program_id), None)
    if program is None or tuple(p.state for p in program.phases) != EXPECTED_STATES:
        raise ValueError("남북→황색→전적색→동서→황색→전적색 프로그램이 필요합니다")
    for index, duration in ((1, 3), (2, 1), (4, 3), (5, 1)):
        if program.phases[index].duration != duration:
            raise ValueError(f"{signal_id}: 전환시간은 황색 3초, 전적색 1초여야 합니다")


class SafetyController:
    def __init__(self, connection, min_green=10, max_green=60, *, signal_id="center", incoming_lanes=None):
        if not all(math.isfinite(value) for value in (min_green, max_green)) or not 0 < min_green <= max_green:
            raise ValueError("0 < min_green <= max_green이어야 합니다")
        self.connection = connection
        self.signal_id = signal_id
        self.min_green = float(min_green)
        self.max_green = float(max_green)
        self.forced_switches = 0
        if incoming_lanes is None:
            validate_toy_network(connection)
        else:
            validate_signal(connection, signal_id, incoming_lanes)

    def phase(self):
        lights = self.connection.trafficlight
        return lights.getPhase(self.signal_id), lights.getSpentDuration(self.signal_id)

    def _start_yellow(self, phase, *, forced):
        # Never jump directly from one green to the opposite green.
        self.connection.trafficlight.setPhase(self.signal_id, phase + 1)
        if forced:
            self.forced_switches += 1

    def apply_action(self, action):
        if isinstance(action, bool) or not isinstance(action, Integral) or action not in (0, 1):
            raise ValueError("행동은 정수 0(유지) 또는 1(전환 요청)이어야 합니다")
        phase, elapsed = self.phase()
        result = {"requested": int(action), "accepted": False, "reason": "clearance", "forced": False}
        if phase not in GREEN_PHASES:
            return result
        if elapsed >= self.max_green:
            self._start_yellow(phase, forced=True)
            result.update(reason="max_green", forced=True)
        elif action == 0:
            result.update(accepted=True, reason="hold")
        elif elapsed < self.min_green:
            result.update(reason="min_green")
        else:
            self._start_yellow(phase, forced=False)
            result.update(accepted=True, reason="switch")
        return result

    def before_step(self):
        """Enforce the maximum at each physical step, not only at decision times."""
        phase, elapsed = self.phase()
        if phase not in GREEN_PHASES:
            return False
        if elapsed >= self.max_green:
            self._start_yellow(phase, forced=True)
            return True
        # Override the native 30-second timer while allowing SUMO to run clearances.
        self.connection.trafficlight.setPhaseDuration(self.signal_id, self.max_green - elapsed)
        return False
