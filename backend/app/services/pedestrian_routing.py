"""Small-area pedestrian routing over imported OSM way geometry.

This is a pilot path finder, not an accessibility or safety validator. OSM
highway tags and incomplete clipped extracts cannot prove on-the-ground access.
"""
from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from typing import Any


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlat, dlon = lat2-lat1, lon2-lon1
    hav = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371000 * 2 * math.asin(math.sqrt(hav))


def _node(point: list[float] | tuple[float, float]) -> tuple[float, float]:
    return (round(float(point[0]), 7), round(float(point[1]), 7))


def _allows_pedestrian_access(properties: dict[str, Any]) -> bool:
    """Conservatively omit ways explicitly tagged as unavailable to pedestrians."""
    foot = str(properties.get("foot", "")).strip().casefold()
    access = str(properties.get("access", "")).strip().casefold()
    highway = str(properties.get("highway", "")).strip().casefold()
    if foot in {"no", "private", "restricted", "none", "off"}:
        return False
    explicit_foot_access = foot in {"yes", "permissive", "designated"}
    if access in {"no", "private", "customers", "permit", "military"} and not explicit_foot_access:
        return False
    if highway in {"motorway", "motorway_link"} and not explicit_foot_access:
        return False
    return True


def find_pedestrian_route(db, origin: tuple[float, float], destination: tuple[float, float], *, max_snap_m: float = 150, walk_speed_mps: float = 1.2) -> dict[str, Any]:
    """Return one shortest-distance OSM-tag path, or a clear unavailable state."""
    edges: dict[tuple[float, float], list[tuple[tuple[float, float], float]]] = defaultdict(list)
    nodes: set[tuple[float, float]] = set()
    network_ids: set[int] = set()
    for row in db.execute("select network_id,geometry_geojson from pedestrian_segments"):
        feature = json.loads(row["geometry_geojson"])
        coords = feature.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            continue
        points = [_node(point) for point in coords]
        props = feature.get("properties") or {}
        if not _allows_pedestrian_access(props):
            continue
        network_ids.add(int(row["network_id"]))
        nodes.update(points)
        oneway = props.get("oneway:foot", props.get("oneway")) in {"yes", "1", "true"}
        reverse_oneway = props.get("oneway:foot") == "-1"
        for start, end in zip(points, points[1:]):
            length = _distance_m(start, end)
            if length <= 0:
                continue
            if not reverse_oneway:
                edges[start].append((end, length))
            if not oneway or reverse_oneway:
                edges[end].append((start, length))
    if not nodes:
        return {"status": "unavailable", "reason": "No pedestrian-tagged map data is loaded."}

    def snap(point: tuple[float, float]):
        nearest, distance = min(((n, _distance_m(point, n)) for n in nodes), key=lambda item: item[1])
        return nearest, distance

    start, start_gap = snap(origin)
    finish, finish_gap = snap(destination)
    if max(start_gap, finish_gap) > max_snap_m:
        return {"status": "unavailable", "reason": "One or both places are outside the bounded pilot pedestrian-map coverage."}
    if start == finish:
        return {"status": "unavailable", "reason": "The selected places are too close to form a route."}

    distances = {start: 0.0}
    previous: dict[tuple[float, float], tuple[float, float]] = {}
    queue = [(0.0, start)]
    while queue:
        distance, current = heapq.heappop(queue)
        if distance != distances.get(current):
            continue
        if current == finish:
            break
        for neighbor, weight in edges.get(current, []):
            candidate = distance + weight
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                previous[neighbor] = current
                heapq.heappush(queue, (candidate, neighbor))
    if finish not in distances:
        return {"status": "unavailable", "reason": "The pilot map does not contain a connected pedestrian path between these places."}
    path = [finish]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    path.insert(0, _node(origin))
    path.append(_node(destination))
    distance_m = distances[finish] + start_gap + finish_gap
    duration_s = distance_m / walk_speed_mps
    return {
        "status": "available",
        "network_ids": sorted(network_ids),
        "route": {
            "id": "osm-pilot-walk-shortest",
            "distance_m": round(distance_m, 1),
            "duration_s": round(duration_s),
            "geometry": {"type": "LineString", "coordinates": [list(point) for point in path]},
            "rank_reason": "Shortest distance across OSM pedestrian-tagged ways in the pilot extract; mapped access is not field-verified.",
        },
        "walking_speed_mps": walk_speed_mps,
        "snap_gaps_m": {"origin": round(start_gap, 1), "destination": round(finish_gap, 1)},
        "limitations": [
            "Pilot coverage is limited to six small locality windows and may omit paths or access restrictions.",
            "OSM tags and the walking-time estimate do not verify sidewalks, accessibility, lighting, safety, or current conditions.",
            "This route is not a safety ranking; no route is guaranteed safe.",
        ],
    }
