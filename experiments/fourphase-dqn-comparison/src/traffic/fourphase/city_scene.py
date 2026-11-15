"""Display-only city geometry adapted to the audited two-incoming-lane road.

Four horizontal four-aspect housings combine straight and left-turn indications.
The GUI observer reads the actual eight SUMO links; standalone uses native bars.
"""

import math
import xml.etree.ElementTree as ET

from .scenario import DIRECTIONS, write_xml


PREFIX = "fourphase.city."
OFF = (48, 58, 61, 255)
ON = {"r": (249, 82, 87, 255), "y": (255, 193, 59, 255), "g": (55, 222, 151, 255)}
SIGNAL_POSITIONS = ((-18, 18), (18, -18), (18, 18), (-18, -18))


def transform(points, x, y, angle):
    a = math.radians(angle)
    return [(x + u * math.cos(a) + v * math.sin(a), y - u * math.sin(a) + v * math.cos(a)) for u, v in points]


def car_parts(color, length=5.0, width=1.8):
    """Local coordinates, front bumper at (0,0), matching SUMO vehicle positions."""
    def shape(points):
        return [(x * width / 1.8, y * length / 5) for x, y in points]

    body = [(-.65, 0), (.65, 0), (.9, -.35), (.9, -4.6), (.65, -5), (-.65, -5), (-.9, -4.6), (-.9, -.35)]
    return [
        (shape(body), (30, 39, 48, 255)),
        (shape([(x * .87, -.12 + y * .95) for x, y in body]), tuple(color)),
        (shape([(-.63, -1.1), (.63, -1.1), (.5, -1.9), (-.5, -1.9)]), (157, 205, 220, 255)),
        (shape([(-.5, -2), (.5, -2), (.5, -3.15), (-.5, -3.15)]),
         tuple(min(255, c + 20) for c in color[:3]) + (255,)),
        (shape([(-.5, -3.3), (.5, -3.3), (.63, -3.9), (-.63, -3.9)]), (88, 132, 154, 255)),
        (shape([(-.65, -.18), (-.25, -.18), (-.25, -.34), (-.65, -.34)]), (255, 243, 189, 255)),
        (shape([(.25, -.18), (.65, -.18), (.65, -.34), (.25, -.34)]), (255, 243, 189, 255)),
        (shape([(-.66, -4.67), (.66, -4.67), (.66, -4.83), (-.66, -4.83)]), (232, 74, 70, 255)),
    ]


