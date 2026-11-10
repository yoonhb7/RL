from pathlib import Path
import json
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from traffic_rl.common import write_json, sha256
from traffic_rl.env import CentralizedTrafficEnv
from traffic_rl.scenario import build, generate_demand
from traffic_rl.inventory import inspect_network

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scenario(tmp_path):
    cfg = json.loads((ROOT / "configs/corridor2.json").read_text())
    cfg.update(demand_seconds=40, horizon_seconds=180)
    path = tmp_path / "config.json"
    write_json(path, cfg)
    build(path, tmp_path / "network")
    return tmp_path / "network"


@pytest.mark.parametrize("count", [1, 2, 3])
def test_generated_greens_never_serve_conflicting_movements(tmp_path, count):
    cfg = json.loads((ROOT / "configs/toy.json").read_text())
    cfg["intersections"] = count
    write_json(tmp_path / "config.json", cfg)
    manifest = build(tmp_path / "config.json", tmp_path / "network")
    net = ET.parse(tmp_path / "network/network.net.xml").getroot()
    for spec in manifest["signals"]:
        junction = next(j for j in net.findall("junction") if j.get("id") == spec["id"])
        foes = {int(r.get("index")): r.get("foes")[::-1] for r in junction.findall("request")}
        for green in spec["greens"]:
            active = [i for i, c in enumerate(green) if c in "Gg"]
            assert len(active) == 2
            for i in active:
                for j in active:
                    assert foes[i][j] == "0"


def test_same_explicit_demand_reused_and_episode_reset(scenario):
    manifest = json.loads((scenario / "manifest.json").read_text())
    a = generate_demand(scenario, manifest, 42)
    before = sha256(a)
    assert sha256(generate_demand(scenario, manifest, 42)) == before
    assert sha256(generate_demand(scenario, manifest, 43)) != before
    env = CentralizedTrafficEnv(scenario)
    try:
        first, info = env.reset(seed=42)
        assert env.observation_space.contains(first)
        for _ in range(3):
            env.step(int(np.flatnonzero(env.action_masks())[0]))
        again, info = env.reset(seed=42)
        assert env.t == 0 and env.departed == 0
        np.testing.assert_array_equal(first, again)
        assert sha256(env.route_file) == before
    finally:
        env.close()


def test_network_routes_really_run_and_conserve_vehicles(scenario, tmp_path):
    env = CentralizedTrafficEnv(scenario, controller="fixed", output=tmp_path / "run")
    try:
        obs, info = env.reset(seed=13)
        done = False
        while not done:
            obs, reward, done, truncated, info = env.step(0)
            assert env.observation_space.contains(obs)
        metrics = env.last_metrics
        assert metrics["scheduled"] > 0 and metrics["arrived"] > 0
        assert metrics["count_balance_ok"] and metrics["tripinfo_counts_match"]
        assert metrics["collision_events"] == metrics["teleports"] == 0
        assert env.connection is None
    finally:
        env.close()


def test_unfinished_and_not_departed_are_counted(tmp_path):
    cfg = json.loads((ROOT / "configs/toy.json").read_text())
    cfg.update(demand_seconds=45, horizon_seconds=50, ew_rate=10000, ns_rate=10000)
    write_json(tmp_path / "config.json", cfg)
    build(tmp_path / "config.json", tmp_path / "network")
    env = CentralizedTrafficEnv(tmp_path / "network", "fixed", output=tmp_path / "overloaded")
    try:
        env.reset(seed=12)
        done = False
        while not done:
            _, _, done, _, info = env.step(0)
        m = env.last_metrics
        assert m["unfinished"] > 0 and m["not_departed"] > 0
        assert m["pending_vehicle_seconds"] > 0
        assert m["count_balance_ok"] and m["tripinfo_counts_match"]
        assert m["tripinfo_departed_rows"] == m["arrived"] + m["unfinished"]
    finally:
        env.close()


def test_inventory_uses_final_sumo_link_indices(scenario, tmp_path):
    data = inspect_network(scenario / "network.net.xml", tmp_path / "inventory.json")
    assert len(data["signals"]) == 2
    for signal in data["signals"]:
        indices = [int(c["linkIndex"]) for c in signal["connections_by_link_index"]]
        assert indices == [0, 1, 2, 3]
        assert len(signal["lanes"]) == 4


def test_native_preserves_loaded_field_program_and_offset(scenario):
    import copy
    manifest_path = scenario / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    net = ET.parse(scenario / "network.net.xml").getroot()
    additional = ET.Element("additional")
    for logic in net.findall("tlLogic"):
        program = copy.deepcopy(logic)
        program.set("programID", "observed")
        program.set("offset", "35")
        additional.append(program)
    ET.ElementTree(additional).write(scenario / "field.add.xml", encoding="utf-8")
    manifest["additional_files"] = ["field.add.xml"]
    write_json(manifest_path, manifest)
    env = CentralizedTrafficEnv(scenario, "native")
    try:
        env.reset(seed=13)
        for signal in manifest["signals"]:
            assert env.connection.trafficlight.getProgram(signal["id"]) == "observed"
            assert env.connection.trafficlight.getRedYellowGreenState(signal["id"]) == signal["greens"][1]
        env.step(0)
        for signal in manifest["signals"]:
            assert env.connection.trafficlight.getProgram(signal["id"]) == "observed"
    finally:
        env.close()
