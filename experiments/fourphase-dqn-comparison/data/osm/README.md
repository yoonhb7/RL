# Sejong OSM source snapshot

- Download date: 2026-11-11 (Asia/Seoul).
- Source: [OpenStreetMap API map extract](https://api.openstreetmap.org/api/0.6/map?bbox=127.066,37.540,127.080,37.557).
- Bounding box: west 127.066, south 37.540, east 127.080, north 37.557 (WGS84).
- File: `sejong_2026-11-11.osm.xml`.
- SHA-256: `cca2002a0c788c9373c7c469bbf1b5ab86c4b9ef04249e2bc4b46fb4a0173328`.
- Attribution: © OpenStreetMap contributors.
- License: [Open Database License 1.0](https://www.openstreetmap.org/copyright).

This is the downloaded, unmodified public extract, including complete ways that
may extend beyond its requested box. Do not silently replace it with a fresh
download: changing sources requires updating the configuration and provenance.

The preliminary two-junction selection is Hwayang Samgeori
([OSM node 414685242](https://www.openstreetmap.org/node/414685242)) and the
Children's Grand Park Station intersection
([OSM node 8952652961](https://www.openstreetmap.org/node/8952652961)).
Each intersection consists of multiple mapped nodes on separated carriageways.
The exact node joins and selected 17 ways are recorded in `configs/sejong2.json`.

This source does not establish observed traffic demand, real signal operation,
legal turning movements, or calibrated simulation performance. No field survey
was performed. The generated scenario records omitted roads and operational
assumptions separately in `assumptions.json`.