class CityGeometry:
    def __init__(self, center=(500, 500), arm_length=500):
        self.cx, self.cy = center
        self.arm_length = arm_length
        self.shapes = []
        self.signal_lamps = {}
        self.counter = 0

    def poly(self, points, color, layer=2, name=None):
        self.counter += 1
        shape_id = PREFIX + (name or f"shape.{self.counter:04d}")
        self.shapes.append({"id": shape_id, "shape": [(self.cx + x, self.cy + y) for x, y in points],
                            "color": tuple(color) if len(color) == 4 else (*color, 255), "layer": layer})
        return shape_id

    def rect(self, x, y, w, h, color, layer=2, name=None):
        return self.poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], color, layer, name)

    def circle(self, x, y, radius, color, layer=5, name=None):
        return self.poly([(x + radius * math.cos(i * math.tau / 20), y + radius * math.sin(i * math.tau / 20))
                          for i in range(20)], color, layer, name)

    def tree(self, x, y, radius=2.4):
        self.circle(x + .8, y - .8, radius, (119, 138, 117), 3)
        self.circle(x, y, radius, (64, 125, 83), 7)
        self.circle(x - .55, y + .55, radius * .7, (90, 153, 99), 8)

    def building(self, x, y, w, h, color, *, solar=False):
        self.rect(x + 2, y - 2, w, h, (156, 164, 153), 2)
        self.rect(x, y, w, h, (79, 91, 99), 3)
        self.rect(x + .6, y + .6, w - 1.2, h - 1.2, color, 4)
        self.rect(x + .6, y + .6, w - 1.2, 2.3, tuple(max(0, c - 27) for c in color), 5)
        for wx in range(2, int(w) - 2, 4):
            self.rect(x + wx, y + .9, 2.1, 1.1, (156, 195, 208), 6)
        self.rect(x + 2, y + h - 5, 5, 2.8, (114, 129, 139), 6)
        self.rect(x + 2.5, y + h - 4.5, 4, 1.8, (186, 199, 201), 7)
        if solar:
            for px in (w - 13, w - 7):
                for py in (h - 7, h - 12):
                    self.rect(x + px, y + py, 4.7, 3, (62, 91, 121), 6)
                    self.rect(x + px + .4, y + py + .4, 3.9, .12, (130, 160, 185), 7)
        else:
            self.rect(x + w - 6, y + h - 5, 3, 2.7, (138, 150, 155), 6)

    def parking(self, x, y, w=65, h=19):
        self.rect(x, y, w, h, (169, 180, 179), 2)
        self.rect(x + 1, y + 1, w - 2, h - 2, (100, 115, 127), 3)
        for p in range(2, int(w) - 3, 4):
            self.rect(x + p, y + 1.5, .12, 5.5, (235, 236, 222), 4)
            self.rect(x + p, y + h - 7, .12, 5.5, (235, 236, 222), 4)
        for index, color in ((0, (218, 224, 225, 255)), (2, (79, 134, 169, 255)), (5, (204, 119, 95, 255))):
            if 5 + index * 4 < w - 2:
                for offset, (points, col) in enumerate(car_parts(color)):
                    self.poly(transform(points, x + 4 + index * 4, y + 7, 0), col, 5 + offset)

    def street_details(self):
        length = self.arm_length
        self.rect(-length, -12.5, 2 * length, 25, (185, 197, 187), -5)
        self.rect(-12.5, -length, 25, 2 * length, (185, 197, 187), -5)
        self.rect(-length, -10.8, 2 * length, 21.6, (221, 217, 204), -4)
        self.rect(-10.8, -length, 21.6, 2 * length, (221, 217, 204), -4)
        for p in range(-164, 165, 4):
            if abs(p) < 26:
                continue
            for side in (-1, 1):
                self.rect(p, side * 8.7 - 1.7, .07, 3.4, (192, 192, 178), -3)
                self.rect(side * 8.7 - 1.7, p, 3.4, .07, (192, 192, 178), -3)
        for p in (-160, -136, -112, -88, -64, -40, 40, 64, 88, 112, 136, 160):
            for side in (-1, 1):
                for x, y in ((p, side * 13.7), (side * 13.7, p)):
                    self.rect(x - 1.9, y - 1.9, 3.8, 3.8, (157, 175, 146), 2)
                    self.tree(x, y, 1.65)
        for p in (-120, -72, -28, 28, 72, 120):
            for side in (-1, 1):
                for x, y in ((p, side * 9), (side * 9, p)):
                    self.circle(x + .4, y - .4, .8, (170, 179, 170), 2)
                    self.rect(x - .12, y - 1.4, .24, 2.4, (108, 122, 126), 3)
                    self.circle(x, y + 1.1, .55, (249, 235, 181), 4)

    def neighborhood(self):
        # All blocks start outside the widened carriageway and its stop lines.
        self.rect(-114, 27, 88, 66, (206, 204, 188), 1)
        self.building(-105, 35, 31, 25, (182, 149, 128))
        self.building(-65, 35, 30, 23, (189, 185, 164))
        self.parking(-105, 67, 70, 19)
        for x in (-109, -72, -30):
            self.tree(x, 29, 2)

        self.rect(27, 27, 62, 62, (129, 164, 117), 1)
        self.rect(29, 29, 58, 58, (159, 190, 138), 2)
        self.rect(55, 29, 3, 58, (223, 215, 190), 3)
        self.rect(29, 55, 58, 3, (223, 215, 190), 3)
        self.circle(56.5, 56.5, 7.2, (221, 221, 205), 4)
        self.circle(56.5, 56.5, 4.8, (104, 162, 184), 5)
        self.circle(55.6, 57.2, 3.5, (158, 209, 218), 6)
        for x, y in ((36, 36), (78, 37), (36, 78), (78, 79), (79, 65), (36, 64)):
            self.tree(x, y, 3)
        for x, y in ((43, 49), (66, 63), (64, 38), (43, 72)):
            self.rect(x, y, 4, .8, (128, 94, 69), 7)
            self.rect(x + .3, y - .3, .3, 1.4, (69, 83, 80), 6)
            self.rect(x + 3.4, y - .3, .3, 1.4, (69, 83, 80), 6)
        self.building(99, 34, 33, 37, (177, 194, 192), solar=True)
        self.tree(94, 30, 2.2)

        self.rect(-114, -111, 88, 85, (210, 206, 190), 1)
        self.building(-105, -77, 32, 39, (179, 164, 148))
        self.building(-65, -65, 30, 28, (193, 169, 145))
        self.parking(-105, -103, 70, 19)
        for x in (-109, -73, -30):
            self.tree(x, -29, 2)

        self.rect(27, -104, 103, 78, (201, 210, 194), 1)
        self.building(35, -68, 37, 32, (176, 192, 197), solar=True)
        self.building(82, -82, 38, 44, (187, 164, 149))
        self.parking(35, -96, 38, 20)
        for x, y in ((31, -30), (78, -31), (125, -31), (125, -98)):
            self.tree(x, y, 2.4)
        for x, y, w, h, col in ((-151, 34, 26, 38, (180, 182, 168)),
                                 (-151, -73, 26, 37, (173, 187, 176)),
                                 (-104, 108, 34, 25, (186, 180, 165)),
                                 (-60, 105, 28, 31, (179, 191, 188)),
                                 (31, 104, 30, 32, (187, 179, 165)),
                                 (76, 107, 42, 25, (167, 183, 190))):
            self.building(x, y, w, h, col)

    def signals(self):
        for direction, (x, y) in zip(DIRECTIONS, SIGNAL_POSITIONS):
            name = f"signal.{direction}"
            self.rect(x - 4.9, y - 1.9, 10.5, 3, (135, 147, 142), 21, f"{name}.shadow")
            self.rect(x - .15, y - 5.2, .3, 5.5, (100, 115, 122), 22, f"{name}.pole")
            self.rect(x - 5.25, y - 1.5, 10.5, 3, (27, 37, 45), 23, f"{name}.body")
            self.rect(x - 5.05, y - 1.3, 10.1, 2.6, (39, 50, 58), 24, f"{name}.inset")
            lamps = {}
            for lamp, dx in (("r", -3.6), ("y", -1.2), ("g", 3.6)):
                lamps[lamp] = self.circle(x + dx, y, .9, OFF, 25, f"{name}.{lamp}")
            self.circle(x + 1.2, y, .9, OFF, 25, f"{name}.left.background")
            arrow = [(-.65, 0), (-.12, .52), (-.12, .23), (.47, .23), (.47, -.23),
                     (-.12, -.23), (-.12, -.52)]
            lamps["left"] = self.poly([(x + 1.2 + ax, y + ay) for ax, ay in arrow], OFF, 26, f"{name}.left")
            self.signal_lamps[direction] = lamps

    def build(self):
        self.street_details()
        self.neighborhood()
        self.signals()
        return self

    def write(self, path):
        root = ET.Element("additional")
        for shape in self.shapes:
            ET.SubElement(root, "poly", id=shape["id"], type="fourphase.display-only", fill="true",
                          layer=str(shape["layer"]), color=",".join(map(str, shape["color"])),
                          shape=" ".join(f"{x:.4f},{y:.4f}" for x, y in shape["shape"]))
        write_xml(path, root)
