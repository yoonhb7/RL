"""Paths and settings shared by the toy simulation commands."""

import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOY = ROOT / "sumo" / "toy"
CONFIG_PATH = ROOT / "configs" / "toy.json"
DIRECTIONS = ("north", "south", "east", "west")


def read_config():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not 0 <= config["warmup_seconds"] < config["demand_end_seconds"] <= config["duration_seconds"]:
        raise ValueError("Expected 0 <= warmup < demand end <= duration")
    if config["step_length_seconds"] != 1:
        raise ValueError("The first baseline uses one-second samples")
    return config


def binary(name):
    # Prefer the current interpreter's environment over unrelated system versions.
    candidate = Path(sys.executable).parent / name
    if candidate.is_file():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"{name} is missing; install requirements.txt in .venv")
