from __future__ import annotations

import numpy as np


def decode_action(action, count):
    if not 0 <= int(action) < 2 ** count:
        raise ValueError("joint action out of range")
    return [(int(action) >> i) & 1 for i in range(count)]


def encode_action(bits):
    if any(b not in (0, 1) for b in bits):
        raise ValueError("actions must be binary")
    return sum(int(b) << i for i, b in enumerate(bits))


class SafetySignal:
    """One-second FSM. Requests never bypass yellow or all-red clearance."""

    def __init__(self, spec):
        self.spec = spec
        if not (0 < spec["min_green"] <= spec["fixed_green"] <= spec["max_green"]):
            raise ValueError("require 0 < min_green <= fixed_green <= max_green")
        if any(not isinstance(spec[k], int) or spec[k] <= 0 for k in ["min_green", "max_green", "fixed_green", "yellow", "all_red"]):
            raise ValueError("signal durations must be positive integer seconds")
        if len(spec["greens"]) < 2 or len(spec["greens"]) != len(spec["yellows"]):
            raise ValueError("each cyclic green requires its own yellow")
        states = spec["greens"] + spec["yellows"] + [spec["all_red_state"]]
        if len({len(s) for s in states}) != 1 or set(spec["all_red_state"]) != {"r"}:
            raise ValueError("inconsistent states or non-red clearance")
        for g, y in zip(spec["greens"], spec["yellows"]):
            if "y" in g.lower() or not any(c in "Gg" for c in g):
                raise ValueError("green state must contain green and no yellow")
            expected = "".join("y" if c in "Gg" else "r" for c in g)
            if y != expected:
                raise ValueError("yellow must clear exactly the outgoing green movements")
        self.green = 0
        self.stage = "green"
        self.elapsed = 0
        self.switches = 0

    def allowed(self):
        if self.stage != "green" or self.elapsed < self.spec["min_green"]:
            return (0,)
        if self.elapsed >= self.spec["max_green"]:
            return (1,)
        return (0, 1)

    def request(self, switch):
        if switch and 1 in self.allowed():
            self._start_yellow()

    def _start_yellow(self):
        self.stage, self.elapsed = "yellow", 0
        self.switches += 1

    def before_second(self):
        if self.stage == "yellow" and self.elapsed >= self.spec["yellow"]:
            self.stage, self.elapsed = "all_red", 0
        elif self.stage == "all_red" and self.elapsed >= self.spec["all_red"]:
            self.green = (self.green + 1) % len(self.spec["greens"])
            self.stage, self.elapsed = "green", 0
        if self.stage == "green" and self.elapsed >= self.spec["max_green"]:
            self._start_yellow()
        return self.state

    @property
    def state(self):
        if self.stage == "green":
            return self.spec["greens"][self.green]
        if self.stage == "yellow":
            return self.spec["yellows"][self.green]
        return self.spec["all_red_state"]

    def after_second(self):
        self.elapsed += 1


def joint_mask(signals):
    return np.array([all(b in s.allowed() for b, s in zip(decode_action(a, len(signals)), signals)) for a in range(2 ** len(signals))], dtype=bool)
