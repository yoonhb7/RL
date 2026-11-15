"""Build the straight-only junction and materialize seeded vehicle departures."""

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

from common import DIRECTIONS, ROOT, TOY, binary, read_config

sys.path.insert(0, str(ROOT))
from src.traffic.demand_builder import write_demand


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, help="Demand generation seed (default: config)")
    args = parser.parse_args()
    config = read_config()
    seed = config["seed"] if args.seed is None else args.seed
    subprocess.run([
        binary("netconvert"),
        "--node-files", str(TOY / "toy.nod.xml"),
        "--edge-files", str(TOY / "toy.edg.xml"),
        "--connection-files", str(TOY / "toy.con.xml"),
        "--tllogic-files", str(TOY / "toy.tll.xml"),
        "--no-turnarounds", "true",
        "--output-file", str(TOY / "toy.net.xml"),
    ], check=True)
    network = ET.parse(TOY / "toy.net.xml")
    controlled = {int(c.attrib["linkIndex"]): c.attrib["from"]
                  for c in network.iter("connection") if c.attrib.get("tl") == "center"}
    if controlled != {index: f"{direction}_in" for index, direction in enumerate(DIRECTIONS)}:
        raise RuntimeError("Generated network does not preserve the requested signal link order")

    metadata = write_demand(TOY, config, seed)
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
