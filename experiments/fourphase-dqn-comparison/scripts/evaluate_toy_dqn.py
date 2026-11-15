"""Compare a validation-selected DQN and native fixed time on unseen paired cases."""

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

from common import ROOT

sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="Completed training experiment folder")
    parser.add_argument("--output", type=Path, help="New evaluation folder (default: RUN/evaluation)")
    args = parser.parse_args()
    try:
        from stable_baselines3 import DQN
        from src.agents.evaluation import run_episode
        from src.agents.plots import plot_comparison
        from src.traffic.experiments import sha256, write_json
    except ModuleNotFoundError as error:
        print(f"평가 패키지가 없습니다: {error.name}. requirements-dqn.txt를 설치하세요.", file=sys.stderr)
        return 1
    folder = (ROOT / args.run).resolve()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    training = json.loads((folder / "training_summary.json").read_text(encoding="utf-8"))
    if training["status"] != "completed":
        parser.error("정상 완료된 학습 실행을 평가해야 합니다")
    output = (ROOT / args.output).resolve() if args.output else folder / "evaluation"
    if not output.is_relative_to(ROOT):
        parser.error("결과는 프로젝트 폴더 안에 저장해야 합니다")
    if output.exists():
        parser.error("평가 폴더가 이미 있습니다. 새로운 --output을 지정하세요")
    output.mkdir(parents=True)
    model = DQN.load(str(folder / "best_model.zip"), device="cpu")
    rows = []
    for case in manifest["cases"]["test"]:
        for method in ("fixed", "dqn"):
            print(f"[평가] {method} demand_seed={case['demand_seed']}", flush=True)
            report = run_episode(
                folder, case, manifest["env_settings"], model=model if method == "dqn" else None,
                mode="agent" if method == "dqn" else "fixed", output=output / f"seed_{case['demand_seed']}" / method,
            )
            rows.append({"method": method, "demand_seed": case["demand_seed"], "sumo_seed": case["sumo_seed"],
                         **report["counts"], **report["metrics"], "episode_return": report["episode_return"]})
    with (output / "comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {}
    for method in ("fixed", "dqn"):
        records = [row for row in rows if row["method"] == method]
        waiting = [row["cohort_mean_waiting_observed_s"] for row in records]
        if any(value is None for value in waiting):
            raise RuntimeError("출발한 분석 차량이 없어 평균 대기시간을 계산할 수 없습니다. 원시 결과를 확인하세요")
        summary[method] = {
            "n_cases": len(records), "waiting_mean_s": statistics.fmean(waiting),
            "waiting_std_s": statistics.stdev(waiting) if len(waiting) > 1 else 0.0,
            "throughput_mean": statistics.fmean(row["arrived_during_measurement"] for row in records),
            "unfinished_mean": statistics.fmean(row["unfinished"] for row in records),
            "pending_mean": statistics.fmean(row["not_departed_due"] for row in records),
        }
    comparable = all(row["cohort_unfinished"] == 0 and row["cohort_not_departed"] == 0 for row in rows)
    base = summary["fixed"]["waiting_mean_s"]
    summary["waiting_reduction_percent"] = 100 * (base - summary["dqn"]["waiting_mean_s"]) / base if comparable and base > 0 else None
    summary["all_cohort_trips_completed"] = comparable
    summary["model"] = "best_model.zip (selected using validation cases only)"
    summary["model_sha256"] = sha256(folder / "best_model.zip")
    write_json(output / "summary.json", summary)
    plot_comparison(output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("결과표:", output / "comparison.csv")
    print("비교 그래프:", output / "comparison.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
