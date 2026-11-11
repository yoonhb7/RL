"""Portable environment setup. Optional external package directory is explicit."""
import os
import sys
from pathlib import Path

HANDLES = []

def configure():
    prepared = os.getenv('PEDLINK_RUNTIME')
    local = Path(__file__).resolve().parents[2] / 'work/runtime'
    if not prepared and sys.prefix == sys.base_prefix and local.is_dir():
        prepared = str(local)
    if prepared:
        folder = Path(prepared).resolve()
        if not folder.is_dir():
            raise RuntimeError('PEDLINK_RUNTIME must point to an installed package directory')
        sys.path.insert(0, str(folder))
    if os.name == 'nt':
        # Optional explicit DLL directory for an externally supplied runtime.
        dlls = os.getenv('PEDLINK_DLL_DIR')
        bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin'
        if not dlls and (bundled / 'msvcp140.dll').is_file():
            dlls = str(bundled)
        if dlls:
            folder = Path(dlls).resolve()
            os.environ['PATH'] = str(folder) + os.pathsep + os.environ.get('PATH', '')
            HANDLES.append(os.add_dll_directory(str(folder)))
