"""SUMO-only visual scene. Colors and decorative shapes never change dynamics."""
from __future__ import annotations

import math
import os
from pathlib import Path


VIEW_SETTINGS = Path(__file__).parent / "assets" / "demo.view.xml"


class GuiPresentation:
    PALETTE = [(38, 132, 244, 255), (240, 126, 45, 255), (18, 175, 158, 255), (175, 105, 232, 255), (244, 197, 66, 255), (225, 232, 240, 255)]
    LAMP_ON = {"r": (255, 48, 58, 255), "y": (255, 200, 32, 255), "g": (35, 239, 105, 255)}
    LAMP_OFF = {"r": (83, 32, 39, 255), "y": (79, 65, 27, 255), "g": (26, 65, 44, 255)}

    def __init__(self, connection, manifest, controller, output=None):
        self.c, self.manifest, self.controller = connection, manifest, controller
        self.output = Path(output) if output else None
        print("Preparing detailed SUMO view...", flush=True)
        self.lights = []
        self.previous_states = {}
        self.last_labels = {}
        self.positions = [self.c.junction.getPosition(s["id"]) for s in manifest["signals"]]
        self.view = self.c.gui.getIDList()[0]
        self.c.gui.setSchema(self.view, "Traffic demo")
        xmin = min(p[0] for p in self.positions) - 120
        xmax = max(p[0] for p in self.positions) + 120
        cy = sum(p[1] for p in self.positions) / len(self.positions)
        self.c.gui.setBoundary(self.view, xmin, cy - 165, xmax, cy + 165)
        if manifest.get("synthetic"):
            self._city_blocks()
            self._road_markings()
        for spec, (jx, jy) in zip(manifest["signals"], self.positions):
            links = self.c.trafficlight.getControlledLinks(spec["id"])
            for lane in spec["lanes"]:
                index = next(i for i, group in enumerate(links) if any(link[0] == lane for link in group))
                shape = self.c.lane.getShape(lane)
                end, previous = shape[-1], shape[-2]
                dx, dy = end[0] - previous[0], end[1] - previous[1]
                norm = math.hypot(dx, dy)
                dx, dy = dx / norm, dy / norm
                # A visible three-lamp housing beside the actual incoming lane.
                x, y = end[0] - dx * 19 + dy * 17, end[1] - dy * 19 - dx * 17
                prefix = f"_demo/light/{spec['id']}/{index}"
                self._rect(prefix + "/shadow", x + 1, y - 1, 14, 29, (100, 111, 105, 180), 80)
                self._rect(prefix + "/body", x, y, 13, 28, (22, 30, 39, 255), 90)
                for lamp, delta in [("r", 8), ("y", 0), ("g", -8)]:
                    self.c.poi.add(prefix + "/" + lamp, x, y + delta, self.LAMP_OFF[lamp], layer=100, width=6.4, height=6.4)
                self.lights.append((spec["id"], index, prefix))
            self.c.poi.add(f"_demo/title/{spec['id']}", jx, jy + 86, (0, 0, 0, 0), poiType=spec["id"] + " | SIGNAL", layer=110, width=0.1)
        cx = (xmin + xmax) / 2
        controller_label = {"rl": "CENTRAL DQN", "fixed": "FIXED SIGNALS", "queue": "QUEUE RULE", "native": "NATIVE SIGNALS"}[controller]
        self.c.poi.add("_demo/header", cx, cy + 145, (0, 0, 0, 0), poiType=f"{controller_label} | SYNTHETIC TRAFFIC SIMULATION", layer=110, width=0.1)
        self.c.poi.add("_demo/counters", cx, cy + 119, (0, 0, 0, 0), poiType="Vehicles entering the network...", layer=110, width=0.1)
        self.update(0, 0, 0)
        print("Detailed SUMO view ready: vehicles and live traffic lights.", flush=True)

    def _rect(self, identifier, x, y, width, height, color, layer):
        self.c.polygon.add(identifier, [(x - width / 2, y - height / 2), (x + width / 2, y - height / 2), (x + width / 2, y + height / 2), (x - width / 2, y + height / 2)], color, fill=True, layer=layer)

    def _city_blocks(self):
        # Purely illustrative surroundings, not buildings from a real map.
        for j, (x, y) in enumerate(self.positions):
            for side in (-1, 1):
                for k, off in enumerate((-91, 91)):
                    bx, by = x + off, y + side * 75
                    self._rect(f"_demo/lot/{j}/{side}/{k}", bx, by, 96, 83, (215, 225, 209, 255), -8)
                    self._rect(f"_demo/build-shadow/{j}/{side}/{k}", bx + 4, by - 4, 58, 48, (153, 169, 160, 255), -7)
                    self._rect(f"_demo/build/{j}/{side}/{k}", bx, by, 58, 48, (186, 201, 213, 255) if k == 0 else (213, 194, 169, 255), -6)
                    self._rect(f"_demo/roof/{j}/{side}/{k}", bx, by + 5, 42, 30, (211, 222, 230, 255) if k == 0 else (237, 222, 199, 255), -5)
                    for tree in (-1, 1):
                        self.c.poi.add(f"_demo/tree/{j}/{side}/{k}/{tree}", bx + tree * 39, by + side * 18, (75, 137, 87, 255), layer=-4, width=12, height=12)

    def _road_markings(self):
        xs = [p[0] for p in self.positions]
        y = self.positions[0][1]
        xmin, xmax = min(xs) - 300, max(xs) + 300
        self._rect("_demo/horizontal-curb", (xmin + xmax) / 2, y, xmax - xmin, 20, (202, 211, 203, 255), -3)
        self._rect("_demo/horizontal-road", (xmin + xmax) / 2, y, xmax - xmin, 13, (55, 65, 81, 255), -2)
        for j, (x, y) in enumerate(self.positions):
            self._rect(f"_demo/vertical-curb/{j}", x, y, 20, 600, (202, 211, 203, 255), -3)
            self._rect(f"_demo/vertical-road/{j}", x, y, 13, 600, (55, 65, 81, 255), -2)
        for i, x in enumerate(range(int(xmin), int(xmax), 16)):
            if all(abs(x - jx) > 14 for jx in xs):
                self._rect(f"_demo/h-line/{i}", x, y, 8, 0.55, (255, 222, 110, 255), 1)
        for j, (x, y) in enumerate(self.positions):
            for i, yy in enumerate(range(int(y - 300), int(y + 300), 16)):
                if abs(yy - y) > 14:
                    self._rect(f"_demo/v-line/{j}/{i}", x, yy, 0.55, 8, (255, 222, 110, 255), 1)

    def update(self, time, arrived, queued):
        for vid in self.c.simulation.getDepartedIDList():
            index = sum(vid.encode("utf-8")) % len(self.PALETTE)
            self.c.vehicle.setColor(vid, self.PALETTE[index])
        states = {s["id"]: self.c.trafficlight.getRedYellowGreenState(s["id"]) for s in self.manifest["signals"]}
        for sid, index, prefix in self.lights:
            active = states[sid][index].lower()
            if self.previous_states.get((sid, index)) == active:
                continue
            for lamp in ("r", "y", "g"):
                self.c.poi.setColor(prefix + "/" + lamp, self.LAMP_ON[lamp] if active == lamp else self.LAMP_OFF[lamp])
            self.previous_states[sid, index] = active
        for spec in self.manifest["signals"]:
            chars = states[spec["id"]]
            phase = "YELLOW" if "y" in chars else "ALL RED" if set(chars.lower()) == {"r"} else "GREEN"
            label = spec["id"] + " | " + phase
            if self.last_labels.get(spec["id"]) != label:
                self.c.poi.setType(f"_demo/title/{spec['id']}", label)
                self.last_labels[spec["id"]] = label
        active = self.c.vehicle.getIDCount()
        note = " | Demand ended: clearing remaining traffic" if time >= self.manifest["demand_seconds"] else ""
        self.c.poi.setType("_demo/counters", f"Time {time}s | On road {active} | Waiting {queued} | Arrived {arrived}{note}")
        if self.output and time % 10 == 0:
            from .common import write_json
            write_json(self.output / "live.json", {"time": time, "active_vehicles": active, "queued_vehicles": queued, "arrived": arrived, "signals": states})
        sequence_frame = os.environ.get("SUMO_PREVIEW_SEQUENCE") == "1" and 30 <= time <= 180 and time % 3 == 0
        if self.output and ((os.environ.get("SUMO_SAVE_PREVIEWS") == "1" and time in (60, 120)) or sequence_frame):
            self.c.gui.screenshot(self.view, str(self.output / f"preview_{time:03d}.png"))
