"""Latest one-second TraCI subscriptions; reading these caches sends no requests."""

import traci.constants as tc

from .scenario import TLS


SIM_VARIABLES = (tc.VAR_TIME, tc.VAR_DEPARTED_VEHICLES_IDS, tc.VAR_ARRIVED_VEHICLES_IDS,
                 tc.VAR_PENDING_VEHICLES, tc.VAR_COLLIDING_VEHICLES_IDS,
                 tc.VAR_TELEPORT_STARTING_VEHICLES_IDS)
TLS_VARIABLES = (tc.TL_CURRENT_PHASE, tc.TL_RED_YELLOW_GREEN_STATE)


class TrafficSnapshot:
    def __init__(self, connection):
        self.c = connection
        self.lanes = tuple(connection.lane.getIDList())
        for lane in self.lanes:
            connection.lane.subscribe(lane, (tc.LAST_STEP_VEHICLE_HALTING_NUMBER,))
        connection.simulation.subscribe(SIM_VARIABLES)
        connection.trafficlight.subscribe(TLS, TLS_VARIABLES)
        self.refresh()

    def refresh(self):
        simulation = self.c.simulation.getSubscriptionResults() or {}
        lights = self.c.trafficlight.getSubscriptionResults(TLS) or {}
        lanes = self.c.lane.getAllSubscriptionResults() or {}
        if any(variable not in simulation for variable in SIM_VARIABLES) or any(
            variable not in lights for variable in TLS_VARIABLES
        ) or any(tc.LAST_STEP_VEHICLE_HALTING_NUMBER not in lanes.get(lane, {}) for lane in self.lanes):
            raise RuntimeError("Incomplete TraCI subscription snapshot")
        self.time = simulation[tc.VAR_TIME]
        self.departed = tuple(simulation[tc.VAR_DEPARTED_VEHICLES_IDS])
        self.arrived = tuple(simulation[tc.VAR_ARRIVED_VEHICLES_IDS])
        self.pending = tuple(simulation[tc.VAR_PENDING_VEHICLES])
        self.colliding = tuple(simulation[tc.VAR_COLLIDING_VEHICLES_IDS])
        self.teleports = tuple(simulation[tc.VAR_TELEPORT_STARTING_VEHICLES_IDS])
        self.phase = lights[tc.TL_CURRENT_PHASE]
        self.signal = lights[tc.TL_RED_YELLOW_GREEN_STATE]
        self.queues = {lane: lanes[lane][tc.LAST_STEP_VEHICLE_HALTING_NUMBER] for lane in self.lanes}
