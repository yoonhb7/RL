"""Immutable per-run departure files, balanced episode order and disjoint splits."""

import json
import math
import random
import shutil
from collections import Counter
from pathlib import Path

from src.traffic.experiments import ROOT, sha256, write_json
from src.traffic.fourphase.scenario import OBSERVATION_SIZE, verify_scenario, write_configuration, write_demand


LEVELS = ("low", "medium", "high")
ALGORITHMS = ("dqn", "double_dqn", "dueling_dqn")


def read_config(path=None, *, episodes=None, seed=None, device=None, algorithm=None):
    config = json.loads(Path(path or ROOT / "configs/fourphase_dqn.json").read_text(encoding="utf-8"))
    for key, override in (("episodes", episodes), ("seed", seed), ("device", device), ("algorithm", algorithm)):
        if override is not None:
            config[key] = override
    if config["algorithm"] not in ALGORITHMS or config["hidden_sizes"] != [128, 64]:
        raise ValueError("Choose DQN/Double/pure Dueling with the agreed shared observation-128-64 feature layers")
    for key in ("episodes", "buffer_size", "batch_size", "learning_starts", "target_update_decisions",
                "validation_every_episodes", "torch_threads"):
        if type(config[key]) is not int or config[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    for key in ("seed", "train_demand_seed_start"):
        if type(config[key]) is not int or not 0 <= config[key] < 2**31:
            raise ValueError(f"{key} must be an integer in [0, 2**31)")
    if config["buffer_size"] < max(config["batch_size"], config["learning_starts"]):
        raise ValueError("Replay capacity must cover the initial collection and minibatch")
    for key in ("learning_rate", "gamma", "epsilon_initial", "epsilon_final", "epsilon_fraction"):
        if isinstance(config[key], bool) or not math.isfinite(config[key]):
            raise ValueError(f"{key} must be finite")
    if config["learning_rate"] <= 0 or not 0 < config["gamma"] <= 1 or not 0 < config["epsilon_fraction"] <= 1:
        raise ValueError("Invalid learning rate, gamma or epsilon fraction")
    if not 0 <= config["epsilon_final"] <= config["epsilon_initial"] <= 1:
        raise ValueError("Expected 0 <= final epsilon <= initial epsilon <= 1")
    split_seeds(config)
    return config


def split_seeds(config):
    groups = {"train": list(range(config["train_demand_seed_start"],
                                   config["train_demand_seed_start"] + config["episodes"])),
              "validation": config["validation_demand_seeds"]}
    used = {42}  # The road pilot demand is not an independent validation case.
    for split, values in groups.items():
        if not values or any(type(v) is not int or not 0 <= v < 2**31 for v in values):
            raise ValueError(f"Invalid {split} demand seeds")
        if len(set(values)) != len(values) or used.intersection(values):
            raise ValueError("Demand splits must be unique, disjoint and exclude pilot seed 42")
        used.update(values)
    return groups


def episode_order(config):
    rng = random.Random(config["seed"])
    levels = [LEVELS[i % 3] for i in range(config["episodes"])]
    rng.shuffle(levels)
    return [{"episode": i + 1, "level": level, "demand_seed": config["train_demand_seed_start"] + i}
            for i, level in enumerate(levels)]


def prepare_run(folder, source, config):
    folder, source = Path(folder).resolve(), Path(source).resolve()
    base = verify_scenario(source)
    settings = base["settings"]
    if settings["duration_seconds"] != 3600:
        raise ValueError("Research runs require the full 3600-second external time limit")
    if folder.exists():
        raise ValueError("Use a new results folder; existing runs are preserved")
    groups = split_seeds(config)
    if settings["pilot_seed"] in set().union(*(set(v) for v in groups.values())):
        raise ValueError("Do not reuse the source road pilot demand in the learning experiment splits")
    folder.mkdir(parents=True)
    shutil.copy2(source / "network.net.xml", folder / "network.net.xml")
    shutil.copy2(source / "view.xml", folder / "view.xml")
    write_json(folder / "env_settings.json", settings)
    write_json(folder / "training_config.json", config)
    order = episode_order(config)
    cases = {"train": [], "validation": []}

    def make(split, level, seed, name, episode=None):
        relative = Path("scenarios") / split / name  # Three levels below shared network.net.xml.
        case = folder / relative
        case.mkdir(parents=True)
        demand = write_demand(case, settings, level, seed)
        write_configuration(case, settings, seed)
        record = {"id": name, "level": level, "demand_seed": seed, "sumo_seed": seed,
                  "folder": str(relative), "scheduled_due": demand["scheduled_due"], "episode": episode,
                  "sha256": {p.name: sha256(p) for p in sorted(case.iterdir()) if p.is_file()}}
        cases[split].append(record)

    for item in order:
        make("train", item["level"], item["demand_seed"], f"episode_{item['episode']:04d}", item["episode"])
    for split in ("validation",):
        for level in LEVELS:
            for seed in groups[split]:
                make(split, level, seed, f"{level}_seed_{seed}")
    manifest = {"schema_version": 1, "kind": "fourphase_masked_dqn_v1", "algorithm": config["algorithm"],
                "config": config, "env_settings": settings, "cases": cases, "episode_order": order,
                "training_level_counts": dict(Counter(item["level"] for item in order)),
                "observation_size": OBSERVATION_SIZE, "actions": {"0": "hold", "1": "next_phase"},
                "source_manifest_sha256": sha256(source / "manifest.json"),
                "network_sha256": sha256(folder / "network.net.xml"),
                "view_sha256": sha256(folder / "view.xml"),
                "selection": "minimum equally weighted validation ATT; earliest checkpoint on ties"}
    write_json(folder / "manifest.json", manifest)
    return manifest


def case_path(folder, manifest, case):
    folder = Path(folder).resolve()
    path = (folder / case["folder"]).resolve()
    if not path.is_relative_to(folder) or sha256(folder / "network.net.xml") != manifest["network_sha256"]:
        raise ValueError("Case path/network differs from the frozen run")
    for name, expected in case["sha256"].items():
        candidate = (path / name).resolve()
        if not candidate.is_relative_to(path) or sha256(candidate) != expected:
            raise ValueError(f"Frozen case input changed: {candidate}")
    return path
