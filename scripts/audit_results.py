"""Audit saved per-second SUMO traces; run from the project root."""
import csv
from itertools import groupby
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    verified = root / "results/verified"
    count = signal_seconds = 0
    for scenario in ("toy", "corridor2", "corridor3"):
        evaluation = verified / f"{scenario}-evaluation"
        data = json.loads((evaluation / "evaluation.json").read_text(encoding="utf-8"))
        for seed in data["seeds"]:
            hashes = set()
            for controller in data["controllers"]:
                run = evaluation / controller / f"seed_{seed}"
                metadata = json.loads((run / "run.json").read_text(encoding="utf-8"))
                metrics = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
                assert metrics["count_balance_ok"] and metrics["tripinfo_counts_match"], run
                assert metrics["teleports"] == metrics["collision_events"] == 0, run
                hashes.add(metrics["route_sha256"])
                with (run / "trace.csv").open(encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
                horizon = metadata["manifest"]["horizon_seconds"]
                assert [int(r["time"]) for r in rows] == list(range(1, horizon + 1)), run
                for signal in metadata["manifest"]["signals"]:
                    states = [r[signal["id"] + "_state"] for r in rows]
                    blocks = [(state, len(list(items))) for state, items in groupby(states)]
                    cycle = []
                    durations = []
                    for green, yellow in zip(signal["greens"], signal["yellows"]):
                        cycle += [green, yellow, signal["all_red_state"]]
                        durations += [(signal["min_green"], signal["max_green"]), (signal["yellow"], signal["yellow"]), (signal["all_red"], signal["all_red"])]
                    for i, (state, duration) in enumerate(blocks):
                        pos = i % len(cycle)
                        assert state == cycle[pos], (run, signal["id"], i, state)
                        low, high = durations[pos]
                        if controller == "fixed" and pos % 3 == 0:
                            low = high = signal["fixed_green"]
                        assert duration <= high, (run, signal["id"], "duration too long", duration)
                        if i != len(blocks) - 1:
                            assert duration >= low, (run, signal["id"], "duration too short", duration)
                    signal_seconds += len(states)
                count += 1
            assert len(hashes) == 1, (scenario, seed, "demand mismatch")
    result = {"evaluation_runs": count, "signal_second_records": signal_seconds, "trace_order_and_signal_durations_pass": True, "vehicle_balance_pass": True, "paired_demand_hashes_pass": True, "collision_events": 0, "teleports": 0}
    (verified / "audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
