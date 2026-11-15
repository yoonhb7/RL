"""Record the Python and SUMO versions without opening a GUI."""

import importlib.metadata
import json
import platform
import subprocess

from common import ROOT, binary


def main():
    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("eclipse-sumo", "sumo-data", "traci", "sumolib")
        },
        "binaries": {},
    }
    for name in ("sumo", "netconvert", "sumo-gui"):
        result = subprocess.run([binary(name), "--version"], check=True, capture_output=True, text=True)
        report["binaries"][name] = result.stdout.strip()
    folder = ROOT / "results" / "environment"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "versions.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
