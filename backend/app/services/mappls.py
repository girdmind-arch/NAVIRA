"""MapmyIndia (Mappls) place search, routing and live-traffic travel time.

All calls use the Mappls static key (MAPPLS_STATIC_KEY) passed as `access_token`.
Set MAPPLS_REST_KEY to use a different (server-only) key for REST calls; the
static key is also handed to the browser for the map SDK, so restrict it to
NAVIRA's domain in the Mappls console.

Docs: https://github.com/mappls-api/mappls-rest-apis (autosuggest, place details,
routing `route_adv` / `route_eta`).
"""
from __future__ import annotations

import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

AUTOSUGGEST_URL = "https://search.mappls.com/search/places/autosuggest/json"
PLACE_DETAILS_URL = "https://place.mappls.com/O2O/entity/place-details/{eloc}"
ROUTE_URL = "https://route.mappls.com/route/direction/{resource}/{profile}/{points}"
SDK_URL = "https://sdk.mappls.com/map/sdk/web?v=3.0&layer=vector&access_token={key}"

PROFILES = {"car": "driving", "motorcycle": "biking", "walking": "walking"}
PROFILE_LABELS = {"driving": "car", "biking": "two-wheeler", "walking": "walking"}


class MapplsNotConfigured(RuntimeError):
    """No Mappls key is set on the server."""


class MapplsUnavailable(RuntimeError):
    """Mappls could not answer (rejected key, quota, network, no result)."""


def provider_mode() -> str:
    """'mappls' (default) or 'legacy' (OpenStreetMap/OSRM providers, used by older tests)."""
    return "legacy" if os.getenv("NAVIRA_MAP_PROVIDER", "mappls").strip().lower() == "legacy" else "mappls"


def static_key() -> str:
    return os.getenv("MAPPLS_STATIC_KEY", "").strip()


def rest_key() -> str:
    return os.getenv("MAPPLS_REST_KEY", "").strip() or static_key()


def not_configured_message(feature: str) -> str:
    return (f"{feature} uses MapmyIndia (Mappls), which is not configured yet. "
            "Add MAPPLS_STATIC_KEY in the server settings (Railway → Variables).")


def _describe_http(code: int) -> str:
    return {
        401: "Mappls rejected the API key (HTTP 401). Check MAPPLS_STATIC_KEY and that this API is enabled for the key in the Mappls console.",
        403: "Mappls refused the request (HTTP 403): the daily quota may be used up, or the key is not allowed for this server/domain.",
        412: "Mappls reported a missing parameter (HTTP 412).",
        204: "Mappls had a temporary database error (HTTP 204).",
        503: "Mappls is temporarily unavailable (HTTP 503).",
    }.get(code, f"Mappls returned HTTP {code}.")


def _get_json(url: str, timeout: float = 10) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "NAVIRA/0.2"})
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status == 204:
                raise MapplsUnavailable(_describe_http(204))
            body = response.read()
    except HTTPError as error:
        raise MapplsUnavailable(_describe_http(error.code)) from error
    except (URLError, TimeoutError, OSError) as error:
        raise MapplsUnavailable("Mappls could not be reached. Check the server's internet connection and try again.") from error
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MapplsUnavailable("Mappls returned an unreadable response.") from error


