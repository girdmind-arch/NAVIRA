"""Nearby police and hospital places from OpenStreetMap and official fallbacks."""
from __future__ import annotations

import json
import math
import os
import threading
import time
from copy import deepcopy
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class FacilitiesUnavailable(RuntimeError):
    """The OpenStreetMap places provider could not be used."""


OVERPASS_FALLBACKS = (
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
FACILITY_CACHE_SECONDS = 10 * 60
POLICE_GIS_URL = "https://gsdl.org.in/arcgis/rest/services/Delhi_Police/Delhi_Police/MapServer/4/query"
POLICE_GIS_SOURCE = "https://gsdl.org.in/arcgis/rest/services/Delhi_Police/Delhi_Police/MapServer/4"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_SEARCH_URL = "https://photon.komoot.io/api"
_police_gis_cache: tuple[float, list[dict[str, Any]]] | None = None
_police_gis_lock = threading.Lock()
_nominatim_cache: dict[tuple[float, float, int], tuple[float, list[dict[str, Any]]]] = {}
_nominatim_lock = threading.Lock()
_nominatim_last_request = 0.0
_photon_cache: dict[tuple[float, float, int, str], tuple[float, list[dict[str, Any]]]] = {}
_photon_lock = threading.Lock()


class OverpassPlaces:
    def __init__(self, endpoint: str | None = None, fetcher: Callable[[str, bytes], Any] | None = None) -> None:
        configured = endpoint or os.getenv("NAVIRA_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
        self.endpoints = tuple(dict.fromkeys((configured, *OVERPASS_FALLBACKS)))
        self.fetcher = fetcher or self._fetch
        self._cache: dict[tuple[float, float, str, int, int], tuple[float, list[dict[str, Any]]]] = {}
        self._cache_lock = threading.Lock()

    @staticmethod
    def _fetch(url: str, data: bytes) -> Any:
        request = Request(
            url,
            data=data,
            headers={
                "User-Agent": os.getenv("NAVIRA_GEOCODER_USER_AGENT", "NAVIRA/0.1 (OpenStreetMap places)"),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=4) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise FacilitiesUnavailable(f"OpenStreetMap Overpass returned HTTP {error.code}.") from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise FacilitiesUnavailable("OpenStreetMap Overpass is temporarily unreachable.") from error

    def search(self, latitude: float, longitude: float, category: str, radius_m: int, limit: int) -> list[dict[str, Any]]:
        cache_key = (round(latitude, 5), round(longitude, 5), category, radius_m, limit)
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < FACILITY_CACHE_SECONDS:
                return deepcopy(cached[1])
        categories = {
            "police": ['[amenity="police"]'],
            "hospitals": ['[amenity="hospital"]', '[healthcare="hospital"]'],
            "all": ['[amenity="police"]', '[amenity="hospital"]', '[healthcare="hospital"]'],
        }
        if category not in categories:
            raise ValueError("Category must be police, hospitals, or all.")
        clauses = [
            f'nwr{selector}(around:{radius_m},{latitude},{longitude});'
            for selector in categories[category]
        ]
        query = f'[out:json][timeout:10];({"".join(clauses)});out center tags;'
        request_body = urlencode({"data": query}).encode()
        payload = None
        last_error: Exception | None = None
        for endpoint in self.endpoints:
            try:
                candidate = self.fetcher(endpoint, request_body)
                if not isinstance(candidate, dict) or not isinstance(candidate.get("elements"), list):
                    raise FacilitiesUnavailable("OpenStreetMap Overpass returned an invalid response.")
                if candidate.get("remark"):
                    raise FacilitiesUnavailable("OpenStreetMap Overpass could not complete the nearby places query.")
                payload = candidate
                self.last_successful_endpoint = endpoint
                break
            except FacilitiesUnavailable as error:
                last_error = error
            except Exception as error:
                last_error = FacilitiesUnavailable("OpenStreetMap Overpass is temporarily unavailable.")
                last_error.__cause__ = error
        if payload is None:
            raise FacilitiesUnavailable(
                str(last_error) if last_error else "Nearby places are temporarily unavailable."
            ) from last_error

        places = []
        seen: set[tuple[str, int]] = set()
        for element in payload["elements"]:
            if not isinstance(element, dict) or not isinstance(element.get("tags"), dict):
                continue
            tags = element["tags"]
            amenity = tags.get("amenity")
            kind = "police" if amenity == "police" else "hospital" if amenity == "hospital" or tags.get("healthcare") == "hospital" else None
            if kind is None or (category != "all" and kind != category.rstrip("s")):
                continue
            place_type = str(element.get("type") or "")
            place_id = element.get("id")
            if not place_type or not isinstance(place_id, int) or (place_type, place_id) in seen:
                continue
            seen.add((place_type, place_id))
            point = element if place_type == "node" else element.get("center") or {}
            try:
                place_latitude = float(point["lat"])
                place_longitude = float(point["lon"])
                if not (-90 <= place_latitude <= 90 and -180 <= place_longitude <= 180):
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            address = ", ".join(filter(None, (
                " ".join(filter(None, (tags.get("addr:housenumber"), tags.get("addr:street")))),
                tags.get("addr:suburb") or tags.get("addr:neighbourhood"),
                tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village"),
                tags.get("addr:state"),
                tags.get("addr:postcode"),
            )))
            places.append({
                "id": f"osm-{place_type}-{place_id}",
                "name": tags.get("name") or tags.get("official_name") or "",
                "kind": kind,
                "latitude": place_latitude,
                "longitude": place_longitude,
                "address": address or None,
                "location_source": "OSM mapped node" if place_type == "node" else "OSM mapped area center",
                "operating_status": "unverified",
                "source_url": f"https://www.openstreetmap.org/{place_type}/{place_id}",
                "tags": {key: tags[key] for key in ("opening_hours", "operator", "phone") if tags.get(key)},
            })
        places.sort(key=lambda place: straight_line_distance_m(
            latitude, longitude, place["latitude"], place["longitude"]
        ))
        if category == "all":
            # Avoid a hospital-heavy result set hiding every nearby police
            # station (or the reverse) when the UI asks for both categories.
            selected: list[dict[str, Any]] = []
            for kind in ("police", "hospital"):
                selected.extend([place for place in places if place["kind"] == kind][:10])
            selected_ids = {place["id"] for place in selected}
            selected.extend(place for place in places if place["id"] not in selected_ids)
            places = selected
        result = places[:limit]
        with self._cache_lock:
            if len(self._cache) >= 256:
                oldest_key = min(self._cache, key=lambda key: self._cache[key][0])
                self._cache.pop(oldest_key, None)
            self._cache[cache_key] = (time.monotonic(), deepcopy(result))
        return result


places_provider = OverpassPlaces()


def _official_police_places(latitude: float, longitude: float, radius_m: int, limit: int) -> list[dict[str, Any]]:
    """Use Delhi Police's published station point layer if Overpass is down."""
    global _police_gis_cache
    now = time.monotonic()
    with _police_gis_lock:
        cached = _police_gis_cache
    if not cached or now - cached[0] >= 24 * 60 * 60:
        params = urlencode({
            "where": "1=1", "outFields": "NAME,DISTRICT,FID", "returnGeometry": "true",
            "outSR": "4326", "f": "json",
        })
        request = Request(f"{POLICE_GIS_URL}?{params}", headers={
            "User-Agent": os.getenv("NAVIRA_GEOCODER_USER_AGENT", "NAVIRA/0.1 (nearby facilities)"),
            "Accept": "application/json",
        })
        try:
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise FacilitiesUnavailable("Delhi Police station location data is temporarily unavailable.") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("features"), list) or payload.get("error"):
            raise FacilitiesUnavailable("Delhi Police station location data returned an invalid response.")
        items = []
        for feature in payload["features"]:
            if not isinstance(feature, dict):
                continue
            attrs = feature.get("attributes") or {}
            point = feature.get("geometry") or {}
            try:
                lat, lon = float(point["y"]), float(point["x"])
            except (KeyError, TypeError, ValueError):
                continue
            name = str(attrs.get("NAME") or "").strip()
            if not name:
                continue
            district = str(attrs.get("DISTRICT") or "").strip()
            fid = attrs.get("FID")
            items.append({
                "id": f"delhipolice-station-{fid if fid is not None else name.casefold().replace(' ', '-')}",
                "name": name.removeprefix("PS ").strip(),
                "kind": "police", "latitude": lat, "longitude": lon,
                "address": f"{district} District, Delhi" if district else "Delhi",
                "location_source": "Delhi Police official station-location GIS point",
                "operating_status": "unverified", "source_url": POLICE_GIS_SOURCE,
                "tags": {},
            })
        if not items:
            raise FacilitiesUnavailable("Delhi Police station location data contains no mappable points.")
        cached = (time.monotonic(), items)
        with _police_gis_lock:
            _police_gis_cache = cached
    result = deepcopy(cached[1])
    result = [place for place in result if straight_line_distance_m(latitude, longitude, place["latitude"], place["longitude"]) <= radius_m]
    result.sort(key=lambda place: straight_line_distance_m(latitude, longitude, place["latitude"], place["longitude"]))
    return result[:limit]


def _photon_facilities(latitude: float, longitude: float, radius_m: int, limit: int, kind: str) -> list[dict[str, Any]]:
    """Return tag-filtered, bbox-limited OSM search matches from Photon."""
    key = (round(latitude, 5), round(longitude, 5), radius_m, kind)
    now = time.monotonic()
    with _photon_lock:
        cached = _photon_cache.get(key)
        if cached and now - cached[0] < FACILITY_CACHE_SECONDS:
            return deepcopy(cached[1][:limit])

    lat_delta = radius_m / 110_574
    lon_delta = radius_m / (111_320 * max(0.1, math.cos(math.radians(latitude))))
    osm_tag = "amenity:hospital" if kind == "hospital" else "amenity:police"
    query = "hospital" if kind == "hospital" else "police station"
    params = urlencode({
        "q": query, "lat": latitude, "lon": longitude, "zoom": 13,
        "bbox": f"{longitude - lon_delta},{latitude - lat_delta},{longitude + lon_delta},{latitude + lat_delta}",
        "osm_tag": osm_tag, "limit": 50, "lang": "en",
    })
    request = Request(f"{PHOTON_SEARCH_URL}?{params}", headers={
        "User-Agent": os.getenv("NAVIRA_GEOCODER_USER_AGENT", "NAVIRA/0.1 (nearby facilities)"),
        "Accept": "application/geo+json, application/json",
    })
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise FacilitiesUnavailable("OpenStreetMap Photon search is temporarily unavailable.") from error
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise FacilitiesUnavailable("OpenStreetMap Photon returned an invalid response.")
    items = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if properties.get("osm_key") != "amenity" or properties.get("osm_value") != kind:
            continue
        coordinates = geometry.get("coordinates")
        try:
            lon, lat = float(coordinates[0]), float(coordinates[1])
        except (TypeError, ValueError, IndexError):
            continue
        if straight_line_distance_m(latitude, longitude, lat, lon) > radius_m:
            continue
        osm_type = str(properties.get("osm_type") or "").upper()
        element_type = {"N": "node", "W": "way", "R": "relation"}.get(osm_type)
        osm_id = properties.get("osm_id")
        source_url = f"https://www.openstreetmap.org/{element_type}/{osm_id}" if element_type and osm_id else "https://www.openstreetmap.org/"
        name = str(properties.get("name") or "").strip()
        if not name:
            continue
        address = ", ".join(str(properties[field]) for field in ("housenumber", "street", "district", "city", "state", "postcode") if properties.get(field))
        place_kind = "police" if kind == "police" else "hospital"
        items.append({
            "id": f"photon-{place_kind}-{osm_type.lower()}-{osm_id or name.casefold().replace(' ', '-')}",
            "name": name, "kind": place_kind, "latitude": lat, "longitude": lon,
            "address": address or None,
            "location_source": "OSM Photon tag-filtered local search",
            "operating_status": "unverified", "source_url": source_url,
            "tags": feature.get("extra") or {},
        })
    items.sort(key=lambda place: straight_line_distance_m(latitude, longitude, place["latitude"], place["longitude"]))
    with _photon_lock:
        if len(_photon_cache) >= 256:
            oldest_key = min(_photon_cache, key=lambda cache_key: _photon_cache[cache_key][0])
            _photon_cache.pop(oldest_key, None)
        _photon_cache[key] = (time.monotonic(), deepcopy(items))
    return items[:limit]


def _nominatim_hospitals(latitude: float, longitude: float, radius_m: int, limit: int) -> list[dict[str, Any]]:
    """Best-match hospital fallback; Nominatim does not guarantee exhaustive results."""
    global _nominatim_last_request
    key = (round(latitude, 5), round(longitude, 5), radius_m)
    now = time.monotonic()
    with _nominatim_lock:
        cached = _nominatim_cache.get(key)
        if cached and now - cached[0] < FACILITY_CACHE_SECONDS:
            return deepcopy(cached[1][:limit])
        wait = max(0.0, 1.1 - (now - _nominatim_last_request))
        if wait:
            time.sleep(wait)
        _nominatim_last_request = time.monotonic()

    lat_delta = radius_m / 110_574
    lon_delta = radius_m / (111_320 * max(0.1, math.cos(math.radians(latitude))))
    params = urlencode({
        "q": "[hospital]",
        "viewbox": f"{longitude - lon_delta},{latitude + lat_delta},{longitude + lon_delta},{latitude - lat_delta}",
        "bounded": 1, "format": "jsonv2", "limit": 50, "countrycodes": "in",
        "addressdetails": 1, "extratags": 1,
    })
    request = Request(f"{NOMINATIM_SEARCH_URL}?{params}", headers={
        "User-Agent": os.getenv("NAVIRA_GEOCODER_USER_AGENT", "NAVIRA/0.1 (nearby facilities)"),
        "Accept": "application/json",
    })
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise FacilitiesUnavailable("OpenStreetMap hospital search is temporarily unavailable.") from error
    if not isinstance(payload, list):
        raise FacilitiesUnavailable("OpenStreetMap hospital search returned an invalid response.")
    items = []
    for result in payload:
        if not isinstance(result, dict) or result.get("type") != "hospital":
            continue
        try:
            lat, lon = float(result["lat"]), float(result["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        distance = straight_line_distance_m(latitude, longitude, lat, lon)
        if distance > radius_m:
            continue
        osm_type = str(result.get("osm_type") or "").casefold()
        osm_id = result.get("osm_id")
        source_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}" if osm_type in {"node", "way", "relation"} and osm_id else "https://www.openstreetmap.org/"
        address_parts = result.get("address") if isinstance(result.get("address"), dict) else {}
        address = ", ".join(str(address_parts[key]) for key in ("road", "suburb", "city", "state", "postcode") if address_parts.get(key))
        items.append({
            "id": f"nominatim-hospital-{osm_type}-{osm_id or result.get('place_id')}",
            "name": result.get("name") or str(result.get("display_name") or "").split(",")[0],
            "kind": "hospital", "latitude": lat, "longitude": lon,
            "address": address or result.get("display_name"),
            "location_source": "OSM Nominatim bounded best-match search",
            "operating_status": "unverified", "source_url": source_url,
            "tags": (result.get("extratags") or {}),
        })
    items.sort(key=lambda place: straight_line_distance_m(latitude, longitude, place["latitude"], place["longitude"]))
    with _nominatim_lock:
        if len(_nominatim_cache) >= 256:
            oldest_key = min(_nominatim_cache, key=lambda cache_key: _nominatim_cache[cache_key][0])
            _nominatim_cache.pop(oldest_key, None)
        _nominatim_cache[key] = (time.monotonic(), deepcopy(items))
    return items[:limit]


def straight_line_distance_m(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float) -> int:
    radius = 6_371_000
    lat1, lat2 = math.radians(origin_lat), math.radians(dest_lat)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(dest_lon - origin_lon)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return round(radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value)))


def nearby_facilities(
    latitude: float,
    longitude: float,
    category: str,
    radius_m: int,
    limit: int,
    places: OverpassPlaces | None = None,
    router: Any | None = None,
) -> dict[str, Any]:
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Coordinates are outside valid latitude and longitude ranges.")
    if not 250 <= radius_m <= 10_000:
        raise ValueError("Search radius must be between 250 and 10,000 metres.")
    if not 1 <= limit <= 30:
        raise ValueError("Result limit must be between 1 and 30.")

    provider = places or places_provider
    fallback_mode = False
    fallback_note = None
    try:
        found = provider.search(latitude, longitude, category, radius_m, limit)
    except FacilitiesUnavailable as overpass_error:
        fallback_mode = True
        found = []
        fallback_available = False
        fallback_errors = []
        police_source = None
        hospital_source = None
        if category in {"police", "all"}:
            try:
                found.extend(_official_police_places(latitude, longitude, radius_m, limit))
                fallback_available = True
                police_source = "Delhi Police official station-location GIS"
            except FacilitiesUnavailable as error:
                fallback_errors.append(str(error))
                try:
                    photon_police = _photon_facilities(latitude, longitude, radius_m, limit, "police")
                    found.extend(photon_police)
                    fallback_available = True
                    police_source = "OSM Photon tag-filtered search"
                except FacilitiesUnavailable as photon_error:
                    fallback_errors.append(str(photon_error))
        if category in {"hospitals", "all"}:
            try:
                photon_hospitals = _photon_facilities(latitude, longitude, radius_m, limit, "hospital")
                found.extend(photon_hospitals)
                fallback_available = True
                hospital_source = "OSM Photon tag-filtered search"
                if not photon_hospitals:
                    try:
                        found.extend(_nominatim_hospitals(latitude, longitude, radius_m, limit))
                        fallback_available = True
                        hospital_source = "OSM Nominatim bounded best-match search"
                    except FacilitiesUnavailable as error:
                        fallback_errors.append(str(error))
            except FacilitiesUnavailable as photon_error:
                fallback_errors.append(str(photon_error))
                try:
                    found.extend(_nominatim_hospitals(latitude, longitude, radius_m, limit))
                    fallback_available = True
                    hospital_source = "OSM Nominatim bounded best-match search"
                except FacilitiesUnavailable as error:
                    fallback_errors.append(str(error))
        if not fallback_available:
            suffix = f" {' '.join(fallback_errors)}" if fallback_errors else ""
            raise FacilitiesUnavailable(f"Nearby places are unavailable from Overpass and fallback sources.{suffix}") from overpass_error
        # Keep both categories visible in the combined view, then fill remaining
        # slots by proximity. Nominatim hospital results are best matches only.
        if category == "all":
            selected = []
            for kind in ("police", "hospital"):
                selected.extend([place for place in found if place["kind"] == kind][:10])
            selected_ids = {place["id"] for place in selected}
            selected.extend(place for place in found if place["id"] not in selected_ids)
            found = selected[:limit]
        fallback_sources = []
        if police_source:
            fallback_sources.append(f"police results came from {police_source}")
        elif category in {"police", "all"}:
            fallback_sources.append("no police-station fallback source was available")
        if hospital_source:
            hospital_note = f"hospital results came from {hospital_source}"
            if "Nominatim" in hospital_source or "Photon" in hospital_source:
                hospital_note += " and may be incomplete"
            fallback_sources.append(hospital_note)
        elif category in {"hospitals", "all"}:
            fallback_sources.append("no hospital fallback source was available")
        fallback_note = "Overpass could not be reached; " + "; ".join(fallback_sources) + "."
        if fallback_errors:
            fallback_note += f" Some fallback sources were unavailable: {' '.join(fallback_errors)}"
    for place in found:
        place["straight_line_distance_m"] = straight_line_distance_m(
            latitude, longitude, place["latitude"], place["longitude"]
        )
        place["road_distance_m"] = None
        place["road_duration_s"] = None
        place["route_status"] = "unavailable"

    found.sort(key=lambda item: item["straight_line_distance_m"])
    routing_status = "unavailable"
    routing_note = "Road distance and time are unavailable; straight-line distance is shown for orientation only."
    if found and not fallback_mode:
        try:
            matrix = (router or _default_router()).table(
                f"{longitude},{latitude}",
                [f"{place['longitude']},{place['latitude']}" for place in found],
            )
            distances = matrix.get("distances") or [[]]
            durations = matrix.get("durations") or [[]]
            distance_row = distances[0] if distances else []
            duration_row = durations[0] if durations else []
            for index, place in enumerate(found):
                distance = distance_row[index] if index < len(distance_row) else None
                duration = duration_row[index] if index < len(duration_row) else None
                if isinstance(distance, (int, float)) and isinstance(duration, (int, float)):
                    place["road_distance_m"] = round(distance)
                    place["road_duration_s"] = round(duration)
                    place["route_status"] = "available"
            routing_status = "available" if any(item["route_status"] == "available" for item in found) else "unavailable"
            routing_note = (
                "Some facilities have no drivable route; their straight-line distance is shown for orientation only."
                if routing_status == "available"
                else "OSRM did not return drivable routes for these facilities; straight-line distance is shown for orientation only."
            )
        except RuntimeError:
            routing_note = "Road distance and time are temporarily unavailable; straight-line distance is shown for orientation only."

    found.sort(key=lambda item: (
        item["road_distance_m"] if item["road_distance_m"] is not None else item["straight_line_distance_m"],
        item["straight_line_distance_m"],
    ))
    return {
        "items": found,
        "category_counts": {
            "police": sum(1 for item in found if item["kind"] == "police"),
            "hospitals": sum(1 for item in found if item["kind"] == "hospital"),
        },
        "provider": " + ".join(dict.fromkeys(source for source in (police_source, hospital_source) if source)) if fallback_mode else "OpenStreetMap Overpass",
        "data_coverage_status": "partial_fallback" if fallback_mode else "openstreetmap_mapped_data",
        "coverage_note": fallback_note or "OpenStreetMap mapping can be incomplete; facility existence and operating status are not independently verified.",
        "routing_provider": "OSRM",
        "routing_status": routing_status,
        "routing_note": routing_note,
        "operating_status_note": "Facility listing, location accuracy, and current operating status are not independently verified by NAVIRA.",
    }


def _default_router() -> Any:
    from backend.app.services.agents import OSRMRouter
    return OSRMRouter()
