"""Portable environment setup. Optional external package directory is explicit."""
import os
import sys
from pathlib import Path

HANDLES = []

def configure():
    prepared = os.getenv('PEDLINK_RUNTIME')
    if prepared:
        folder = Path(prepared).resolve()
        if not folder.is_dir():
            raise RuntimeError('PEDLINK_RUNTIME must point to an installed package directory')
        sys.path.insert(0, str(folder))
    if os.name == 'nt':
        # Optional explicit DLL directory for an externally supplied runtime.
        dlls = os.getenv('PEDLINK_DLL_DIR')
        if dlls:
            folder = Path(dlls).resolve()
            os.environ['PATH'] = str(folder) + os.pathsep + os.environ.get('PATH', '')
            HANDLES.append(os.add_dll_directory(str(folder)))
