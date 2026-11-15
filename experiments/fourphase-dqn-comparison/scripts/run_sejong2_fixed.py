"""Measure the two-junction native fixed plan with immutable input snapshots."""

import argparse
import csv
import json
import math
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT, binary

sys.path.insert(0, str(ROOT))
from src.traffic.metrics import summarize
from src.traffic.sejong_network import digest, expected_fixed_phase, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=Path("sumo/sejong2"))
    parser.add_argument("--seed", type=int, help="SUMO seed; demand remains frozen")
    parser.add_argument("--output", type=Path, help="New result folder inside this project")
    args = parser.parse_args()
    source = (ROOT / args.scenario).resolve()
    if not source.is_relative_to(ROOT) or not (source / "manifest.json").is_file():
        parser.error("Build a scenario first: .venv/bin/python scripts/build_sejong2.py")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files_sha256"].items():
        path = (source / name).resolve()
        if not path.is_relative_to(source) or digest(path) != expected:
            parser.error(f"Frozen scenario input changed: {name}")
    config = manifest["config"]
    seed = config["seed"] if args.seed is None else args.seed
    if seed < 0:
        parser.error("seed must be nonnegative")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = (ROOT / (args.output or Path(f"results/sejong2/fixed_seed_{seed}_{stamp}"))).resolve()
    if not output.is_relative_to(ROOT / "results"):
        parser.error("Output must be a new folder under results/")
    if output.exists() and any(output.iterdir()):
        parser.error("Output is not empty; choose a new --output")
    import traci
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, output / "scenario")
    scenario = output / "scenario"
    schedule = {v.attrib["id"]: float(v.attrib["depart"])
                for v in ET.parse(scenario / "sejong.rou.xml").iter("vehicle")}
    inventory = json.loads((scenario / "network_inventory.json").read_text(encoding="utf-8"))["junctions"]
    plans = {item["id"]: item for item in inventory}
    warmup, end = config["warmup_seconds"], config["duration_seconds"]
    command = [binary("sumo"), "-c", str(scenario / "sejong.sumocfg"), "--seed", str(seed),
               "--route-steps", "0", "--tripinfo-output", str(output / "tripinfo.xml"),
               "--tripinfo-output.write-unfinished", "true", "--summary-output", str(output / "summary.xml"),
               "--collision-output", str(output / "collisions.xml"),
               "--log", str(output / "sumo.log"), "--no-step-log", "true", "--duration-log.disable", "true"]
    write_json(output / "run.json", {"status": "started", "controller": "assumed native fixed-time",
               "seed": seed, "command": command, "source_manifest_sha256": digest(source / "manifest.json")})
    safety = {"collision_vehicle_events": 0, "teleport_starts": 0, "signal_constraint_violations": 0}
    samples, violations = [], []
    fields = ["time_seconds", "step_seconds", "measured", "network_vehicles", "network_halting",
              "departed_step", "arrived_step"]
    for signal_id in plans:
        fields.extend([f"{signal_id}_phase", f"{signal_id}_state", f"{signal_id}_inbound_halting",
                       f"{signal_id}_expected_phase", f"{signal_id}_phase_elapsed_s"])
    traci.start(command, numRetries=2)
    try:
        version = traci.getVersion()
        if set(traci.trafficlight.getIDList()) != set(plans):
            raise ValueError("Running signals differ from the two-junction manifest")
        for signal_id, plan in plans.items():
            logic = next(p for p in traci.trafficlight.getAllProgramLogics(signal_id)
                         if p.programID == traci.trafficlight.getProgram(signal_id))
            actual = [(float(p.duration), p.state) for p in logic.phases]
            expected = [(p["duration"], p["state"]) for p in plan["phases"]]
            if actual != expected:
                raise ValueError(f"Running fixed plan differs from manifest: {signal_id}")
        lanes = tuple(traci.lane.getIDList())
        with (output / "queues.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            while traci.simulation.getTime() < end:
                before = traci.simulation.getTime()
                traci.simulationStep()
                now = traci.simulation.getTime()
                if not math.isclose(now - before, 1.0, abs_tol=1e-7):
                    raise ValueError("Expected exactly one simulated second per sample")
                row = {"time_seconds": now, "step_seconds": 1, "measured": int(now > warmup),
                       "network_vehicles": traci.vehicle.getIDCount(),
                       "network_halting": sum(traci.lane.getLastStepHaltingNumber(lane) for lane in lanes),
                       "departed_step": traci.simulation.getDepartedNumber(),
                       "arrived_step": traci.simulation.getArrivedNumber()}
                safety["collision_vehicle_events"] += traci.simulation.getCollidingVehiclesNumber()
                safety["teleport_starts"] += traci.simulation.getStartingTeleportNumber()
                for signal_id, plan in plans.items():
                    phase = traci.trafficlight.getPhase(signal_id)
                    state = traci.trafficlight.getRedYellowGreenState(signal_id)
                    elapsed = traci.trafficlight.getSpentDuration(signal_id)
                    # SUMO evaluates the TLS at the beginning of this physical
                    # step. In particular, the first offset phase is partial;
                    # getSpentDuration must not be compared to its full length.
                    expected_phase = expected_fixed_phase(before, plan["phases"], plan["offset_s"])
                    expected_state = plan["phases"][expected_phase]["state"]
                    if phase != expected_phase or state != expected_state:
                        safety["signal_constraint_violations"] += 1
                        violations.append({"time_seconds": now, "signal_id": signal_id,
                                           "expected_phase": expected_phase, "actual_phase": phase,
                                           "expected_state": expected_state, "actual_state": state,
                                           "observed_elapsed_s": elapsed})
                    row.update({f"{signal_id}_phase": phase, f"{signal_id}_state": state,
                                f"{signal_id}_inbound_halting": sum(traci.lane.getLastStepHaltingNumber(lane)
                                                                    for lane in plan["incoming_lanes"]),
                                f"{signal_id}_expected_phase": expected_phase,
                                f"{signal_id}_phase_elapsed_s": elapsed})
                samples.append(row)
                writer.writerow(row)
        active_at_end = traci.vehicle.getIDCount()
        # Preserve the location and intended next road of the longest-stopped
        # vehicles. This is diagnostic data, never a reason to ignore congestion.
        blocked = []
        for vehicle_id in traci.vehicle.getIDList():
            route = traci.vehicle.getRoute(vehicle_id)
            index = traci.vehicle.getRouteIndex(vehicle_id)
            blocked.append({"id": vehicle_id, "lane": traci.vehicle.getLaneID(vehicle_id),
                            "road": traci.vehicle.getRoadID(vehicle_id), "speed_m_s": traci.vehicle.getSpeed(vehicle_id),
                            "continuous_waiting_s": traci.vehicle.getWaitingTime(vehicle_id),
                            "route_index": index, "route": list(route),
                            "next_edge": route[index + 1] if 0 <= index + 1 < len(route) else None})
        write_json(output / "blocked_vehicles.json", sorted(blocked, key=lambda item: -item["continuous_waiting_s"])[:30])
    except Exception as error:
        write_json(output / "failure.json", {"type": type(error).__name__, "message": str(error)})
        raise
    finally:
        traci.close()
    report = summarize(schedule, output / "tripinfo.xml", samples, warmup, end)
    write_json(output / "signal_violations.json", violations)
    counts = report["counts"]
    checks = {
        "vehicle_accounting": counts["scheduled_total"] == counts["arrived"] + counts["unfinished"]
                              + counts["not_departed_due"] + counts["scheduled_after_end"],
        "active_matches_unfinished": active_at_end == counts["unfinished"],
        "departures_match_tripinfo": sum(row["departed_step"] for row in samples) == counts["departed"],
        "arrivals_match_tripinfo": sum(row["arrived_step"] for row in samples) == counts["arrived"],
        "no_collision_teleport_or_signal_violation": not any(safety.values()),
    }
    report.update({"controller": "assumed fixed-time; not observed real signal plans", "seed": seed,
                   "sumo_version": version, "warmup_seconds": warmup, "end_seconds": end,
                   "safety": safety, "checks": checks, "limitations": config["limitations"],
                   "source_manifest_sha256": digest(source / "manifest.json")})
    write_json(output / "metrics.json", report)
    with (output / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        flat = {"controller": "assumed fixed-time", "seed": seed, **counts, **report["metrics"], **safety}
        writer = csv.DictWriter(handle, fieldnames=list(flat))
        writer.writeheader()
        writer.writerow(flat)
    write_json(output / "run.json", {"status": "completed" if all(checks.values()) else "validation_failed",
               "controller": "assumed native fixed-time", "seed": seed, "command": command,
               "source_manifest_sha256": digest(source / "manifest.json")})
    print(json.dumps({"output": str(output), **report}, indent=2, ensure_ascii=False))
    if not all(checks.values()):
        raise RuntimeError("Baseline validation failed; see metrics.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
