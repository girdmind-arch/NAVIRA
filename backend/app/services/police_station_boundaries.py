"""Approximate route-to-police-station matching using Delhi Police GIS polygons.

Boundaries are fetched from the official GSDL ArcGIS service and cached. The
route is sampled at short intervals; this is a coverage aid, not a legal
jurisdiction determination.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import threading
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BOUNDARY_SERVICE_URL = "https://gsdl.org.in/arcgis/rest/services/Delhi_Police/Delhi_Police/MapServer/2/query"
BOUNDARY_SOURCE_URL = "https://gsdl.org.in/arcgis/rest/services/Delhi_Police/Delhi_Police/MapServer"
CACHE_SECONDS = 24 * 60 * 60
STALE_SECONDS = 7 * 24 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 12
MAX_ROUTE_SAMPLES = 6000
SAMPLE_SPACING_METRES = 100
_cache: tuple[float, dict[str, Any]] | None = None
_lock = threading.Lock()


def _point_in_ring(point: tuple[float, float], ring: list[Any]) -> bool:
    x, y = point
    inside = False
    if len(ring) < 4:
        return False
    previous = ring[-1]
    for current in ring:
        try:
            x1, y1 = float(previous[0]), float(previous[1])
            x2, y2 = float(current[0]), float(current[1])
        except (TypeError, ValueError, IndexError):
            previous = current
            continue
        if ((y1 > y) != (y2 > y)) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-15) + x1:
            inside = not inside
        previous = current
    return inside


def _point_in_polygon(point: tuple[float, float], rings: list[Any]) -> bool:
    # GeoJSON rings are ordered outer-first, followed by holes. ArcGIS GeoJSON
    # follows the same convention for this service.
    if not rings or not _point_in_ring(point, rings[0]):
        return False
    return not any(_point_in_ring(point, ring) for ring in rings[1:])


def _polygon_parts(geometry: dict[str, Any]) -> Iterable[list[Any]]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Polygon" and isinstance(coordinates, list):
        yield coordinates
    elif kind == "MultiPolygon" and isinstance(coordinates, list):
        yield from (part for part in coordinates if isinstance(part, list))


def _route_samples(geometry: Any) -> list[tuple[float, float, float]]:
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        return []
    raw = geometry.get("coordinates")
    if not isinstance(raw, list) or len(raw) < 2:
        return []
    coordinates: list[tuple[float, float]] = []
    for item in raw:
        try:
            lon, lat = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90:
            if not coordinates or coordinates[-1] != (lon, lat):
                coordinates.append((lon, lat))
    if len(coordinates) < 2:
        return []
    lengths = []
    for (lon1, lat1), (lon2, lat2) in zip(coordinates, coordinates[1:]):
        lat_mid = math.radians((lat1 + lat2) / 2)
        dx = math.radians(lon2 - lon1) * 6_371_000 * math.cos(lat_mid)
        dy = math.radians(lat2 - lat1) * 6_371_000
        lengths.append(math.hypot(dx, dy))
    total = sum(lengths)
    if total <= 0:
        return []
    count = min(MAX_ROUTE_SAMPLES, max(2, math.ceil(total / SAMPLE_SPACING_METRES) + 1))
    result: list[tuple[float, float, float]] = []
    segment = 0
    before = 0.0
    for index in range(count):
        target = total * index / (count - 1)
        while segment < len(lengths) - 1 and before + lengths[segment] < target:
            before += lengths[segment]
            segment += 1
        length = lengths[segment]
        fraction = 0 if length <= 0 else min(1.0, max(0.0, (target - before) / length))
        a, b = coordinates[segment], coordinates[segment + 1]
        result.append((a[0] + fraction * (b[0] - a[0]), a[1] + fraction * (b[1] - a[1]), target))
    return result


def _fetch_boundaries() -> dict[str, Any]:
    params = urlencode({
        "where": "1=1", "outFields": "POL_STN_NM,DIST_NM", "returnGeometry": "true",
        "outSR": "4326", "f": "geojson",
    })
    request = Request(f"{BOUNDARY_SERVICE_URL}?{params}", headers={
        "User-Agent": "NAVIRA/1.0 (+https://github.com/singhxagauri-jpg/Navira)",
        "Accept": "application/geo+json, application/json",
    })
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise RuntimeError(f"Police boundary service returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list) or not features:
        raise ValueError("Police boundary service returned no station polygons")
    stations = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        name = str(properties.get("POL_STN_NM") or properties.get("pol_stn_nm") or "").strip()
        if name and list(_polygon_parts(geometry)):
            stations.append({
                "name": name,
                "district": str(properties.get("DIST_NM") or properties.get("dist_nm") or "").strip() or None,
                "geometry": geometry,
            })
    if not stations:
        raise ValueError("Police boundary response did not include station names and polygons")
    return {"stations": stations, "retrieved_at": datetime.now(timezone.utc).isoformat()}


def _boundaries() -> tuple[dict[str, Any], str]:
    global _cache
    now = time.monotonic()
    with _lock:
        if _cache and now - _cache[0] < CACHE_SECONDS:
            return _cache[1], "cached"
    try:
        result = _fetch_boundaries()
        with _lock:
            _cache = (time.monotonic(), result)
        return result, "fresh"
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError, ValueError):
        with _lock:
            cached = _cache
        if cached and now - cached[0] < STALE_SECONDS:
            return cached[1], "stale"
        raise


def match_route_police_stations(geometry: Any) -> dict[str, Any]:
    """Return stations whose official polygons contain route samples."""
    samples = _route_samples(geometry)
    if not samples:
        return {
            "status": "invalid_geometry", "source_url": BOUNDARY_SOURCE_URL,
            "stations": [], "matched_count": 0,
            "notice": "A usable route LineString is required to match police-station areas.",
        }
    try:
        boundary_data, cache_status = _boundaries()
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        return {
            "status": "unavailable", "source_url": BOUNDARY_SOURCE_URL,
            "stations": [], "matched_count": 0,
            "provider_error": "Official police-station boundary data could not be read right now.",
            "diagnostic": str(exc)[:240],
            "notice": "Without boundary data, NAVIRA will not infer a police station from a nearby place name.",
        }
    found: dict[str, dict[str, Any]] = {}
    for lon, lat, distance in samples:
        point = (lon, lat)
        for station in boundary_data["stations"]:
            key = station["name"].casefold()
            if key in found:
                continue
            if any(_point_in_polygon(point, part) for part in _polygon_parts(station["geometry"])):
                found[key] = {
                    "name": station["name"], "district": station["district"],
                    "first_sample_distance_m": round(distance),
                }
    matches = sorted(found.values(), key=lambda item: item["first_sample_distance_m"])
    return {
        "status": "matched" if matches else "no_boundary_matches",
        "source_url": BOUNDARY_SOURCE_URL,
        "retrieved_at": boundary_data["retrieved_at"],
        "cache_status": cache_status,
        "stations": matches,
        "matched_count": len(matches),
        "coverage": {"route_samples": len(samples), "spacing_metres": SAMPLE_SPACING_METRES, "cap": MAX_ROUTE_SAMPLES},
        "match_method": "route samples inside official police-station boundary polygons",
        "notice": "Station coverage is an approximate spatial match to published boundary polygons. It does not verify incident location or provide all registered crime counts.",
    }
