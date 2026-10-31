"""TomTom live traffic flow sampling for an existing route geometry."""
from __future__ import annotations

import json
import math
import os
import threading
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor


class TrafficUnavailable(RuntimeError):
    """The live traffic provider could not return usable flow data."""


class TomTomTraffic:
    """Query live TomTom flow at evenly spaced locations along a route."""

    BASE_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
    MAX_SAMPLES = 5

    def __init__(self, api_key: str | None = None, fetcher: Callable[[str], Any] | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("TOMTOM_API_KEY", "")
        self.fetcher = fetcher or self._fetch

    @staticmethod
    def _fetch(url: str) -> Any:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "NAVIRA/0.1"})
        try:
            with urlopen(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise TrafficUnavailable(f"Traffic provider returned HTTP {error.code}.") from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise TrafficUnavailable("Traffic provider could not be reached.") from error

    @staticmethod
    def _sample_indices(count: int, limit: int) -> list[int]:
        if count <= limit:
            return list(range(count))
        # Include the start and end while distributing calls along the full route.
        return sorted({round(i * (count - 1) / (limit - 1)) for i in range(limit)})

    @staticmethod
    def _level(current_speed: float, free_flow_speed: float, road_closure: bool) -> tuple[str, float | None]:
        if road_closure:
            return "heavy", 0.0
        if free_flow_speed <= 0 or current_speed < 0:
            raise TrafficUnavailable("Traffic provider returned invalid speed values.")
        ratio = min(1.0, current_speed / free_flow_speed)
        return ("light" if ratio >= .8 else "moderate" if ratio >= .5 else "heavy"), ratio

    def route_conditions(
        self, coordinates: list[list[float]], base_duration_s: float, base_distance_m: float
    ) -> dict[str, Any]:
        if not self.api_key:
            return {"status": "unconfigured", "provider": "TomTom", "reason": "Set TOMTOM_API_KEY on the backend."}
        if len(coordinates) < 2:
            return {"status": "unavailable", "provider": "TomTom", "reason": "The selected route has no usable geometry."}

        indices = self._sample_indices(len(coordinates), self.MAX_SAMPLES)
        def read_point(position: int) -> dict[str, Any]:
            lon, lat = coordinates[position]
            params = urlencode({"point": f"{lat:.6f},{lon:.6f}", "unit": "kmph", "key": self.api_key})
            payload = self.fetcher(f"{self.BASE_URL}?{params}")
            flow = payload.get("flowSegmentData", {}) if isinstance(payload, dict) else {}
            current_speed = float(flow["currentSpeed"])
            free_flow_speed = float(flow["freeFlowSpeed"])
            if not all(math.isfinite(value) for value in (current_speed, free_flow_speed)):
                raise TrafficUnavailable("Traffic provider returned invalid speeds.")
            closed = bool(flow.get("roadClosure", False))
            level, ratio = self._level(current_speed, free_flow_speed, closed)
            provider_observed_at = flow.get("dateTime") or flow.get("dateTimeUTC")
            segment_geometry = flow.get("coordinates", {}).get("coordinate", [])
            segment_coordinates = [
                {"latitude": float(point["latitude"]), "longitude": float(point["longitude"])}
                for point in segment_geometry
                if isinstance(point, dict) and "latitude" in point and "longitude" in point
            ] if isinstance(segment_geometry, list) else []
            point = {
                "route_index": position,
                "latitude": lat,
                "longitude": lon,
                "current_speed_kmh": current_speed,
                "free_flow_speed_kmh": free_flow_speed,
                "confidence": flow.get("confidence"),
                "road_closure": closed,
                "level": level,
                "speed_ratio": ratio,
                "segment_coordinates": segment_coordinates,
            }
            if isinstance(provider_observed_at, str) and provider_observed_at.strip():
                point["provider_observed_at"] = provider_observed_at
            return point

        with ThreadPoolExecutor(max_workers=self.MAX_SAMPLES) as pool:
            futures = [pool.submit(read_point, position) for position in indices]
            points = []
            errors = 0
            for future in futures:
                try:
                    points.append(future.result())
                except (TrafficUnavailable, KeyError, TypeError, ValueError, AttributeError, OSError):
                    errors += 1
        points.sort(key=lambda point: point["route_index"])

        if not points:
            return {"status": "unavailable", "provider": "TomTom", "reason": "No live traffic readings were available for this route."}

        ratios = [point["speed_ratio"] for point in points if point["speed_ratio"] is not None]
        average_ratio = sum(ratios) / len(ratios) if ratios else 0.0
        level = "light" if average_ratio >= .8 else "moderate" if average_ratio >= .5 else "heavy"
        # TomTom provides current/free-flow segment travel times; applying the
        # sampled ratio to the existing route duration is explicitly an estimate.
        estimated_delay_s = max(0, round(base_duration_s * (1 / max(average_ratio, .1) - 1)))
        retrieved_at = datetime.now(timezone.utc).isoformat()
        return {
            "status": "available" if errors == 0 else "partial",
            "provider": "TomTom",
            "retrieved_at": retrieved_at,
            "stale_after_seconds": 180,
            "level": level,
            "estimated_delay_s": estimated_delay_s,
            "estimated_travel_time_s": round(base_duration_s + estimated_delay_s),
            "base_travel_time_s": round(base_duration_s),
            "distance_m": round(base_distance_m),
            "coverage": {"sampled": len(points), "requested": len(indices)},
            "points": points,
            "method_note": "Traffic level is based on sampled current/free-flow speeds. Added delay is an estimate applied to the selected route's base travel time.",
        }


_traffic_provider = TomTomTraffic()
_provider_lock = threading.Lock()


def get_route_traffic(coordinates: list[list[float]], base_duration_s: float, base_distance_m: float) -> dict[str, Any]:
    # Re-read environment configuration so local and hosted configuration changes
    # take effect without exposing provider credentials to the frontend.
    global _traffic_provider
    api_key = os.getenv("TOMTOM_API_KEY", "")
    if _traffic_provider.api_key != api_key:
        with _provider_lock:
            if _traffic_provider.api_key != api_key:
                _traffic_provider = TomTomTraffic(api_key=api_key)
    return _traffic_provider.route_conditions(coordinates, base_duration_s, base_distance_m)
