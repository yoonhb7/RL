from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def binary(name):
    """Prefer an explicitly selected SUMO installation, then PATH, then PyPI SUMO."""
    suffix = ".exe" if os.name == "nt" else ""
    candidates = []
    if name == "sumo-gui" and os.environ.get("SUMO_GUI_BINARY"):
        candidates.append(Path(os.environ["SUMO_GUI_BINARY"]))
    if os.environ.get("SUMO_HOME"):
        candidate = Path(os.environ["SUMO_HOME"]) / "bin" / (name + suffix)
        if candidate.exists():
            candidates.append(candidate)
    if name == "sumo-gui" and os.name == "nt" and os.environ.get("USERPROFILE"):
        # The full official Windows ZIP includes GUI DLL dependencies that the
        # prepared PyPI executable may otherwise obtain only from the host PATH.
        portable = Path(os.environ["USERPROFILE"]) / "Downloads/sumo-win64-1.28.0/sumo-win64-1.28.0/bin/sumo-gui.exe"
        if portable.is_file():
            candidates.append(portable)
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    try:
        import sumo
        candidate = Path(sumo.__file__).parent / "bin" / (name + suffix)
        if candidate.exists():
            candidates.append(candidate)
    except ImportError:
        pass
    if not candidates:
        raise FileNotFoundError(f"{name} not found. Install requirements.txt or set SUMO_HOME.")
    if name != "sumo-gui":
        return str(candidates[0])
    failures = []
    for candidate in dict.fromkeys(candidates):
        try:
            result = subprocess.run([str(candidate), "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            if result.returncode == 0:
                return str(candidate)
            code = f"0x{result.returncode & 0xffffffff:08X}"
            detail = "missing dependent DLL" if code == "0xC0000135" else (result.stderr or result.stdout).strip()
            failures.append(f"{candidate}: {code} {detail}")
        except (OSError, subprocess.TimeoutExpired) as error:
            failures.append(f"{candidate}: {error}")
    raise RuntimeError("SUMO GUI could not start. Set SUMO_HOME to a full SUMO installation or SUMO_GUI_BINARY to its sumo-gui.exe.\n" + "\n".join(failures))


def run_command(command):
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"Command failed: {command}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def load_scenario(directory):
    directory = Path(directory).resolve()
    manifest = read_json(directory / "manifest.json")
    if not 1 <= len(manifest["signals"]) <= 3:
        raise ValueError("This baseline supports 1-3 centrally controlled intersections.")
    for key in ("decision_seconds", "horizon_seconds", "demand_seconds"):
        value = manifest[key]
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"{key} must be a positive integer (1 second simulation step).")
    if manifest["demand_seconds"] > manifest["horizon_seconds"]:
        raise ValueError("demand_seconds must not exceed horizon_seconds")
    return directory, manifest


def schema(directory, manifest):
    """Checkpoint compatibility covers ordered observation, signals and network."""
    return {
        "network_sha256": sha256(Path(directory) / manifest["net_file"]),
        **({"additional_sha256": [sha256(Path(directory) / f) for f in manifest["additional_files"]]} if manifest.get("additional_files") else {}),
        "signals": manifest["signals"],
        "decision_seconds": manifest["decision_seconds"],
        "observation_version": 1,
    }
