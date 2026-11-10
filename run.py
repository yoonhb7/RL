"""Run from any directory without installing this project as a package."""
from pathlib import Path
import os
import sys

project = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(project / "work" / "matplotlib"))
sys.path.insert(0, str(project / "src"))
from traffic_rl.cli import main

if __name__ == "__main__":
    main()
