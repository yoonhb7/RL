"""Read actual traffic; mutate only GUI and display polygon properties."""

from .city_scene import CityGeometry, OFF, ON, PREFIX, car_parts, transform
from .scenario import DIRECTIONS, TLS


class FourPhaseCityDisplay:
    def __init__(self, connection, *, detailed_cars=False, arm_length=500):
        self.c = connection
        self.cx, self.cy = connection.junction.getPosition(TLS)
        self.geometry = CityGeometry((self.cx, self.cy), arm_length).build()
        self.detailed_cars = detailed_cars
        self.cars = {}
        self.last_signal = None
        self.lamp_colors = {}
        self.camera = "city"
        views = connection.gui.getIDList()
        if not views:
            raise ValueError("A sumo-gui view is required for the city display")
        self.view = views[0]

    def attach(self):
        present = set(self.c.polygon.getIDList())
        # An already copied city XML may still contain the original eight heads.
        # Replace that display layout without changing any Mac traffic input.
        if PREFIX + "signal.north.straight.r" in present:
            for shape_id in sorted(present):
                if shape_id.startswith(PREFIX):
                    self.c.polygon.remove(shape_id)
            present = {shape_id for shape_id in present if not shape_id.startswith(PREFIX)}
            self.cars.clear()
        for shape in self.geometry.shapes:
            if shape["id"] not in present:
                self.c.polygon.add(shape["id"], shape["shape"], shape["color"], fill=True,
                                   polygonType="fourphase.display-only", layer=shape["layer"])
        self.c.gui.setSchema(self.view, "Four phase city detailed" if self.detailed_cars else "Four phase city")
        self.set_camera(self.camera)
        self.last_signal = None
        self.lamp_colors.clear()
        self.update()

    def set_camera(self, camera):
        if camera not in ("city", "junction", "map"):
            raise ValueError("view city / view junction / view map")
        self.camera = camera
        if camera == "map":
            bounds = self.c.simulation.getNetBoundary()
            self.c.gui.setBoundary(self.view, *bounds[0], *bounds[1])
        else:
            width, height = (165, 120) if camera == "city" else (48, 35)
            self.c.gui.setBoundary(self.view, self.cx - width, self.cy - height, self.cx + width, self.cy + height)

    def update_signals(self, signal_state=None):
        state = signal_state if signal_state is not None else self.c.trafficlight.getRedYellowGreenState(TLS)
        if len(state) != 8:
            raise ValueError("The display requires the eight audited movement links")
        if state == self.last_signal:
            return
        for index, direction in enumerate(DIRECTIONS):
            lamps = self.geometry.signal_lamps[direction]
            straight, left = state[2 * index:2 * index + 2].lower()
            yellow = straight == "y" or left == "y"
            # Red stays on during protected left: straight traffic must stop.
            enabled = {"r": straight != "g" and not yellow, "y": yellow,
                       "left": left == "g", "g": straight == "g"}
            for lamp, lit in enabled.items():
                color = ON["g" if lamp == "left" else lamp] if lit else OFF
                shape_id = lamps[lamp]
                if self.lamp_colors.get(shape_id) != color:
                    self.c.polygon.setColor(shape_id, color)
                    self.lamp_colors[shape_id] = color
        self.last_signal = state

    def update_cars(self, vehicles=None):
        if not self.detailed_cars:
            return
        active = set(self.c.vehicle.getIDList()) if vehicles is None else set(vehicles)
        gone = set(self.cars) - active
        if gone:
            remaining_shapes = set(self.c.polygon.getIDList())
            for vehicle in gone:
                for shape_id in self.cars.pop(vehicle):
                    if shape_id in remaining_shapes:
                        self.c.polygon.remove(shape_id)
        for vehicle in sorted(active - set(self.cars)):
            x, y = self.c.vehicle.getPosition(vehicle)
            angle = self.c.vehicle.getAngle(vehicle)
            parts = car_parts(self.c.vehicle.getColor(vehicle), self.c.vehicle.getLength(vehicle),
                              self.c.vehicle.getWidth(vehicle))
            ids = []
            for index, (points, color) in enumerate(parts):
                shape_id = PREFIX + f"car.{vehicle}.{index}"
                self.c.polygon.add(shape_id, transform(points, x, y, angle), color, fill=True,
                                   polygonType="fourphase.vehicle-display", layer=200 + index)
                self.c.polygon.addDynamics(shape_id, trackedObjectID=vehicle, rotate=True)
                ids.append(shape_id)
            self.cars[vehicle] = ids

    def update(self, *, signal_state=None, vehicles=None):
        self.update_signals(signal_state)
        self.update_cars(vehicles)
