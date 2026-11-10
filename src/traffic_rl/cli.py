from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path
import platform
import subprocess

from .common import binary, run_command
from .scenario import build


def main():
    parser = argparse.ArgumentParser(description="SUMO centralized single-agent DQN baseline")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check Python, packages and SUMO binaries")
    inventory = sub.add_parser("inspect", help="Export actual signal links and saved programs from a SUMO network")
    inventory.add_argument("--net", required=True)
    inventory.add_argument("--out", default="data/processed/network-inventory.json")
    b = sub.add_parser("build", help="Generate a straight-only synthetic network and demand")
    b.add_argument("--config", default="configs/toy.json")
    b.add_argument("--out", default="sumo/toy")
    t = sub.add_parser("train")
    t.add_argument("--scenario", default="sumo/toy")
    t.add_argument("--out", default="results/local/toy-train")
    t.add_argument("--episodes", type=int, default=50)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--double", action="store_true")
    for name in ["evaluate", "view"]:
        e = sub.add_parser(name)
        e.add_argument("--scenario", default="sumo/toy")
        e.add_argument("--model")
        e.add_argument("--out", default=f"results/local/{name}")
        e.add_argument("--seeds", nargs="+", type=int, default=[1001, 1002, 1003, 1004, 1005])
        e.add_argument("--controllers", nargs="+", choices=["fixed", "queue", "dqn", "native"], default=["fixed", "queue"])
        e.add_argument("--scale", type=float, default=1.0)
        if name == "view":
            e.add_argument("--delay", type=int, default=1000, help="GUI milliseconds per simulated second")
    args = parser.parse_args()
    if args.command == "doctor":
        print("Python:", platform.python_version())
        for name in ["eclipse-sumo", "traci", "gymnasium", "torch", "numpy", "matplotlib"]:
            print(name, importlib.metadata.version(name))
        for name in ["sumo", "netconvert", "sumo-gui", "netedit"]:
            print(name, binary(name))
        print(run_command([binary("sumo"), "--version"]).splitlines()[0])
    elif args.command == "inspect":
        from .inventory import inspect_network
        data = inspect_network(args.net, args.out)
        print(f"Found {len(data['signals'])} traffic lights. Saved: {Path(args.out).resolve()}")
    elif args.command == "build":
        manifest = build(args.config, args.out)
        print(f"Built {manifest['name']}: {len(manifest['signals'])} junction(s), {2**len(manifest['signals'])} joint actions")
    elif args.command == "train":
        from .env import CentralizedTrafficEnv
        from .dqn import train
        from .experiment import plot_training
        env = CentralizedTrafficEnv(args.scenario)
        train(env, args.out, args.episodes, args.seed, args.double)
        plot_training(args.out)
        print("Saved:", Path(args.out).resolve() / "model.pt")
    else:
        from .experiment import evaluate
        if args.command == "view" and (len(args.seeds) != 1 or len(args.controllers) != 1):
            parser.error("view requires one --seed(s) and one --controller(s)")
        evaluate(args.scenario, args.out, args.seeds, args.controllers, args.model, args.scale, args.command == "view", getattr(args, "delay", 1000))
        print("Results:", Path(args.out).resolve())
