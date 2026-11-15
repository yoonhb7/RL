"""One owner of the TLS clock, shared by fixed-time and masked agent control."""

import math

from .scenario import LANES, MOVEMENTS, STATES, TLS, connection_attributes


def action_mask(green_elapsed, settings):
    """Called at green decision boundaries, including the truncated final state."""
    if not math.isfinite(green_elapsed) or not 0 <= green_elapsed <= settings["max_green_seconds"]:
        raise ValueError("Green age is outside the protocol")
    return (green_elapsed + 15 <= settings["max_green_seconds"], green_elapsed >= settings["min_green_seconds"])


class SignalController:
    def __init__(self, connection, settings, mode="agent"):
        if mode not in ("agent", "fixed"):
            raise ValueError("mode must be agent or fixed")
        self.connection, self.settings, self.mode = connection, settings, mode
        lights = connection.trafficlight
        if set(lights.getIDList()) != {TLS}:
            raise ValueError("Load the new fourphase scenario (center4), rather than an earlier toy/corridor map")
        links = lights.getControlledLinks(TLS)
        if len(links) != 8:
            raise ValueError("Eight controlled movement links are required")
        for index, (incoming, entries) in enumerate(zip(LANES, links)):
            attrs = connection_attributes(index)
            if len(entries) != 1 or entries[0][:2] != (incoming, f"{attrs['to']}_{attrs['toLane']}"):
                raise ValueError(f"Unexpected lane mapping for {MOVEMENTS[index]}")
        program = next(p for p in lights.getAllProgramLogics(TLS) if p.programID == lights.getProgram(TLS))
        if tuple(p.state for p in program.phases) != STATES:
            raise ValueError("Expected 12 phases in the agreed four-green/yellow/all-red order")
        durations = tuple(d for g in settings["fixed_green_seconds"] for d in (g, 3, 1))
        if tuple(p.duration for p in program.phases) != durations:
            raise ValueError("The network and settings disagree on fixed-time durations")
        self.phase, self.elapsed, self.switches = 0, 0, 0
        self._last_snapshot_phase = 0
        self._set_phase(0)

    @property
    def green(self):
        return self.phase // 3

    @property
    def in_green(self):
        return self.phase % 3 == 0

    def _set_phase(self, phase):
        self.phase, self.elapsed = phase, 0
        self.connection.trafficlight.setPhase(TLS, phase)
        # Python owns boundaries; prevent the native fixed-time clock intervening.
        self.connection.trafficlight.setPhaseDuration(TLS, 1_000_000)

    def valid_actions(self):
        if not self.in_green:
            raise RuntimeError("Agent decisions must occur in green, after the full 15-second action")
        return action_mask(self.elapsed, self.settings)

    def apply(self, action):
        if self.mode != "agent":
            raise RuntimeError("A fixed-time controller does not accept agent actions")
        if type(action) is not int or action not in (0, 1):
            raise ValueError("action must be integer 0 or 1")
        mask = self.valid_actions()
        if not mask[action]:
            raise ValueError(f"Invalid action {action} at green age {self.elapsed}s; mask={mask}")
        if action == 1:
            self.switches += 1
            self._set_phase(self.phase + 1)

    def before_second(self, snapshot=None):
        # A freshly selected action may already have set yellow while the cache
        # still represents the previous completed physical step.
        if snapshot is not None and (snapshot.phase != self._last_snapshot_phase or
                                     snapshot.signal != STATES[self._last_snapshot_phase]):
            raise RuntimeError("SUMO TLS changed outside the fourphase safety controller")
        kind = self.phase % 3
        if kind == 0 and self.mode == "fixed" and self.elapsed >= self.settings["fixed_green_seconds"][self.green]:
            self.switches += 1
            self._set_phase(self.phase + 1)
        elif kind == 1 and self.elapsed >= self.settings["yellow_seconds"]:
            self._set_phase(self.phase + 1)
        elif kind == 2 and self.elapsed >= self.settings["all_red_seconds"]:
            self._set_phase((self.phase + 1) % 12)
        lights = self.connection.trafficlight
        if snapshot is None and (lights.getPhase(TLS) != self.phase or lights.getRedYellowGreenState(TLS) != STATES[self.phase]):
            raise RuntimeError("SUMO TLS changed outside the fourphase safety controller")

    def after_second(self, snapshot=None):
        self.elapsed += 1
        if self.in_green and self.elapsed > self.settings["max_green_seconds"]:
            raise RuntimeError("Maximum green violated")
        lights = self.connection.trafficlight
        actual_phase = snapshot.phase if snapshot is not None else lights.getPhase(TLS)
        actual_state = snapshot.signal if snapshot is not None else lights.getRedYellowGreenState(TLS)
        if actual_phase != self.phase or actual_state != STATES[self.phase]:
            raise RuntimeError("Native TLS advanced during a Python-owned signal interval")
        self._last_snapshot_phase = self.phase
