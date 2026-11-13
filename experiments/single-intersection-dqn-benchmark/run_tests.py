"""Run analytic checks and real SUMO integration checks with the same runtime bootstrap."""
from pathlib import Path
import runpy
import unittest
from start import configure_windows_runtime

ROOT=Path(__file__).resolve().parent
configure_windows_runtime()
runpy.run_path(str(ROOT/'run.py'),run_name='trafficbench_bootstrap')
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
result=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
