"""Simple map view, without cards or labels, over the existing TraCI tunnel."""

import traci.constants as tc

from src.traffic.gui_presentation import SCHEMES, ToyGuiPresentation


class CorridorGui(ToyGuiPresentation):
    def _reset(self, env, *, info):
        self.env = env
        self.view = self.c.gui.getIDList()[0]
        self.active = set(self.c.vehicle.getIDList())
        self.c.simulation.subscribe((tc.VAR_DEPARTED_VEHICLES_IDS, tc.VAR_ARRIVED_VEHICLES_IDS))
        for vehicle_id in self.active:
            self._style_vehicle(vehicle_id)
        self._set_camera(self.camera)
        self.c.gui.setSchema(self.view, SCHEMES[self.color_mode])
        self.ready = True

    def _second(self, env, *, now):
        sample = self.c.simulation.getSubscriptionResults() or {}
        arrived = set(sample.get(tc.VAR_ARRIVED_VEHICLES_IDS, ()))
        for vehicle_id in set(sample.get(tc.VAR_DEPARTED_VEHICLES_IDS, ())) - arrived:
            self._style_vehicle(vehicle_id)

    def _set_camera(self, mode):
        a, b = (self.c.junction.getPosition(j) for j in ("A", "B"))
        if mode == "overview":
            boundary = (a[0] - 150, a[1] - 230, b[0] + 150, b[1] + 230)
        else:
            x, y = a if mode == "A" else b
            boundary = x - 95, y - 95, x + 95, y + 95
        self.c.gui.setBoundary(self.view, *boundary)

    def command(self, name, arguments):
        if name == "view":
            if not self.ready or self.disabled:
                raise ValueError("GUI not ready; reset to reconnect the view")
            if len(arguments) != 1 or arguments[0] not in ("overview", "A", "B"):
                raise ValueError("view overview / view A / view B")
            self._set_camera(arguments[0])
            self.camera = arguments[0]
            return f"화면: {self.camera}"
        return super().command(name, arguments)
