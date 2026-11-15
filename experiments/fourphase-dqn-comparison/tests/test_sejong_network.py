"""Offline checks for source provenance, clipping and reproducible demand."""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

from src.traffic.sejong_network import (
    ROOT, audit_incoming_programs, clipped_refs, digest, expected_fixed_phase,
    prepare_osm, read_config, write_demand,
)


class SejongInputTests(unittest.TestCase):
    def test_offset_first_partial_phase_uses_absolute_schedule(self):
        # Observed failed-run sequence: samples at t=1..11 were phase 5,
        # t=12..14 phase 6, t=15 phase 7, and t=16 phase 0.
        phases = [{"duration": duration} for duration in (30, 3, 10, 3, 1, 30, 3, 1)]
        for sampled_time, phase in ((1, 5), (11, 5), (12, 6), (14, 6), (15, 7), (16, 0), (46, 1), (97, 0)):
            self.assertEqual(expected_fixed_phase(sampled_time - 1, phases, 15), phase)

    def test_fixed_schedule_detects_a_real_late_phase(self):
        phases = [{"duration": duration} for duration in (30, 3, 3, 30, 3, 3)]
        self.assertEqual(expected_fixed_phase(29, phases), 0)
        self.assertEqual(expected_fixed_phase(30, phases), 1)
        self.assertEqual(expected_fixed_phase(36, phases), 3)
        self.assertEqual(expected_fixed_phase(72, phases), 0)

    def test_incoming_plan_covers_links_and_rejects_conflicts_or_missing_clearance(self):
        root = ET.Element("net")
        node = ET.SubElement(root, "junction", id="J")
        for index, foes in enumerate(("1100", "1100", "0011", "0011")):
            ET.SubElement(node, "request", index=str(index), foes=foes)
            ET.SubElement(root, "connection", {"from": "A" if index < 2 else "B", "to": f"exit{index}",
                          "fromLane": str(index % 2), "toLane": "0", "tl": "J", "linkIndex": str(index)})
        program = ET.SubElement(root, "tlLogic", id="J")
        for duration, state in ((30, "GGrr"), (3, "yyrr"), (3, "rrrr"),
                                (30, "rrGG"), (3, "rryy"), (3, "rrrr")):
            ET.SubElement(program, "phase", duration=str(duration), state=state)
        settings = {"yellow_seconds": 3, "all_red_seconds": 3}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "net.xml"
            ET.ElementTree(root).write(path)
            self.assertTrue(audit_incoming_programs(path, settings)["J"]["all_links_served"])
            node.find("request").set("foes", "1110")  # Same-approach links 0/1 now conflict.
            ET.ElementTree(root).write(path)
            with self.assertRaisesRegex(ValueError, "Conflicting green"):
                audit_incoming_programs(path, settings)
            node.find("request").set("foes", "1100")
            program.findall("phase")[1].set("duration", "2")
            ET.ElementTree(root).write(path)
            with self.assertRaisesRegex(ValueError, "clearance"):
                audit_incoming_programs(path, settings)

    def test_frozen_osm_contains_selected_roads_and_all_join_nodes(self):
        config = read_config()
        source = ROOT / config["osm_source"]
        self.assertEqual(digest(source), config["osm_sha256"])
        with tempfile.TemporaryDirectory() as temporary:
            targets = prepare_osm(config, Path(temporary))
            subset = ET.parse(Path(temporary) / "sejong.selected.osm.xml").getroot()
            self.assertEqual({way.attrib["id"] for way in subset.findall("way")}, set(config["selected_ways"]))
            self.assertEqual({item["id"] for item in targets}, {"hwayang", "childrens_park"})
            self.assertFalse(subset.findall("relation"))
            self.assertTrue(all(not node.findall("tag") for node in subset.findall("node")))
            joins = ET.parse(Path(temporary) / "sejong.joins.nod.xml").getroot()
            self.assertEqual(len(joins.findall("join")), 2)

    def test_clipping_keeps_source_boundary_points_and_rejects_shortcuts(self):
        nodes = {str(index): ET.Element("node", lon=str(x), lat="0.5")
                 for index, x in enumerate((-1, 0.2, 0.8, 2))}
        self.assertEqual(clipped_refs(["0", "1", "2", "3"], nodes, [0, 0, 1, 1]), ["0", "1", "2", "3"])
        with self.assertRaises(ValueError):
            clipped_refs(["1", "3", "2"], nodes, [0, 0, 1, 1])

    def test_unreachable_od_is_recorded_and_arrival_stream_is_not_dropped(self):
        class Network:
            def getEdge(self, edge_id):
                return SimpleNamespace(getID=lambda: edge_id)

            def getShortestPath(self, start, end, **kwargs):
                if end.getID() == "blocked":
                    return None, float("inf")
                return (start, end), 300.0

        ports = {"west": {"incoming": "entry", "outgoing": "unused"},
                 "east": {"incoming": "unused", "outgoing": "exit"},
                 "north": {"incoming": "unused", "outgoing": "blocked"}}
        config = {"ports": {"west": {"vehicles_per_hour": 600}}, "demand_end_seconds": 1200,
                  "destination_weights": {"west": {"east": 0.5, "north": 0.5}}}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            metadata = write_demand(Network(), ports, config, folder, 42)
            first = (folder / "sejong.rou.xml").read_bytes()
            self.assertEqual(metadata["normalized_reachable_weights"], {"west": {"east": 1.0}})
            self.assertEqual(metadata["unreachable_od"], [{"origin": "west", "destination": "north", "weight": 0.5}])
            self.assertGreater(metadata["vehicle_count"], 100)
            departures = [float(v.attrib["depart"]) for v in ET.fromstring(first).findall("vehicle")]
            self.assertEqual(departures, sorted(departures))
            self.assertTrue(all(0 <= value < 1200 for value in departures))
            write_demand(Network(), ports, config, folder, 42)
            self.assertEqual((folder / "sejong.rou.xml").read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
