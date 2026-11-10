from __future__ import annotations

from bisect import bisect_left
import csv
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

import gymnasium as gym
from gymnasium import spaces
import numpy as np
import traci

from .common import binary, load_scenario, schema, sha256, write_json
from .scenario import generate_demand
from .signals import SafetySignal, decode_action, encode_action, joint_mask
from .launch import start_sumo


class CentralizedTrafficEnv(gym.Env):
    """A single observation, scalar joint action, and global queue reward.

    Finite-horizon episodic task: reaching the horizon is terminal, not a
    continuing-task time-limit truncation. The normalized time is observed.
    """

    metadata = {"render_modes": ["human"]}

    def __init__(self, directory, controller="rl", gui=False, output=None, scale=1.0, trace=False, gui_delay_ms=1000):
        self.directory, self.manifest = load_scenario(directory)
        if controller not in ("rl", "fixed", "queue", "native"):
            raise ValueError(controller)
        self.controller, self.gui = controller, gui
        self.output = Path(output).resolve() if output else None
        self.scale, self.trace = scale, trace
        self.gui_delay_ms = int(gui_delay_ms)
        if self.gui_delay_ms < 0:
            raise ValueError("GUI delay must be nonnegative")
        self.presentation = None
        self.connection = None
        self.signals = [SafetySignal(s) for s in self.manifest["signals"]]
        self.action_space = spaces.Discrete(2 ** len(self.signals))
        obs_size = 1 + sum(2 * len(s.spec["lanes"]) + len(s.spec["greens"]) + 4 for s in self.signals)
        self.observation_space = spaces.Box(0, 1, (obs_size,), dtype=np.float32)
        self.checkpoint_schema = schema(self.directory, self.manifest)
        self.finished = True
        self.trace_handle = None
        self.last_metrics = None

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.close()
        self.episode_seed = int(seed if seed is not None else self.np_random.integers(0, 2**30))
        self.route_file = generate_demand(self.directory, self.manifest, self.episode_seed, self.scale)
        # Explicit vehicle files keep accounting unambiguous, including insertion failures.
        route_root = ET.parse(self.route_file).getroot()
        if route_root.findall("flow") or route_root.findall("trip"):
            raise ValueError("Use explicit <vehicle depart='seconds'> routes, not flows/trips. See real-road guide.")
        self.departures = sorted(float(v.attrib["depart"]) for v in route_root.findall("vehicle"))
        if any(t < 0 or t >= self.manifest["horizon_seconds"] for t in self.departures):
            raise ValueError("Every scheduled departure must lie in [0, horizon_seconds).")
        self.signals = [SafetySignal(s) for s in self.manifest["signals"]]
        self.t = self.departed = self.arrived = self.teleports = self.collisions = 0
        self.queue_samples, self.pending_samples = [], []
        self.total_reward = 0.0
        self.finished = False
        self.last_metrics = None
        self.label = "traffic-" + uuid.uuid4().hex
        command = [binary("sumo-gui" if self.gui else "sumo"), "--net-file", str(self.directory / self.manifest["net_file"]), "--route-files", str(self.route_file), "--step-length", "1", "--seed", str(self.episode_seed), "--time-to-teleport", "-1", "--no-step-log", "true", "--duration-log.disable", "true", "--xml-validation", "never", "--collision.action", "warn"]
        if self.manifest.get("additional_files"):
            command += ["--additional-files", ",".join(str(self.directory / f) for f in self.manifest["additional_files"])]
        if self.gui:
            from .presentation import VIEW_SETTINGS
            command += ["--start", "--quit-on-end", "--delay", str(self.gui_delay_ms), "--gui-settings-file", str(VIEW_SETTINGS), "--window-size", "1600,1000"]
        if self.output:
            self.output.mkdir(parents=True, exist_ok=True)
            self.tripinfo_file = self.output / "tripinfo.xml"
            command += ["--tripinfo-output", str(self.tripinfo_file), "--tripinfo-output.write-unfinished", "true", "--error-log", str(self.output / "sumo-errors.log")]
            write_json(self.output / "run.json", {"seed": self.episode_seed, "controller": self.controller, "scale": self.scale, "route_sha256": sha256(self.route_file), "route_file": str(self.route_file), "manifest": self.manifest, "schema": self.checkpoint_schema, "command": command})
        if self.gui:
            print(f"Opening SUMO GUI: {command[0]}", flush=True)
        self.connection = start_sumo(command, self.label, self.output)
        try:
            self._validate_network()
            self.all_lanes = sorted(l for l in self.connection.lane.getIDList() if not l.startswith(":"))
            self.capacity = {l: max(1.0, self.connection.lane.getLength(l) / 7.5) for s in self.signals for l in s.spec["lanes"]}
            if self.trace and self.output:
                self.trace_handle = (self.output / "trace.csv").open("w", newline="", encoding="utf-8")
                self.trace_writer = csv.writer(self.trace_handle)
                self.trace_writer.writerow(["time", "queue", "pending"] + [s.spec["id"] + "_state" for s in self.signals])
            if self.controller != "native":
                for signal in self.signals:
                    self.connection.trafficlight.setRedYellowGreenState(signal.spec["id"], signal.state)
            if self.gui:
                from .presentation import GuiPresentation
                self.presentation = GuiPresentation(self.connection, self.manifest, self.controller, self.output)
            return self._observe(), {"action_mask": self.action_masks(), "seed": self.episode_seed}
        except Exception:
            self.close()
            raise

    def _validate_network(self):
        tls_ids = set(self.connection.trafficlight.getIDList())
        lanes = set(self.connection.lane.getIDList())
        declared = [l for s in self.signals for l in s.spec["lanes"]]
        if len(set(declared)) != len(declared):
            raise ValueError("An incoming lane must occur only once in the global observation.")
        for signal in self.signals:
            sid = signal.spec["id"]
            if sid not in tls_ids or not set(signal.spec["lanes"]) <= lanes:
                raise ValueError(f"Unknown signal/lanes: {sid}")
            links = self.connection.trafficlight.getControlledLinks(sid)
            if len(links) != len(signal.state):
                raise ValueError(f"Signal state length differs from SUMO link indices: {sid}")
            controlled = {link[0] for group in links for link in group}
            if set(signal.spec["lanes"]) != controlled:
                raise ValueError(f"List every controlled incoming lane exactly once: {sid}")

    def action_masks(self):
        return joint_mask(self.signals)

    def _observe(self):
        obs = [self.t / self.manifest["horizon_seconds"]]
        for signal in self.signals:
            for lane in signal.spec["lanes"]:
                obs.extend([self.connection.lane.getLastStepHaltingNumber(lane) / self.capacity[lane], self.connection.lane.getLastStepVehicleNumber(lane) / self.capacity[lane]])
            obs += [float(signal.green == i) for i in range(len(signal.spec["greens"]))]
            obs += [float(signal.stage == stage) for stage in ("green", "yellow", "all_red")]
            duration = signal.spec["max_green"] if signal.stage == "green" else signal.spec["yellow"] if signal.stage == "yellow" else signal.spec["all_red"]
            obs.append(signal.elapsed / duration)
        return np.clip(obs, 0, 1).astype(np.float32)

    def queue_action(self):
        """Simple cyclic next-green queue heuristic; this is not SUMO actuated."""
        bits = []
        for s in self.signals:
            links = self.connection.trafficlight.getControlledLinks(s.spec["id"])
            queues = []
            for state in s.spec["greens"]:
                lanes = {link[0] for char, group in zip(state, links) if char in "Gg" for link in group}
                queues.append(sum(self.connection.lane.getLastStepHaltingNumber(l) for l in lanes))
            next_green = (s.green + 1) % len(queues)
            want = int(queues[next_green] > queues[s.green])
            bits.append(want if want in s.allowed() else s.allowed()[0])
        return encode_action(bits)

    def step(self, action):
        if self.finished or self.connection is None:
            raise RuntimeError("reset() must precede step(); do not step after termination")
        if not self.action_space.contains(action):
            raise ValueError("action outside Discrete space")
        if self.controller == "rl":
            if not self.action_masks()[int(action)]:
                raise ValueError("Invalid action: use info['action_mask'] for exploration and inference.")
            for signal, bit in zip(self.signals, decode_action(action, len(self.signals))):
                signal.request(bit)
        elif self.controller == "queue":
            for signal, bit in zip(self.signals, decode_action(self.queue_action(), len(self.signals))):
                signal.request(bit)
        queue_seconds = 0
        for _ in range(self.manifest["decision_seconds"]):
            for signal in self.signals:
                if self.controller == "fixed" and signal.stage == "green" and signal.elapsed >= signal.spec["fixed_green"]:
                    signal.request(1)
                state = signal.before_second()
                if self.controller != "native":
                    self.connection.trafficlight.setRedYellowGreenState(signal.spec["id"], state)
            self.connection.simulationStep()
            self.t += 1
            for signal in self.signals:
                signal.after_second()
            self.departed += self.connection.simulation.getDepartedNumber()
            self.arrived += self.connection.simulation.getArrivedNumber()
            self.teleports += self.connection.simulation.getStartingTeleportNumber()
            self.collisions += self.connection.simulation.getCollidingVehiclesNumber()
            queue = sum(self.connection.lane.getLastStepHaltingNumber(l) for l in self.all_lanes)
            pending = max(0, bisect_left(self.departures, self.t) - self.departed)
            self.queue_samples.append(queue)
            self.pending_samples.append(pending)
            queue_seconds += queue
            if self.presentation is not None:
                self.presentation.update(self.t, self.arrived, queue)
            if self.trace_handle:
                self.trace_writer.writerow([self.t, queue, pending] + [self.connection.trafficlight.getRedYellowGreenState(s.spec["id"]) for s in self.signals])
            if self.t >= self.manifest["horizon_seconds"]:
                self.finished = True
                break
        reward = -float(queue_seconds) / 100.0
        self.total_reward += reward
        obs = self._observe()
        info = {"action_mask": self.action_masks(), "time": self.t}
        if self.finished:
            self.last_metrics = self._summary()
            info["metrics"] = self.last_metrics
            self.close()
        return obs, reward, self.finished, False, info

    def _summary(self):
        active = self.connection.vehicle.getIDCount()
        summary = {"seed": self.episode_seed, "controller": self.controller, "scale": self.scale, "duration_seconds": self.t, "scheduled": len(self.departures), "departed": self.departed, "arrived": self.arrived, "unfinished": active, "not_departed": len(self.departures) - self.departed, "teleports": self.teleports, "collision_events": self.collisions, "queue_vehicle_seconds": sum(self.queue_samples), "pending_vehicle_seconds": sum(self.pending_samples), "mean_queue_vehicles": float(np.mean(self.queue_samples)), "p95_queue_vehicles": float(np.percentile(self.queue_samples, 95)), "switches": sum(s.switches for s in self.signals) if self.controller != "native" else None, "return": self.total_reward, "route_sha256": sha256(self.route_file)}
        summary["count_balance_ok"] = summary["scheduled"] == summary["arrived"] + summary["unfinished"] + summary["not_departed"]
        return summary

    def close(self):
        self.presentation = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None
            if self.output and self.last_metrics is not None:
                trips = list(ET.parse(self.tripinfo_file).getroot().iter("tripinfo"))
                complete = [t for t in trips if float(t.attrib["arrival"]) >= 0]
                departed = [t for t in trips if float(t.attrib["depart"]) >= 0]
                for key, rows, attr in [("mean_wait_arrived_s", complete, "waitingTime"), ("mean_travel_arrived_s", complete, "duration"), ("mean_wait_departed_censored_s", departed, "waitingTime"), ("mean_depart_delay_departed_s", departed, "departDelay")]:
                    self.last_metrics[key] = float(np.mean([float(t.attrib[attr]) for t in rows])) if rows else None
                self.last_metrics["tripinfo_departed_rows"] = len(departed)
                self.last_metrics["tripinfo_counts_match"] = len(departed) == self.last_metrics["departed"] and len(complete) == self.last_metrics["arrived"]
                write_json(self.output / "metrics.json", self.last_metrics)
        if self.trace_handle is not None:
            self.trace_handle.close()
            self.trace_handle = None
