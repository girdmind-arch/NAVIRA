"""Text-to-coordinate geocoding with a cached, throttled Nominatim adapter."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class LocationNotFound(ValueError):
    """The query is not a valid coordinate pair and has no geocoding match."""


class GeocodingUnavailable(RuntimeError):
    """The external geocoding service could not be reached or used."""


class NominatimGeocoder:
    """Low-volume geocoder using Nominatim's public Search API by default."""

    _COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")

    def __init__(
        self,
        base_url: str | None = None,
        user_agent: str | None = None,
        fetcher: Callable[[str], Any] | None = None,
        minimum_interval: float = 1.0,
        cache_ttl: float = 30 * 24 * 60 * 60,
    ) -> None:
        self.base_url = (base_url or os.getenv(
            "NAVIRA_GEOCODER_URL", "https://nominatim.openstreetmap.org"
        )).rstrip("/")
        self.user_agent = user_agent or os.getenv(
            "NAVIRA_GEOCODER_USER_AGENT",
            "NAVIRA/0.1 (+https://github.com/singhxagauri-jpg/Navira)",
        )
        self.fetcher = fetcher or self._fetch
        self.minimum_interval = minimum_interval
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._reverse_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._last_request_at = 0.0
        self._lock = threading.Lock()

    def _fetch(self, url: str) -> Any:
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code in {429, 500, 502, 503, 504}:
                raise GeocodingUnavailable("Location lookup is temporarily unavailable.") from error
            raise GeocodingUnavailable("The location lookup service returned an error.") from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise GeocodingUnavailable("Location lookup is temporarily unavailable.") from error

    @staticmethod
    def _coordinates(longitude: float, latitude: float, query: str, display_name: str, provider: str) -> dict[str, Any]:
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise LocationNotFound("Coordinates are outside valid latitude and longitude ranges.")
        return {
            "query": query,
            "display_name": display_name,
            "latitude": latitude,
            "longitude": longitude,
            "provider": provider,
        }

    def search(self, location: str, limit: int = 5) -> list[dict[str, Any]]:
        query = " ".join(location.split())
        if not query:
            raise LocationNotFound("Enter a location to continue.")

        coordinate_match = self._COORDINATES.fullmatch(query)
        if coordinate_match:
            longitude, latitude = map(float, coordinate_match.groups())
            return [self._coordinates(longitude, latitude, query, query, "coordinates")]

        limit = max(1, min(int(limit), 10))
        cache_key = f"{query.casefold()}:{limit}"
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached and now - cached[0] < self.cache_ttl:
            return [dict(item) for item in cached[1]["items"]]

        params = urlencode({
            "format": "jsonv2",
            "limit": limit,
            "addressdetails": 1,
            "accept-language": "en",
            "countrycodes": os.getenv("NAVIRA_GEOCODER_COUNTRIES", "in"),
            "q": query,
        })
        url = f"{self.base_url}/search?{params}"
        with self._lock:
            now = time.monotonic()
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self.cache_ttl:
                return [dict(item) for item in cached[1]["items"]]
            wait = self.minimum_interval - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()
            payload = self.fetcher(url)

        if not isinstance(payload, list) or not payload:
            raise LocationNotFound("No matching place was found.")
        results = []
        for match in payload:
            try:
                latitude = float(match["lat"])
                longitude = float(match["lon"])
                display_name = str(match["display_name"]).strip()
            except (KeyError, TypeError, ValueError) as error:
                raise GeocodingUnavailable("The location lookup returned an invalid result.") from error
            result = self._coordinates(longitude, latitude, query, display_name, "Nominatim")
            result["place_type"] = str(match.get("type") or match.get("class") or "place")
            result["place_class"] = str(match.get("class") or "place")
            results.append(result)
        self._cache[cache_key] = (time.monotonic(), {"items": results})
        if len(self._cache) > 500:
            self._cache.pop(next(iter(self._cache)))
        return [dict(item) for item in results]

    def geocode(self, location: str) -> dict[str, Any]:
        return self.search(location, limit=1)[0]

    def reverse(self, longitude: float, latitude: float, zoom: int = 14) -> dict[str, Any]:
        """Resolve a route sample to an approximate named locality with Nominatim."""
        longitude, latitude = float(longitude), float(latitude)
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise LocationNotFound("Coordinates are outside valid latitude and longitude ranges.")
        zoom = max(10, min(int(zoom), 18))
        key = f"{longitude:.4f}:{latitude:.4f}:{zoom}"
        now = time.monotonic()
        cached = self._reverse_cache.get(key)
        if cached and now - cached[0] < self.cache_ttl:
            return dict(cached[1])

        params = urlencode({
            "format": "jsonv2", "lat": latitude, "lon": longitude,
            "zoom": zoom, "addressdetails": 1, "accept-language": "en",
        })
        url = f"{self.base_url}/reverse?{params}"
        with self._lock:
            now = time.monotonic()
            cached = self._reverse_cache.get(key)
            if cached and now - cached[0] < self.cache_ttl:
                return dict(cached[1])
            wait = self.minimum_interval - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()
            payload = self.fetcher(url)

        if not isinstance(payload, dict) or not isinstance(payload.get("address"), dict):
            raise LocationNotFound("No named locality was found at this route sample.")
        result = {
            "display_name": str(payload.get("display_name") or ""),
            "address": {str(name): str(value) for name, value in payload["address"].items() if value is not None},
            "latitude": latitude,
            "longitude": longitude,
            "provider": "Nominatim reverse geocoding",
        }
        self._reverse_cache[key] = (time.monotonic(), result)
        if len(self._reverse_cache) > 1000:
            self._reverse_cache.pop(next(iter(self._reverse_cache)))
        return dict(result)


geocoder = NominatimGeocoder()


def geocode_location(location: str) -> dict[str, Any]:
    return geocoder.geocode(location)


def reverse_geocode_location(longitude: float, latitude: float, zoom: int = 14) -> dict[str, Any]:
    return geocoder.reverse(longitude, latitude, zoom)


def search_locations(location: str, limit: int = 5) -> list[dict[str, Any]]:
    return geocoder.search(location, limit)


def geocode_incident_location(location: str) -> dict[str, Any]:
    broad_types = {
        "administrative", "city", "county", "hamlet", "locality", "municipality",
        "neighbourhood", "neighborhood", "province", "state", "suburb", "town", "village",
    }
    results = geocoder.search(location, limit=5)
    precise = [item for item in results if item["place_type"].casefold() not in broad_types]
    if not precise:
        raise LocationNotFound("The incident location did not resolve to a street address or precise place.")
    return precise[0]
