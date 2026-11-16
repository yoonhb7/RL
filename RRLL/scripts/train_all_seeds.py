"""Train every algorithm with every training seed, several runs at a time.

Each run is an independent `train_fourphase_dqn.py` process writing to
results/fourphase_dqn/<algorithm>_seed<seed>/ and logging to <that folder>.log.
Runs whose output folder already exists are skipped, so an interrupted batch can be restarted.
Activate the project environment first (conda activate fourphase-py310) so SUMO is on PATH.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from common import ROOT

ALGORITHMS = ("dqn", "double_dqn", "dueling_dqn")


def main():
    config = json.loads((ROOT / "configs/fourphase_dqn.json").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--algorithms", nargs="+", choices=ALGORITHMS, default=list(ALGORITHMS))
    parser.add_argument("--seeds", nargs="+", type=int, default=config["training_seeds"])
    parser.add_argument("--episodes", type=int, help="Default: episodes in configs/fourphase_dqn.json")
    parser.add_argument("--parallel", type=int, default=5, help="Simultaneous runs (default 5; one SUMO + one CPU thread each)")
    parser.add_argument("--dry-run", action="store_true", help="Only print the planned runs")
    args = parser.parse_args()

    jobs, skipped = [], []
    for seed in args.seeds:  # Seed-major order: all algorithms of one seed finish close together.
        for algorithm in args.algorithms:
            output = Path("results/fourphase_dqn") / f"{algorithm}_seed{seed}"
            if (ROOT / output).exists():
                skipped.append(str(output))
                continue
            command = [sys.executable, str(ROOT / "scripts/train_fourphase_dqn.py"), "--algorithm", algorithm,
                       "--seed", str(seed), "--output", str(output)]
            if args.episodes:
                command += ["--episodes", str(args.episodes)]
            jobs.append((f"{algorithm}_seed{seed}", output, command))

    print(f"예정 {len(jobs)}회, 이미 있어 건너뜀 {len(skipped)}회, 동시 실행 {args.parallel}개", flush=True)
    for name in skipped:
        print(f"  건너뜀(폴더 있음): {name}", flush=True)
    if args.dry_run:
        for name, _, command in jobs:
            print(f"  {name}: {' '.join(command)}")
        return 0

    running, results, started = [], {}, time.monotonic()
    pending = list(jobs)
    while pending or running:
        while pending and len(running) < args.parallel:
            name, output, command = pending.pop(0)
            log = (ROOT / output).with_suffix(".log")
            log.parent.mkdir(parents=True, exist_ok=True)
            stream = log.open("w", encoding="utf-8")
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            running.append((name, process, stream))
            print(f"[{time.monotonic() - started:7.0f}s] 시작: {name} (기록: {log.relative_to(ROOT)})", flush=True)
        time.sleep(5)
        for item in list(running):
            name, process, stream = item
            if process.poll() is not None:
                stream.close()
                running.remove(item)
                results[name] = process.returncode
                status = "완료" if process.returncode == 0 else f"실패(코드 {process.returncode})"
                print(f"[{time.monotonic() - started:7.0f}s] {status}: {name}", flush=True)

    failed = [name for name, code in results.items() if code != 0]
    print(f"\n전체 {len(results)}회 중 완료 {len(results) - len(failed)}회, 실패 {len(failed)}회", flush=True)
    for name in failed:
        print(f"  실패: {name} -> results/fourphase_dqn/{name}.log", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