class MapplsClient:
    def __init__(self, key: str | None = None, fetch: Callable[[str], Any] | None = None):
        self.key = rest_key() if key is None else key
        self.fetch = fetch or _get_json

    def _require_key(self, feature: str) -> None:
        if not self.key:
            raise MapplsNotConfigured(not_configured_message(feature))

    # ------------------------------------------------------------------ search
    def place_coordinates(self, eloc: str) -> tuple[float, float] | None:
        payload = self.fetch(PLACE_DETAILS_URL.format(eloc=quote(eloc, safe="")) + "?" + urlencode({"access_token": self.key}))
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        if not isinstance(payload, dict):
            return None
        for lat_key, lng_key in (("latitude", "longitude"), ("lat", "lng"), ("entry_lat", "entry_lon")):
            try:
                lat, lng = float(payload[lat_key]), float(payload[lng_key])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180 and (lat, lng) != (0.0, 0.0):
                return lat, lng
        return None

    def search(self, query: str, limit: int = 5, near: tuple[float, float] | None = None) -> list[dict[str, Any]]:
        self._require_key("Place search")
        params = {"query": query.strip()[:45], "region": "IND", "tokenizeAddress": "", "access_token": self.key}
        if near:
            params["location"] = f"{near[0]:.6f},{near[1]:.6f}"
        payload = self.fetch(f"{AUTOSUGGEST_URL}?{urlencode(params)}")
        suggestions = payload.get("suggestedLocations") if isinstance(payload, dict) else None
        if not isinstance(suggestions, list):
            return []
        suggestions = [item for item in suggestions if isinstance(item, dict) and (item.get("eLoc") or item.get("mapplsPin"))][:limit]

        def resolve(item: dict[str, Any]) -> dict[str, Any] | None:
            lat, lng = item.get("latitude"), item.get("longitude")
            try:
                coords = (float(lat), float(lng)) if lat not in (None, "") and lng not in (None, "") else None
            except (TypeError, ValueError):
                coords = None
            eloc = str(item.get("eLoc") or item.get("mapplsPin"))
            if coords is None:
                try:
                    coords = self.place_coordinates(eloc)
                except MapplsUnavailable:
                    coords = None
            if coords is None:
                return None
            name = str(item.get("placeName") or "").strip()
            address = str(item.get("placeAddress") or "").strip()
            display = name if not address else address if address.lower().startswith(name.lower()) else f"{name}, {address}"
            return {
                "query": query, "display_name": display, "latitude": coords[0], "longitude": coords[1],
                "provider": "Mappls", "place_type": str(item.get("type") or "place").lower(), "mappls_pin": eloc,
            }

        with ThreadPoolExecutor(max_workers=max(1, min(5, len(suggestions)))) as pool:
            results = [result for result in pool.map(resolve, suggestions) if result]
        return results

    # ----------------------------------------------------------------- routing
    def directions(self, profile: str, origin: tuple[float, float], destination: tuple[float, float],
                   resource: str = "route_adv", alternatives: int = 2) -> dict[str, Any]:
        """origin/destination are (longitude, latitude)."""
        self._require_key("Routing")
        points = f"{origin[0]:.6f},{origin[1]:.6f};{destination[0]:.6f},{destination[1]:.6f}"
        params = {"geometries": "geojson", "overview": "full", "steps": "false", "access_token": self.key}
        if alternatives:
            params["alternatives"] = str(alternatives)
        if profile == "driving" and resource == "route_adv":
            params["rtype"] = "0"
        payload = self.fetch(ROUTE_URL.format(resource=resource, profile=profile, points=points) + "?" + urlencode(params), timeout=12)
        if not isinstance(payload, dict):
            raise MapplsUnavailable("Mappls returned an unexpected routing response.")
        if str(payload.get("code", "")).lower() not in ("ok", ""):
            reason = "no route was found between these places" if payload.get("code") == "NoRoute" else f"Mappls routing returned '{payload.get('code')}'"
            raise MapplsUnavailable(f"Mappls {PROFILE_LABELS.get(profile, profile)} routing: {reason}.")
        return payload


def _valid_line(geometry: Any) -> bool:
    coords = geometry.get("coordinates") if isinstance(geometry, dict) and geometry.get("type") == "LineString" else None
    if not isinstance(coords, list) or len(coords) < 2:
        return False
    for point in coords:
        try:
            lng, lat = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError):
            return False
        if not (math.isfinite(lng) and math.isfinite(lat) and -180 <= lng <= 180 and -90 <= lat <= 90):
            return False
    return True


