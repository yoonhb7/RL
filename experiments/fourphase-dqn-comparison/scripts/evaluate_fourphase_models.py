"""Evaluate frozen DQN/Double/Dueling and fixed-time on 15 common held-out cases."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT

sys.path.insert(0, str(ROOT))
from src.agents.fourphase_testing import prepare_test, replot_test, run_test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs=3, type=Path, default=[Path(f"results/fourphase_dqn/{name}_seed42") for name in ("main", "double", "dueling")])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report-only", type=Path, help="Regenerate reports from a completed cached test; no SUMO or model inference")
    args = parser.parse_args()
    if args.report_only:
        folder = (ROOT / args.report_only).resolve()
        if args.output or not folder.is_relative_to(ROOT / "results") or folder == ROOT / "results":
            parser.error("Use --report-only with an existing test folder under results/ and no --output")
        report = replot_test(folder)
    else:
        folders = [(ROOT / path).resolve() for path in args.runs]
        if any(not path.is_relative_to(ROOT / "results") or path == ROOT / "results" for path in folders):
            parser.error("Choose completed runs under results/")
        prepared = prepare_test(folders)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        folder = (ROOT / args.output).resolve() if args.output else ROOT / "results/fourphase_dqn" / f"test_seed{prepared[0]['manifest']['config']['seed']}_{stamp}"
        if not folder.is_relative_to(ROOT / "results") or folder == ROOT / "results" or folder.exists():
            parser.error("Choose a new output folder under results/; existing results are preserved")
        print("독립 평가: 4개 제어기 × 교통량 3개 × 배차 시드 5개 = 60회", flush=True)
        print("Linux headless SUMO 사용. Mac GUI/SSH 터널은 필요 없습니다.", flush=True)
        report = run_test(prepared, folder)
    print("단일 학습 시드의 독립 수요 예비 평가 J (낮을수록 좋음):")
    for controller, score in report["J_equal_level_mean"].items():
        print(f"  {controller}: {score:.4f}")
    print(f"결과·그래프·실행 기록: {folder}")


if __name__ == "__main__":
    main()
