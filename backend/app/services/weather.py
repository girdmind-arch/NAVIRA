"""OpenWeatherMap current conditions and short forecast for route samples."""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

logger = logging.getLogger(__name__)


class WeatherUnavailable(RuntimeError):
    """The configured weather provider did not return usable data."""


class OpenWeatherAgent:
    BASE_URL = "https://api.openweathermap.org/data/2.5"
    CACHE_TTL_SECONDS = 600
    MAX_ROUTE_POINTS = 3

    def __init__(self, api_key: str | None = None, fetcher: Callable[[str], Any] | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("OPENWEATHER_API_KEY", "")
        self.fetcher = fetcher or self._fetch
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _fetch(url: str) -> Any:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "NAVIRA/0.1"})
        try:
            with urlopen(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 401:
                raise WeatherUnavailable("OpenWeatherMap rejected the backend API key.") from error
            if error.code == 404:
                raise WeatherUnavailable("OpenWeatherMap has no weather data for this route location.") from error
            if error.code == 429:
                raise WeatherUnavailable("OpenWeatherMap request limit reached. Try again later.") from error
            raise WeatherUnavailable(f"OpenWeatherMap returned HTTP {error.code}.") from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise WeatherUnavailable("OpenWeatherMap could not be reached.") from error

    @staticmethod
    def _sample_indices(count: int, limit: int) -> list[int]:
        if count <= limit:
            return list(range(count))
        return sorted({round(index * (count - 1) / (limit - 1)) for index in range(limit)})

    def _request(self, endpoint: str, latitude: float, longitude: float) -> dict[str, Any]:
        query = urlencode({"lat": f"{latitude:.5f}", "lon": f"{longitude:.5f}", "units": "metric", "appid": self.api_key})
        result = self.fetcher(f"{self.BASE_URL}/{endpoint}?{query}")
        if not isinstance(result, dict) or result.get("cod") not in (None, 200, "200"):
            raise WeatherUnavailable("OpenWeatherMap returned an invalid response.")
        return result

    def _location_weather(self, latitude: float, longitude: float) -> dict[str, Any]:
        cache_key = f"{latitude:.3f}:{longitude:.3f}"
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self.CACHE_TTL_SECONDS:
                return dict(cached[1])

        current = self._request("weather", latitude, longitude)
        forecast = self._request("forecast", latitude, longitude)
        main = current.get("main") or {}
        wind = current.get("wind") or {}
        conditions = current.get("weather") or []
        condition = conditions[0] if conditions and isinstance(conditions[0], dict) else {}
        if not all(math.isfinite(float(main.get(field, float("nan")))) for field in ("temp", "feels_like", "humidity")):
            raise WeatherUnavailable("OpenWeatherMap returned incomplete current conditions.")
        entries = forecast.get("list") or []
        hourly = []
        for item in entries[:8]:
            item_main = item.get("main") or {}
            item_conditions = item.get("weather") or []
            item_condition = item_conditions[0] if item_conditions else {}
            if "temp" not in item_main:
                continue
            hourly.append({
                "time": item.get("dt_txt"),
                "temperature_c": round(float(item_main["temp"])),
                "condition": str(item_condition.get("description") or "Unknown").capitalize(),
                "icon": item_condition.get("icon"),
                "rain_probability": round(float(item.get("pop", 0)) * 100),
            })
        payload = {
            "status": "available",
            "location": str(current.get("name") or "Route location"),
            "latitude": latitude,
            "longitude": longitude,
            "current": {
                "temperature_c": round(float(main["temp"])),
                "feels_like_c": round(float(main["feels_like"])),
                "humidity_percent": round(float(main["humidity"])),
                "wind_speed_kmh": round(float(wind.get("speed", 0)) * 3.6, 1),
                "condition": str(condition.get("description") or "Unknown").capitalize(),
                "icon": condition.get("icon"),
            },
            "forecast": hourly,
            "rain_probability_percent": max((item["rain_probability"] for item in hourly), default=None),
            "alerts": [],
            "alerts_note": "Official severe-weather alerts are not included in the Current Weather and 5-day Forecast endpoints.",
            "observed_at": current.get("dt"),
            "retrieved_at": time.time(),
            "provider": "OpenWeatherMap",
        }
        with self._lock:
            self._cache[cache_key] = (time.monotonic(), payload)
            if len(self._cache) > 500:
                self._cache.pop(next(iter(self._cache)))
        return dict(payload)

    def route_weather(self, coordinates: list[list[float]]) -> dict[str, Any]:
        if not self.api_key:
            return {"status": "unconfigured", "provider": "OpenWeatherMap", "message": "Set OPENWEATHER_API_KEY on the backend."}
        indices = self._sample_indices(len(coordinates), self.MAX_ROUTE_POINTS)
        locations = []
        errors = []
        labels = ("Start",) if len(indices) == 1 else ("Start", "Destination") if len(indices) == 2 else ("Start", "Along route", "Destination")
        for index, label in zip(indices, labels):
            longitude, latitude = coordinates[index]
            try:
                locations.append({"route_position": label, **self._location_weather(latitude, longitude)})
            except (WeatherUnavailable, KeyError, TypeError, ValueError, AttributeError) as error:
                message = str(error) if isinstance(error, WeatherUnavailable) else "OpenWeatherMap returned incomplete weather data."
                logger.warning("Weather lookup failed for route sample %s: %s", label, message)
                errors.append(message)
        if not locations:
            return {"status": "unavailable", "provider": "OpenWeatherMap", "message": errors[0] if errors else "No route weather data is available."}
        return {
            "status": "available" if not errors else "partial",
            "provider": "OpenWeatherMap",
            "retrieved_at": max(item["retrieved_at"] for item in locations),
            "stale_after_seconds": self.CACHE_TTL_SECONDS,
            "locations": locations,
            "unavailable_locations": len(errors),
            "message": errors[0] if errors else None,
            "limitations": ["Forecasts are provider estimates and do not guarantee route safety.", "Weather is sampled at up to three points along the route."],
        }


_weather_agent = OpenWeatherAgent()
_agent_lock = threading.Lock()


def get_route_weather(coordinates: list[list[float]]) -> dict[str, Any]:
    global _weather_agent
    api_key = os.getenv("OPENWEATHER_API_KEY", "")
    if _weather_agent.api_key != api_key:
        with _agent_lock:
            if _weather_agent.api_key != api_key:
                _weather_agent = OpenWeatherAgent(api_key=api_key)
    return _weather_agent.route_weather(coordinates)
