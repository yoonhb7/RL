"""Project root and SUMO executable lookup shared by the scripts."""

import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def binary(name):
    # Prefer the current interpreter's environment over unrelated system versions.
    candidate = Path(sys.executable).parent / name
    if candidate.is_file():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"{name} is missing; activate the project environment (conda activate fourphase-py310)")
