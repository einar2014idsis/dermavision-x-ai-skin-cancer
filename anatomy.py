"""Validate saved points against the same anatomical polygons rendered by React."""
import json
from pathlib import Path

ATLAS = json.loads((Path(__file__).resolve().parent / "web" / "src" / "anatomy.json").read_text(encoding="utf-8"))
REGIONS = {item["id"]: item for item in ATLAS["regions"]}


def inside_polygon(x, y, polygon):
    """Ray crossing with a small tolerance for rounded coordinates on the edge."""
    inside = False
    for (ax, ay), (bx, by) in zip(polygon, polygon[1:] + polygon[:1]):
        dx, dy = bx - ax, by - ay
        length = (dx * dx + dy * dy) ** .5
        if length and abs(dx * (y - ay) - dy * (x - ax)) <= 1e-5 * length:
            if min(ax, bx) - 1e-5 <= x <= max(ax, bx) + 1e-5 and min(ay, by) - 1e-5 <= y <= max(ay, by) + 1e-5:
                return True
        if (ay > y) != (by > y) and x < ax + dx * (y - ay) / dy:
            inside = not inside
    return inside


def validate_anatomical_location(region_id, view, site, x, y, origin):
    region = REGIONS.get(region_id)
    if not region or region["view"] != view or region["label"] != site:
        raise ValueError("Selecciona una región anatómica válida y su vista correspondiente.")
    point = (x * ATLAS["width"], y * ATLAS["height"])
    if not inside_polygon(*point, region["polygon"]):
        raise ValueError("El marcador debe estar dentro de la región anatómica seleccionada.")
    if origin == "default" and any(abs(a - b) > 1e-5 for a, b in zip(point, region["center"])):
        raise ValueError("La ubicación predeterminada debe coincidir con el centro de la región.")
    return region_id, x, y, origin
