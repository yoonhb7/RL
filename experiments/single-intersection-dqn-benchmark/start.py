"""Process-local runtime setup for ordinary Windows Explorer/console launches."""
from pathlib import Path
import os
import runpy
import sys

ROOT = Path(__file__).resolve().parent
_handles = []


def configure_windows_runtime():
    if os.name != 'nt':
        return []
    # GDAL shipped with the SUMO wheel imports Microsoft's OpenMP vcomp140.dll.
    # Explorer's PATH lacks it on this PC, although the Codex tool environment has it.
    dependency_roots = [Path(sys.executable).resolve().parent.parent,
                        Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies']
    dirs = []
    for root in dict.fromkeys(dependency_roots):
        node = root/'node/bin'
        if (node/'msvcp140.dll').is_file():
            dirs.append(node)
        for rel in ('native/jxrlib/jxrlib/bin', 'native/libheif/libheif/bin', 'native/poppler/Library/bin'):
            candidate = root/rel
            if (candidate/'vcomp140.dll').is_file():
                dirs.append(candidate)
                break
    dirs = list(dict.fromkeys(dirs))
    existing = os.environ.get('PATH','').split(os.pathsep)
    # PATH is inherited by SUMO; add_dll_directory alone only helps this Python process.
    os.environ['PATH'] = os.pathsep.join([str(p) for p in dirs]+[p for p in existing if p not in {str(d) for d in dirs}])
    for p in dirs:
        _handles.append(os.add_dll_directory(str(p)))
    return [str(p) for p in dirs]


if __name__ == '__main__':
    configure_windows_runtime()
    runpy.run_path(str(ROOT/'run.py'), run_name='__main__')
