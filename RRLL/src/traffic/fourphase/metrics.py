"""Per-second accounting for the entire observation window, including pending demand."""

import math
import xml.etree.ElementTree as ET

from .scenario import LANES


class InvalidRun(RuntimeError):
    """Operational failure, not an MDP termination or time-limit truncation."""

    def __init__(self, event):
        self.event = event
        super().__init__(event.get("reason", "invalid simulation run"))


class TrafficMetrics:
    def __init__(self, route_file, horizon):
        self.horizon = horizon
        self.scheduled = {v.attrib["id"]: float(v.attrib["depart"])
                          for v in ET.parse(route_file).getroot().findall("vehicle")}
        self.due = {v for v, depart in self.scheduled.items() if depart < horizon}
        if not self.due:
            raise ValueError("N_due must be positive")
        self.departed, self.arrived = {}, {}
        self.stop_in = self.stop_network = self.pending_seconds = 0
        self.samples = 0
        self.max_queue = self.max_pending = 0
        self.phase_seconds = [0] * 12
        self.failure = None
        self.last_sample = None

    def collect(self, connection, controller):
        simulation = connection.simulation
        now = simulation.getTime()
        departures = simulation.getDepartedIDList()
        arrivals = simulation.getArrivedIDList()
        for vehicle in departures:
            if vehicle in self.departed:
                raise RuntimeError(f"Duplicate departure: {vehicle}")
            self.departed[vehicle] = connection.vehicle.getDeparture(vehicle)
        for vehicle in arrivals:
            # Only the ID is used here. Exact travel durations come from tripinfo.
            self.arrived[vehicle] = now
        pending = set(simulation.getPendingVehicles()) & self.due
        queues = {lane: connection.lane.getLastStepHaltingNumber(lane) for lane in LANES}
        stop_in = sum(queues.values())
        stop_network = sum(connection.lane.getLastStepHaltingNumber(lane) for lane in connection.lane.getIDList())
        self.samples += 1
        self.stop_in += stop_in
        self.stop_network += stop_network
        self.pending_seconds += len(pending)
        self.max_queue = max(self.max_queue, stop_in)
        self.max_pending = max(self.max_pending, len(pending))
        self.phase_seconds[controller.phase] += 1
        self.last_sample = {"time_s": now, "tls_phase": controller.phase, "phase_elapsed_s": controller.elapsed,
                            "signal_state": connection.trafficlight.getRedYellowGreenState("center4"),
                            "queues_raw": queues, "halting_incoming": stop_in, "halting_network": stop_network,
                            "pending_due": len(pending), "departed": len(self.departed), "arrived": len(self.arrived)}
        collision_ids = list(simulation.getCollidingVehiclesIDList())
        collisions = simulation.getCollisions()
        teleports = list(simulation.getStartingTeleportIDList())
        if collision_ids or collisions or teleports:
            details = []
            for collision in collisions:
                details.append({key: getattr(collision, key, None) for key in (
                    "collider", "victim", "colliderType", "victimType", "colliderSpeed", "victimSpeed",
                    "type", "lane", "pos")})
            locations = {}
            active = set(connection.vehicle.getIDList())
            for vehicle in collision_ids:
                if vehicle in active:
                    locations[vehicle] = {"lane": connection.vehicle.getLaneID(vehicle),
                                          "lane_position_m": connection.vehicle.getLanePosition(vehicle)}
            self.failure = {"reason": "collision_or_teleport", "time_s": now, "tls_phase": controller.phase,
                            "signal_state": self.last_sample["signal_state"], "collision_vehicle_ids": collision_ids,
                            "collisions": details, "locations": locations, "teleport_vehicle_ids": teleports,
                            "cause_status": "unclassified; inspect minGap/physical collision and environment before attribution"}
            raise InvalidRun(self.failure)
        return self.last_sample

    def summary(self, connection, *, controller, raw_return=None, decisions=None):
        now = connection.simulation.getTime()
        active = set(connection.vehicle.getIDList())
        departed, arrived = set(self.departed), set(self.arrived)
        pending = set(connection.simulation.getPendingVehicles()) & self.due
        missing = self.due - departed
        complete = self.failure is None and math.isclose(now, self.horizon) and self.samples == self.horizon
        valid = complete and missing == pending and departed == (arrived | active) and not (arrived & active)
        checks = {"full_observation_window": complete,
                  "scheduled_due_equals_departed_plus_pending": self.due == (departed | pending) and not departed & pending,
                  "departed_equals_arrived_plus_active": departed == (arrived | active) and not arrived & active,
                  "no_future_departures": departed <= self.due,
                  "no_collision_or_teleport": self.failure is None,
                  "phase_seconds_equal_elapsed": sum(self.phase_seconds) == self.samples}
        if raw_return is not None:
            checks["reward_stop_identity"] = math.isclose(self.stop_in, -15 * raw_return, rel_tol=1e-10, abs_tol=1e-6)
            checks["exact_decision_count"] = decisions == self.horizon // 15
        depart_delays = [self.departed[v] - self.scheduled[v] for v in self.departed]
        return {"status": "completed" if valid and all(checks.values()) else "abnormal",
                "time_s": now, "counts": {"scheduled_total": len(self.scheduled), "scheduled_due": len(self.due),
                "scheduled_after_cutoff": len(self.scheduled) - len(self.due), "departed": len(departed),
                "arrived": len(arrived), "unfinished": len(active), "pending_due": len(pending),
                "due_not_departed": len(missing)},
                "metrics": {"W_stop_in_vehicle_s": self.stop_in, "W_stop_network_vehicle_s": self.stop_network,
                "W_pending_vehicle_s": self.pending_seconds,
                "AQL_in_vehicles": self.stop_in / self.samples if self.samples else None,
                "mean_depart_delay_s": sum(depart_delays) / len(depart_delays) if depart_delays else None,
                "max_incoming_queue": self.max_queue, "max_pending_due": self.max_pending},
                "raw_reward_sum": raw_return, "decision_count": decisions, "switches": controller.switches,
                "tls_phase_seconds": self.phase_seconds, "checks": checks, "failure": self.failure,
                "gridlock_policy": "congestion retained as performance; never dropped because of queue size"}
