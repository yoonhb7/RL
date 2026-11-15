"""Immutable scenario splits and metadata for the first DQN experiment."""

import hashlib
import json
import shutil
from pathlib import Path

from src.traffic.demand_builder import write_demand


ROOT = Path(__file__).resolve().parents[2]
SPLITS = ("train", "validation", "test")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_splits(config):
    used = set()
    for split in SPLITS:
        values = config[f"{split}_demand_seeds"]
        if not values or any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
            raise ValueError(f"{split} seeds must be a nonempty list of nonnegative integers")
        if len(set(values)) != len(values) or used.intersection(values):
            raise ValueError("Train, validation and test demand seeds must be disjoint and unique")
        used.update(values)


def prepare_run(folder, training_config, env_settings):
    folder = Path(folder).resolve()
    if folder.exists() and any(folder.iterdir()):
        raise ValueError("결과 폴더가 비어 있지 않습니다. 새로운 --output을 지정하세요")
    validate_splits(training_config)
    source = ROOT / "sumo" / "toy"
    if not (source / "toy.net.xml").is_file():
        raise FileNotFoundError("scripts/build_toy.py를 먼저 실행하세요")
    traffic = json.loads((ROOT / "configs" / "toy.json").read_text(encoding="utf-8"))
    folder.mkdir(parents=True, exist_ok=True)
    cases = {}
    for split in SPLITS:
        cases[split] = []
        for seed in training_config[f"{split}_demand_seeds"]:
            case_folder = folder / "scenarios" / split / f"seed_{seed}"
            case_folder.mkdir(parents=True)
            for name in ("toy.net.xml", "toy.sumocfg"):
                shutil.copy2(source / name, case_folder / name)
            metadata = write_demand(case_folder, traffic, seed)
            cases[split].append({
                "demand_seed": seed, "sumo_seed": seed, "vehicle_count": metadata["vehicle_count"],
                "config": str((case_folder / "toy.sumocfg").relative_to(folder)),
                "routes": str((case_folder / "toy.rou.xml").relative_to(folder)),
                "sha256": {name: sha256(case_folder / name) for name in ("toy.net.xml", "toy.sumocfg", "toy.rou.xml", "demand.json")},
            })
    manifest = {
        "schema_version": 1, "algorithm": "vanilla DQN", "data_source": "synthetic toy intersection",
        "training_config": training_config, "env_settings": env_settings, "traffic_config": traffic,
        "observation_size": 16, "actions": {"0": "hold", "1": "request_switch"}, "cases": cases,
    }
    write_json(folder / "manifest.json", manifest)
    return manifest


def case_paths(folder, case):
    folder = Path(folder).resolve()
    config = (folder / case["config"]).resolve()
    routes = (folder / case["routes"]).resolve()
    if not config.is_relative_to(folder) or not routes.is_relative_to(folder):
        raise ValueError("Scenario paths must be inside the experiment folder")
    for name, digest in case["sha256"].items():
        if sha256(config.parent / name) != digest:
            raise ValueError(f"고정한 실험 입력 파일이 변경되었습니다: {config.parent / name}")
    return config, routes
