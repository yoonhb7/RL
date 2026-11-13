"""Fast native-process preflight: report the real exit code before TraCI retries."""
from pathlib import Path
import argparse
import json
import os
import runpy
import subprocess
import sys
from start import ROOT, configure_windows_runtime


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--gui',action='store_true')
    args=parser.parse_args()
    dll_dirs=configure_windows_runtime()
    runpy.run_path(str(ROOT/'run.py'),run_name='runtime_bootstrap')
    from trafficbench.scenario import binary
    from trafficbench.common import write_json
    exe=binary('sumo-gui' if args.gui else 'sumo')
    print('Checking SUMO native runtime...',flush=True)
    try:
        p=subprocess.run([exe,'--version'],capture_output=True,text=True,errors='replace',timeout=10)
        result=dict(binary=exe,dll_directories=dll_dirs,exit_code=p.returncode,
                    exit_hex=f'0x{p.returncode & 0xffffffff:08X}',stdout=p.stdout,stderr=p.stderr)
    except Exception as exc:
        result=dict(binary=exe,dll_directories=dll_dirs,error=repr(exc),exit_code=None)
    write_json(ROOT/'results/runtime-check.json',result)
    if result['exit_code']!=0:
        print(json.dumps(result,indent=2),flush=True)
        if result.get('exit_hex')=='0xC0000135':
            print('Windows could not load a required native DLL (including vcomp140.dll).',flush=True)
            print('Use RUN_HERE.ps1 with the prepared runtime, or install the official Microsoft VC++ x64 runtime.',flush=True)
        print('Startup stopped before TraCI. Details: results/runtime-check.json',flush=True)
        return 1
    print(result['stdout'].splitlines()[0],flush=True)
    print('Native runtime OK.',flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