class MapplsRouter:
    """Router adapter compatible with agents.compare(): routes(origin, destination) with 'lon,lat' strings."""

    def __init__(self, mode: str = "car", client: MapplsClient | None = None):
        self.mode = mode
        self.profile = PROFILES.get(mode, "driving")
        self.client = client or MapplsClient()
        self.api_key = self.client.key
        self.provider = f"MapmyIndia (Mappls) · {PROFILE_LABELS[self.profile]} routing"

    @staticmethod
    def _point(value: str) -> tuple[float, float]:
        try:
            lng, lat = map(float, value.split(","))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Mappls routing needs explicit longitude,latitude pairs") from None
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            raise ValueError("Coordinate out of range")
        return lng, lat

    def routes(self, origin: str, destination: str) -> list[dict[str, Any]]:
        payload = self.client.directions(self.profile, self._point(origin), self._point(destination))
        routes, seen = [], set()
        for index, route in enumerate(payload.get("routes") or [], start=1):
            if not isinstance(route, dict):
                continue
            distance, duration, geometry = route.get("distance"), route.get("duration"), route.get("geometry")
            if not isinstance(distance, (int, float)) or not isinstance(duration, (int, float)) or distance <= 0 or duration <= 0:
                continue
            if not _valid_line(geometry):
                continue
            signature = tuple((round(float(p[0]), 5), round(float(p[1]), 5)) for p in geometry["coordinates"])
            if signature in seen:
                continue
            seen.add(signature)
            routes.append({"id": f"mappls-{self.profile}-{index}", "distance_m": float(distance), "duration_s": float(duration), "geometry": geometry, "provider": "Mappls"})
        if not routes:
            raise MapplsUnavailable(f"Mappls returned no usable {PROFILE_LABELS[self.profile]} route for these places.")
        return routes


def traffic_eta(coordinates: list[list[float]], base_duration_s: float, base_distance_m: float,
                client: MapplsClient | None = None) -> dict[str, Any]:
    """Live-traffic travel time for a driving route (India), from Mappls route_eta."""
    client = client or MapplsClient()
    if not client.key:
        return {"status": "unconfigured", "provider": "Mappls", "reason": not_configured_message("Live traffic")}
    if len(coordinates) < 2:
        return {"status": "unavailable", "provider": "Mappls", "reason": "The selected route has no usable geometry."}
    start, end = coordinates[0], coordinates[-1]
    try:
        payload = client.directions("driving", (float(start[0]), float(start[1])), (float(end[0]), float(end[1])), resource="route_eta", alternatives=0)
        route = (payload.get("routes") or [None])[0] or {}
        live = float(route["duration"])
    except (MapplsUnavailable, KeyError, TypeError, ValueError, IndexError) as error:
        return {"status": "unavailable", "provider": "Mappls", "reason": str(error) if isinstance(error, MapplsUnavailable) else "Mappls returned no live-traffic travel time for this route."}
    from datetime import datetime, timezone
    base = max(1.0, float(base_duration_s))
    ratio = base / max(live, 1.0)
    level = "light" if ratio >= 0.8 else "moderate" if ratio >= 0.5 else "heavy"
    delay = max(0, round(live - base))
    return {
        "status": "available", "provider": "Mappls (MapmyIndia) live traffic", "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "stale_after_seconds": 180, "level": level, "estimated_delay_s": delay, "estimated_travel_time_s": round(max(live, base)),
        "base_travel_time_s": round(base), "distance_m": round(base_distance_m), "coverage": {"sampled": 1, "requested": 1}, "points": [],
        "method_note": "Live travel time from Mappls route_eta between the route's start and end; delay compares it with the selected route's base time.",
    }


def map_config() -> dict[str, Any]:
    key = static_key()
    return {
        "provider": "mappls",
        "configured": bool(key),
        "sdk_url": SDK_URL.format(key=quote(key, safe="")) if key else None,
        "message": None if key else not_configured_message("The map"),
    }
