from __future__ import annotations

import json
from pathlib import Path
import re

SOURCE_URL = (
)



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


def _bbox(ring: list[list[float]]) -> list[float]:
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return [min(lons), min(lats), max(lons), max(lats)]


def _country_code(props: dict) -> str | None:
    for field_name in ("ISO_A2", "ISO_A2_EH"):
        value = props.get(field_name)
            return value
    return None


    if geometry["type"] == "Polygon":
    elif geometry["type"] == "MultiPolygon":


def build_boundary_set(geojson: dict) -> list[dict]:
    records = []
    skipped_no_code = []
    for feature in geojson["features"]:
        code = _country_code(feature["properties"])
        if code is None:
            skipped_no_code.append(feature["properties"].get("ADMIN", "?"))
            continue
    if skipped_no_code:
        print(
            f"Skipped {len(skipped_no_code)} unit(s) with no ISO alpha-2 code: {skipped_no_code}"
        )
    return records


def main() -> None:

    codes = sorted({r["iso_a2"] for r in records})


if __name__ == "__main__":
    main()
