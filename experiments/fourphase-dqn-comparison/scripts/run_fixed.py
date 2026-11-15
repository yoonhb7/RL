"""Run the toy fixed-time plan through TraCI and save auditable measurements."""

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import socket
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from common import CONFIG_PATH, DIRECTIONS, ROOT, TOY, binary, read_config

sys.path.insert(0, str(ROOT))
import traci
from src.traffic.metrics import summarize


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, help="SUMO dynamics seed; does not regenerate vehicle demand")
    parser.add_argument("--duration", type=int, help="Override simulation horizon in seconds")
    parser.add_argument("--output", type=Path, help="New result folder (default: seed and UTC timestamp)")
    args = parser.parse_args()
    config = read_config()
    seed = config["seed"] if args.seed is None else args.seed
    end = config["duration_seconds"] if args.duration is None else args.duration
    warmup = config["warmup_seconds"]
    if end <= warmup:
        parser.error("duration must exceed the configured warmup")
    for filename in ("toy.net.xml", "toy.rou.xml", "demand.json"):
        if not (TOY / filename).is_file():
            parser.error("Run scripts/build_toy.py first")
    # Fail clearly before starting SUMO if this execution environment blocks local sockets.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    relative_output = args.output or Path(f"results/fixed/seed_{seed}_{stamp}")
    output = (ROOT / relative_output).resolve()
    if not output.is_relative_to(ROOT):
        parser.error("Output must be inside the project folder")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error("Output folder is not empty; choose a new --output to preserve the previous run")
    schedule = {v.attrib["id"]: float(v.attrib["depart"]) for v in ET.parse(TOY / "toy.rou.xml").iter("vehicle")}
    input_names = ("toy.net.xml", "toy.rou.xml", "toy.sumocfg", "demand.json")
    for name in input_names:
        (output / name).write_bytes((TOY / name).read_bytes())
    (output / "config.json").write_bytes(CONFIG_PATH.read_bytes())
    command = [
        binary("sumo"), "-c", str(output / "toy.sumocfg"),
        "--seed", str(seed), "--end", str(end),
        "--step-length", str(config["step_length_seconds"]), "--route-steps", "0",
        "--tripinfo-output", str(output / "tripinfo.xml"),
        "--tripinfo-output.write-unfinished", "true",
        "--summary-output", str(output / "sumo_summary.xml"),
        "--log", str(output / "sumo.log"), "--no-step-log", "true",
        "--duration-log.disable", "true",
    ]
    fields = ["time_seconds", "step_seconds", "measured", "phase_index", "signal_state",
              "network_vehicles", "network_halting", "departed_step", "arrived_step"]
    fields += [f"{direction}_halting" for direction in DIRECTIONS]
    samples = []
    safety = {"collision_vehicle_events": 0, "teleport_starts": 0, "signal_constraint_violations": 0}
    signal_changes = 0
    previous_phase = None
    previous_change_time = None
    traci.start(command, numRetries=2)
    try:
        sumo_version = traci.getVersion()
        if set(traci.trafficlight.getIDList()) != {"center"}:
            raise RuntimeError("Expected exactly one traffic light")
        links = traci.trafficlight.getControlledLinks("center")
        for index, direction in enumerate(DIRECTIONS):
            if len(links[index]) != 1 or links[index][0][0] != f"{direction}_in_0":
                raise RuntimeError("Traffic light link order differs from the explicit phase definition")
        programs = traci.trafficlight.getAllProgramLogics("center")
        program = next(p for p in programs if p.programID == "fixed")
        expected = [(30, "GGrr"), (3, "yyrr"), (1, "rrrr"), (30, "rrGG"), (3, "rryy"), (1, "rrrr")]
        if [(p.duration, p.state) for p in program.phases] != expected:
            raise RuntimeError("Unexpected fixed signal program")
        lanes = traci.lane.getIDList()
        with (output / "queues.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            while traci.simulation.getTime() < end:
                traci.simulationStep()
                time = traci.simulation.getTime()
                phase = traci.trafficlight.getPhase("center")
                state = traci.trafficlight.getRedYellowGreenState("center")
                if previous_phase is None:
                    previous_phase, previous_change_time = phase, time
                elif phase != previous_phase:
                    signal_changes += 1
                    if phase != (previous_phase + 1) % len(expected) or time - previous_change_time != expected[previous_phase][0]:
                        safety["signal_constraint_violations"] += 1
                    previous_phase, previous_change_time = phase, time
                safety["collision_vehicle_events"] += traci.simulation.getCollidingVehiclesNumber()
                safety["teleport_starts"] += traci.simulation.getStartingTeleportNumber()
                row = {
                    "time_seconds": time, "step_seconds": config["step_length_seconds"],
                    "measured": int(time > warmup), "phase_index": phase, "signal_state": state,
                    "network_vehicles": traci.vehicle.getIDCount(),
                    "network_halting": sum(traci.lane.getLastStepHaltingNumber(lane) for lane in lanes),
                    "departed_step": traci.simulation.getDepartedNumber(),
                    "arrived_step": traci.simulation.getArrivedNumber(),
                }
                row.update({f"{d}_halting": traci.lane.getLastStepHaltingNumber(f"{d}_in_0") for d in DIRECTIONS})
                samples.append(row)
                writer.writerow(row)
        active_at_end = traci.vehicle.getIDCount()
    finally:
        traci.close()

    report = summarize(schedule, output / "tripinfo.xml", samples, warmup, end)
    counts = report["counts"]
    checks = {
        "vehicle_accounting": counts["scheduled_total"] == counts["arrived"] + counts["unfinished"] + counts["not_departed_due"] + counts["scheduled_after_end"],
        "active_matches_unfinished": active_at_end == counts["unfinished"],
        "departures_match_tripinfo": sum(row["departed_step"] for row in samples) == counts["departed"],
        "arrivals_match_tripinfo": sum(row["arrived_step"] for row in samples) == counts["arrived"],
        "no_collision_teleport_or_signal_violation": not any(safety.values()),
    }
    report.update({
        "controller": "fixed-time", "seed": seed, "warmup_seconds": warmup, "end_seconds": end,
        "demand_seed": json.loads((output / "demand.json").read_text())["seed"],
        "python_version": platform.python_version(), "sumo_version": sumo_version,
        "packages": {name: importlib.metadata.version(name) for name in ("eclipse-sumo", "sumo-data", "traci", "sumolib")},
        "input_sha256": {name: sha256(output / name) for name in (*input_names, "config.json")},
        "command": command, "signal_changes": signal_changes, "safety": safety, "checks": checks,
    })
    (output / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    with (output / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        flat = {"controller": "fixed-time", "seed": seed, **counts, **report["metrics"], **safety}
        writer = csv.DictWriter(handle, fieldnames=list(flat))
        writer.writeheader()
        writer.writerow(flat)
    print(json.dumps(report, indent=2))
    if not all(checks.values()):
        raise RuntimeError("Simulation validation failed; see metrics.json")


if __name__ == "__main__":
    main()
