"""Read final SUMO link indices before authoring any real-road signal states."""
from pathlib import Path
import xml.etree.ElementTree as ET

from .common import sha256, write_json


def inspect_network(net_file, output):
    root = ET.parse(net_file).getroot()
    tls_ids = sorted({c.get("tl") for c in root.findall("connection") if c.get("tl")})
    signals = []
    for sid in tls_ids:
        connections = [{key: c.get(key) for key in ["from", "to", "fromLane", "toLane", "linkIndex", "dir", "via"]} for c in root.findall("connection") if c.get("tl") == sid]
        connections.sort(key=lambda c: int(c["linkIndex"]))
        programs = []
        for logic in root.findall("tlLogic"):
            if logic.get("id") == sid:
                programs.append({"program_id": logic.get("programID"), "type": logic.get("type"), "offset": logic.get("offset"), "phases": [dict(p.attrib) for p in logic.findall("phase")]})
        signals.append({"id": sid, "lanes": sorted({c["from"] + "_" + c["fromLane"] for c in connections}), "connections_by_link_index": connections, "programs": programs})
    data = {"net_file": str(Path(net_file).resolve()), "sha256": sha256(net_file), "signals": signals, "warning": "Auto-generated programs are not evidence of field signal timing. Check actual movements and conflicts in netedit."}
    write_json(output, data)
    return data
