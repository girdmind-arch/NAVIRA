"""Route-corridor OSM infrastructure evidence; mapped tags are not field audits."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.app.services.facilities import OVERPASS_FALLBACKS


OVERPASS_URL = os.getenv("NAVIRA_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
OSM_MAP_URL = "https://www.openstreetmap.org/"
DELHI_PWD_URL = "https://pwd.delhi.gov.in/"
MCD_STREETLIGHT_URL = "https://mcdonline.nic.in/portal/downloadFile/circular_reg._complaints_lodged_on_mcd_311_app_230824113534834.pdf"
MCD_COMPLAINT_URL = "https://mcdonline.nic.in/portal/feedback"
NDMC_LIGHTING_URL = "https://www.ndmc.gov.in/ndmc/achievements_it.aspx"
NDMC_COMPLAINT_URL = "https://onlineservices.ndmc.gov.in/auth/"


class InfrastructureUnavailable(RuntimeError):
    """Live OSM infrastructure could not be retrieved or parsed."""


def _fetch(url: str, data: bytes) -> Any:
    request = Request(url, data=data, headers={
        "User-Agent": os.getenv("NAVIRA_GEOCODER_USER_AGENT", "NAVIRA/0.1 (route infrastructure evidence)"),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    })
    try:
        with urlopen(request, timeout=18) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise InfrastructureUnavailable(f"OpenStreetMap Overpass returned HTTP {error.code}.") from error
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise InfrastructureUnavailable("OpenStreetMap Overpass is temporarily unreachable.") from error


def _distance_m(a: list[float], b: list[float]) -> float:
    lat0 = math.radians((a[1] + b[1]) / 2)
    dx = math.radians(b[0] - a[0]) * 6_371_000 * math.cos(lat0)
    dy = math.radians(b[1] - a[1]) * 6_371_000
    return math.hypot(dx, dy)


def _nearest_route_distance_m(point: list[float], route: list[list[float]]) -> float:
    best = float("inf")
    earth_radius = 6_371_000
    for start, end in zip(route, route[1:]):
        lat0 = math.radians((point[1] + start[1] + end[1]) / 3)
        cosine = math.cos(lat0)
        px, py = math.radians(point[0]) * earth_radius * cosine, math.radians(point[1]) * earth_radius
        ax, ay = math.radians(start[0]) * earth_radius * cosine, math.radians(start[1]) * earth_radius
        bx, by = math.radians(end[0]) * earth_radius * cosine, math.radians(end[1]) * earth_radius
        vx, vy = bx - ax, by - ay
        denominator = vx * vx + vy * vy
        ratio = 0 if denominator == 0 else max(0, min(1, ((px - ax) * vx + (py - ay) * vy) / denominator))
        best = min(best, math.hypot(px - (ax + ratio * vx), py - (ay + ratio * vy)))
    return best


def _route_samples(coordinates: list[list[float]], spacing_m: float = 100, maximum: int = 180) -> list[list[float]]:
    """Sample by distance along the route, retaining its endpoints."""
    cumulative = [0.0]
    for start, end in zip(coordinates, coordinates[1:]):
        cumulative.append(cumulative[-1] + _distance_m(start, end))
    length = cumulative[-1]
    count = max(2, min(maximum, math.ceil(length / spacing_m) + 1))
    targets = [length * index / (count - 1) for index in range(count)]
    samples = []
    segment = 0
    for target in targets:
        while segment < len(cumulative) - 2 and cumulative[segment + 1] < target:
            segment += 1
        segment_length = cumulative[segment + 1] - cumulative[segment]
        ratio = 0 if segment_length == 0 else (target - cumulative[segment]) / segment_length
        start, end = coordinates[segment], coordinates[segment + 1]
        samples.append([start[0] + ratio * (end[0] - start[0]), start[1] + ratio * (end[1] - start[1])])
    return samples


def _tag_status(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"yes", "24/7", "automatic", "dusk-dawn", "sunset-sunrise"}:
        return "lit_tagged"
    if normalized in {"no", "none"}:
        return "unlit_tagged"
    if normalized in {"limited", "some"}:
        return "limited_lighting_tagged"
    return "unrecorded"


def _feature_distance_m(geometry: list[list[float]], route: list[list[float]]) -> float:
    """Check way segments as well as their vertices so long paths are retained."""
    if len(geometry) == 1:
        return _nearest_route_distance_m(geometry[0], route)
    samples = []
    for start, end in zip(geometry, geometry[1:]):
        steps = max(1, min(100, math.ceil(_distance_m(start, end) / 50)))
        samples.extend([
            [start[0] + (end[0] - start[0]) * index / steps, start[1] + (end[1] - start[1]) * index / steps]
            for index in range(steps)
        ])
    samples.append(geometry[-1])
    return min(_nearest_route_distance_m(point, route) for point in samples)


class RouteInfrastructure:
    def __init__(self, fetcher: Callable[[str, bytes], Any] | None = None, endpoints: tuple[str, ...] | None = None):
        self.fetcher = fetcher or _fetch
        self.endpoints = endpoints or tuple(dict.fromkeys((OVERPASS_URL, *OVERPASS_FALLBACKS)))

    def search(self, coordinates: list[list[float]], corridor_m: int | None = None) -> dict[str, Any]:
        if corridor_m is None:
            try:
                corridor_m = int(os.getenv("NAVIRA_INFRASTRUCTURE_CORRIDOR_M", "100"))
            except ValueError:
                corridor_m = 100
        radius = corridor_m
        radius = max(25, min(radius, 500))
        samples = _route_samples(coordinates)
        line = ",".join(f"{lat:.6f},{lon:.6f}" for lon, lat in samples)
        query = (
            f'[out:json][timeout:20];('
            f'nwr(around:{radius},{line})[highway="street_lamp"];'
            f'way(around:{radius},{line})[highway~"^(footway|path|pedestrian|steps)$"];'
            f');out geom center tags;'
        )
        body = urlencode({"data": query}).encode()
        payload = None
        last_error: Exception | None = None
        endpoint_used = None
        for endpoint in self.endpoints:
            try:
                candidate = self.fetcher(endpoint, body)
                if not isinstance(candidate, dict) or not isinstance(candidate.get("elements"), list) or candidate.get("remark"):
                    raise InfrastructureUnavailable("OpenStreetMap Overpass returned an incomplete response.")
                payload, endpoint_used = candidate, endpoint
                break
            except Exception as error:
                last_error = error
        if payload is None:
            raise InfrastructureUnavailable(str(last_error or "OpenStreetMap Overpass is unavailable.")) from last_error

        lamps, paths = [], []
        seen: set[tuple[str, int]] = set()
        for element in payload["elements"]:
            if not isinstance(element, dict) or not isinstance(element.get("tags"), dict):
                continue
            kind, element_type, element_id = element["tags"].get("highway"), element.get("type"), element.get("id")
            if not isinstance(element_id, int) or element_type not in {"node", "way", "relation"}:
                continue
            is_lamp = kind == "street_lamp"
            is_path = element_type == "way" and kind in {"footway", "path", "pedestrian", "steps"}
            if not is_lamp and not is_path:
                continue
            identity = (element_type, element_id)
            if identity in seen:
                continue
            seen.add(identity)
            if element_type == "node":
                geometry = [[element.get("lon"), element.get("lat")]]
            else:
                geometry = [[point.get("lon"), point.get("lat")] for point in element.get("geometry", []) if isinstance(point, dict)]
                if not geometry and isinstance(element.get("center"), dict):
                    geometry = [[element["center"].get("lon"), element["center"].get("lat")]]
            try:
                geometry = [[float(lon), float(lat)] for lon, lat in geometry if lon is not None and lat is not None]
            except (TypeError, ValueError):
                continue
            if not geometry:
                continue
            distance_to_route = _feature_distance_m(geometry, coordinates)
            if distance_to_route > radius:
                continue
            feature = {
                "id": f"{element_type}/{element_id}",
                "name": element["tags"].get("name"),
                "kind": "streetlight" if is_lamp else "pedestrian_path",
                "highway": kind,
                "lit_tag": _tag_status(element["tags"].get("lit")),
                "lighting_tag": element["tags"].get("lit"),
                "distance_to_route_m": round(distance_to_route),
                "source_url": f"https://www.openstreetmap.org/{element_type}/{element_id}",
            }
            (lamps if is_lamp else paths).append(feature)

        lit_counts = {key: sum(1 for item in paths if item["lit_tag"] == key) for key in ("lit_tagged", "unlit_tagged", "limited_lighting_tagged", "unrecorded")}
        official_sources = [
            {"name": "Delhi PWD", "status": "unavailable", "source_url": DELHI_PWD_URL, "note": "No route-level streetlight inspection feed is configured."},
            {"name": "MCD", "status": "unavailable", "source_url": MCD_STREETLIGHT_URL, "complaint_url": MCD_COMPLAINT_URL, "note": "Streetlight faults can be reported via MCD 311; complaint records are not available to NAVIRA."},
            {"name": "NDMC", "status": "unavailable", "source_url": NDMC_LIGHTING_URL, "complaint_url": NDMC_COMPLAINT_URL, "note": "Public smart-lighting information is not an individual route inspection record."},
        ]
        retrieved_at = datetime.now(timezone.utc).isoformat()
        return {
            "status": "available", "provider": "OpenStreetMap Overpass", "source_url": OSM_MAP_URL,
            "retrieved_at": retrieved_at, "corridor_m": radius,
            "coverage": {"status": "mapped_features_only", "route_points_sampled": len(samples), "features_returned": len(payload["elements"]), "osm_data_updated_at": (payload.get("osm3s") or {}).get("timestamp_osm_base"), "note": "Counts include mapped OpenStreetMap features in the requested corridor only. The route is sampled at up to 180 points; narrow gaps may be missed on long routes. Map completeness and field condition are unknown; missing mapped features do not mean none exist."},
            "streetlights_mapped": len(lamps), "footpaths_mapped": len(paths), "mapped_feature_count": len(lamps) + len(paths),
            "streetlights": lamps, "footpaths": paths, "lighting_tags_on_paths": lit_counts,
            "working_status": "unverified", "working_status_label": "Unverified — mapped features are not inspected for operation.",
            "night_visibility": "not_assessed", "night_visibility_label": "Not assessed — no lighting audit or night-visibility measurement is available.",
            "official_sources": official_sources,
            "limitations": ["OSM features are mapped records, not verified operational assets.", "The OSM lit tag describes mapped lighting context and does not confirm that a streetlight works.", "Government inspections and complaint counts are unavailable; none are estimated or fabricated."],
            "attribution": "© OpenStreetMap contributors",
            "query_endpoint": endpoint_used,
        }


def get_route_infrastructure(coordinates: list[list[float]], corridor_m: int | None = None) -> dict[str, Any]:
    return RouteInfrastructure().search(coordinates, corridor_m)
