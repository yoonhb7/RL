"""Portable entry point. Uses the prepared local runtime only when installed here."""
from pathlib import Path
import importlib.util
import os
import sys

ROOT = Path(__file__).resolve().parent
_dll_handles = []
if importlib.util.find_spec('torch') is None:
    prepared = ROOT.parent.parent / 'work' / 'runtime'
    if (prepared / 'torch').is_dir():
        sys.path.insert(0, str(prepared))
if os.name == 'nt':
    candidates = [Path(sys.executable).parent.parent / 'node' / 'bin',
                  Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin']
    for p in candidates:
        if (p / 'msvcp140.dll').is_file():
            os.environ['PATH'] = str(p) + os.pathsep + os.environ.get('PATH', '')
            _dll_handles.append(os.add_dll_directory(str(p)))

if __name__ == '__main__':
    from trafficbench.cli import main
    main()
