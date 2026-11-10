"""Use this chat's prepared runtime when available, otherwise normal Python."""
from pathlib import Path
import os
import runpy
import sys

project = Path(__file__).resolve().parent
prepared = project.parent.parent / "work" / "runtime"
if prepared.is_dir():
    sys.path.insert(0, str(prepared))
    # The bundled Python can rely on Visual C++ DLLs shipped beside Node.
    # Keep the change local to this process, including child SUMO processes.
    if os.name == "nt":
        candidates = [Path(sys.executable).resolve().parent.parent / "node" / "bin"]
        if os.environ.get("USERPROFILE"):
            candidates.append(Path(os.environ["USERPROFILE"]) / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin")
        _dll_directory_handles = []
        for candidate in dict.fromkeys(candidates):
            if (candidate / "msvcp140.dll").is_file():
                os.environ["PATH"] = str(candidate) + os.pathsep + os.environ.get("PATH", "")
                _dll_directory_handles.append(os.add_dll_directory(str(candidate)))
os.chdir(project)
os.environ.setdefault("MPLCONFIGDIR", str(prepared.parent / "matplotlib" if prepared.is_dir() else project / "work" / "matplotlib"))
runpy.run_path(str(project / "run.py"), run_name="__main__")
