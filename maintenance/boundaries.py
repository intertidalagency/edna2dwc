from __future__ import annotations

import gzip
import json
from pathlib import Path
import re
import sys

SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/"
    "geojson/ne_10m_admin_0_countries.geojson"
)
USAGE = (
    f"usage: python -I maintenance/boundaries.py <downloaded geojson> edna2dwc/data/boundaries.json.gz\n"
    f"Download the GeoJSON from {SOURCE_URL}"
)

SIMPLIFY_TOLERANCE_DEG = 0.005
DECIMALS = 4

_ISO3166_ALPHA2_RE = re.compile(r"^[A-Z]{2}$")


def _perp_distance(point, start, end):
    (x, y), (x1, y1), (x2, y2) = point, start, end
    if (x1, y1) == (x2, y2):
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    num = abs((y2 - y1) * x - (x2 - x1) * y + x2 * y1 - y2 * x1)
    den = ((y2 - y1) ** 2 + (x2 - x1) ** 2) ** 0.5
    return num / den


def douglas_peucker(points: list[list[float]], tolerance: float) -> list[list[float]]:
    if len(points) <= 3:
        return points

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start_i, end_i = stack.pop()
        start, end = points[start_i], points[end_i]
        max_dist, max_i = 0.0, None
        for i in range(start_i + 1, end_i):
            d = _perp_distance(points[i], start, end)
            if d > max_dist:
                max_dist, max_i = d, i
        if max_i is not None and max_dist > tolerance:
            keep[max_i] = True
            stack.append((start_i, max_i))
            stack.append((max_i, end_i))
    return [p for p, k in zip(points, keep) if k]


def _simplify(ring: list[list[float]]) -> list[list[float]]:
    simplified = douglas_peucker(ring, SIMPLIFY_TOLERANCE_DEG)
    if len(simplified) < 4:
        simplified = ring
    rounded = [[round(x, DECIMALS), round(y, DECIMALS)] for x, y in simplified]
    return [p for i, p in enumerate(rounded) if i == 0 or p != rounded[i - 1]]


def _bbox(ring: list[list[float]]) -> list[float]:
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return [min(lons), min(lats), max(lons), max(lats)]


def _country_code(props: dict) -> str | None:
    for field_name in ("ISO_A2", "ISO_A2_EH"):
        value = props.get(field_name)
        if value and _ISO3166_ALPHA2_RE.match(value):
            return value
    return None


def _iter_polygons(geometry: dict):
    if geometry["type"] == "Polygon":
        yield geometry["coordinates"]
    elif geometry["type"] == "MultiPolygon":
        yield from geometry["coordinates"]


def build_boundary_set(geojson: dict) -> list[dict]:
    records = []
    skipped_no_code = []
    for feature in geojson["features"]:
        code = _country_code(feature["properties"])
        if code is None:
            skipped_no_code.append(feature["properties"].get("ADMIN", "?"))
            continue
        for polygon in _iter_polygons(feature["geometry"]):
            rings = [_simplify(ring) for ring in polygon]
            records.append({"iso_a2": code, "bbox": _bbox(rings[0]), "rings": rings})
    if skipped_no_code:
        print(
            f"Skipped {len(skipped_no_code)} unit(s) with no ISO alpha-2 code: {skipped_no_code}"
        )
    return records


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(USAGE)
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    records = build_boundary_set(json.loads(source.read_text(encoding="utf-8")))
    serialized = json.dumps(records, separators=(",", ":")).encode("utf-8")
    output.write_bytes(gzip.compress(serialized, compresslevel=9, mtime=0))

    codes = sorted({r["iso_a2"] for r in records})
    print(f"Wrote {len(records)} polygon(s), {len(codes)} country code(s) to {output}")
    print(f"({output.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
