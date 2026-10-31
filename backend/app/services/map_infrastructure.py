"""Viewport-scoped OpenStreetMap infrastructure features for the NAVIRA map."""
from __future__ import annotations

import json
import os
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.app.services.facilities import OVERPASS_FALLBACKS

_CACHE_SECONDS = 10 * 60
_cache: dict[tuple[float, float, float, float], tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()
_PEDESTRIAN_HIGHWAYS = {"footway", "path", "pedestrian", "steps", "cycleway", "bridleway"}


class MapInfrastructureUnavailable(RuntimeError):
    """No Overpass endpoint returned a complete viewport response."""


def _fetch(endpoint: str, body: bytes) -> Any:
    request = Request(endpoint, data=body, headers={
        "User-Agent": os.getenv("NAVIRA_GEOCODER_USER_AGENT", "NAVIRA/0.1 (viewport infrastructure map)"),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    })
    try:
        with urlopen(request, timeout=float(os.getenv("NAVIRA_OVERPASS_TIMEOUT_S", "8"))) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise MapInfrastructureUnavailable(f"OpenStreetMap Overpass returned HTTP {error.code}.") from error
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise MapInfrastructureUnavailable("OpenStreetMap Overpass is temporarily unreachable.") from error


def _way_feature(element: dict[str, Any]) -> dict[str, Any] | None:
    tags = element.get("tags")
    geometry = element.get("geometry")
    if not isinstance(tags, dict) or not isinstance(geometry, list):
        return None
    coordinates = []
    for point in geometry:
        try:
            lon, lat = float(point["lon"]), float(point["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        if -180 <= lon <= 180 and -90 <= lat <= 90:
            coordinates.append([lon, lat])
    if len(coordinates) < 2:
        return None
    highway = str(tags.get("highway", ""))
    layers = ["pedestrian"] if highway in _PEDESTRIAN_HIGHWAYS else ["roads"]
    if tags.get("surface"):
        layers.append("surface")
    sidewalk = tags.get("sidewalk")
    sidewalk_status = "mapped" if sidewalk and sidewalk.casefold() != "no" else "explicitly_absent" if sidewalk and sidewalk.casefold() == "no" else "unknown"
    return {
        "type": "Feature",
        "id": f"way/{element.get('id')}",
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "properties": {
            "osm_id": element.get("id"), "osm_type": "way", "name": tags.get("name"),
            "highway": highway or None, "surface": tags.get("surface"), "lit": tags.get("lit"),
            "sidewalk": sidewalk, "sidewalk_status": sidewalk_status, "layers": layers,
            "mapping_status": "mapped", "source_url": f"https://www.openstreetmap.org/way/{element.get('id')}",
            "osm_tags": tags,
        },
    }


def _lamp_feature(element: dict[str, Any]) -> dict[str, Any] | None:
    tags = element.get("tags")
    if not isinstance(tags, dict):
        return None
    try:
        lon, lat = float(element["lon"]), float(element["lat"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return {
        "type": "Feature", "id": f"node/{element.get('id')}",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "osm_id": element.get("id"), "osm_type": "node", "name": tags.get("name"),
            "highway": "street_lamp", "lit": tags.get("lit"), "layers": ["lighting"],
            "mapping_status": "mapped", "working_status": "not_verified",
            "source_url": f"https://www.openstreetmap.org/node/{element.get('id')}", "osm_tags": tags,
        },
    }


class ViewportInfrastructure:
    def __init__(self, fetcher: Callable[[str, bytes], Any] | None = None, endpoints: tuple[str, ...] | None = None):
        configured = os.getenv("NAVIRA_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
        self.endpoints = endpoints or tuple(dict.fromkeys((configured, *OVERPASS_FALLBACKS)))
        self.fetcher = fetcher or _fetch

    def search(self, bbox: tuple[float, float, float, float], use_cache: bool = True) -> dict[str, Any]:
        west, south, east, north = bbox
        key = tuple(round(value, 5) for value in bbox)
        now = time.monotonic()
        if use_cache:
            with _cache_lock:
                entry = _cache.get(key)
                if entry and now - entry[0] < _CACHE_SECONDS:
                    return deepcopy(entry[1])

        query = (
            f"[out:json][timeout:10];(way[\"highway\"]({south},{west},{north},{east});"
            f"node[\"highway\"=\"street_lamp\"]({south},{west},{north},{east}););out geom tags;"
        )
        body = urlencode({"data": query}).encode()
        payload, endpoint_used, last_error = None, None, None
        for endpoint in self.endpoints:
            try:
                candidate = self.fetcher(endpoint, body)
                if not isinstance(candidate, dict) or not isinstance(candidate.get("elements"), list) or candidate.get("remark"):
                    raise MapInfrastructureUnavailable("OpenStreetMap Overpass returned an incomplete response.")
                payload, endpoint_used = candidate, endpoint
                break
            except Exception as error:
                last_error = error
        if payload is None:
            raise MapInfrastructureUnavailable(str(last_error or "OpenStreetMap Overpass is unavailable.")) from last_error

        features: dict[str, dict[str, Any]] = {}
        for element in payload["elements"]:
            if not isinstance(element, dict) or element.get("id") is None:
                continue
            element_type, tags = element.get("type"), element.get("tags")
            if not isinstance(tags, dict):
                continue
            if element_type == "node" and tags.get("highway") == "street_lamp":
                feature = _lamp_feature(element)
            elif element_type == "way" and tags.get("highway"):
                feature = _way_feature(element)
            else:
                feature = None
            if feature:
                features[feature["id"]] = feature

        feature_list = list(features.values())
        counts = {layer: sum(layer in f["properties"]["layers"] for f in feature_list)
                  for layer in ("roads", "pedestrian", "lighting", "surface")}
        result = {
            "type": "FeatureCollection", "features": feature_list, "counts": counts,
            "status": "available", "coverage_status": "mapped" if feature_list else "not_mapped",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "osm_data_updated_at": (payload.get("osm3s") or {}).get("timestamp_osm_base"),
            "bbox": list(bbox), "provider": "OpenStreetMap Overpass", "query_endpoint": endpoint_used,
            "source_url": "https://www.openstreetmap.org/", "attribution": "© OpenStreetMap contributors",
            "note": "Counts describe OSM records returned for this map area. No result means not mapped in this query, not absent in the real world. Mapped tags do not verify on-site condition or lamp operation.",
        }
        with _cache_lock:
            _cache[key] = (time.monotonic(), deepcopy(result))
            if len(_cache) > 128:
                oldest = min(_cache, key=lambda item: _cache[item][0])
                _cache.pop(oldest, None)
        return result


def get_viewport_infrastructure(bbox: tuple[float, float, float, float], use_cache: bool = True) -> dict[str, Any]:
    return ViewportInfrastructure().search(bbox, use_cache)
