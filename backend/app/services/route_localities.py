"""Bounded, cached reverse-geocoding of sample points along a road route."""
from __future__ import annotations

import math
from typing import Any, Callable

from backend.app.services.geocoding import LocationNotFound, GeocodingUnavailable, reverse_geocode_location


MAX_ROUTE_SAMPLES = 6
LOCALITY_FIELDS = (
    "neighbourhood", "suburb", "quarter", "residential", "city_district",
    "borough", "village", "town", "municipality", "city",
)
BROAD_NAMES = {"delhi", "new delhi", "nct of delhi", "india"}


def _distance_m(first: tuple[float, float], second: tuple[float, float]) -> float:
    lon1, lat1 = first
    lon2, lat2 = second
    average_latitude = math.radians((lat1 + lat2) / 2)
    return math.hypot(
        (lon2 - lon1) * 111_320 * math.cos(average_latitude),
        (lat2 - lat1) * 110_574,
    )


def sample_route(geometry: Any, maximum: int = MAX_ROUTE_SAMPLES) -> list[dict[str, float]]:
    """Place no more than six evenly spaced points on a GeoJSON LineString."""
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        return []
    raw = geometry.get("coordinates")
    if not isinstance(raw, list) or len(raw) < 2:
        return []
    points: list[tuple[float, float]] = []
    for coordinate in raw:
        if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
            continue
        try:
            longitude, latitude = float(coordinate[0]), float(coordinate[1])
        except (TypeError, ValueError):
            continue
        if math.isfinite(longitude) and math.isfinite(latitude) and -180 <= longitude <= 180 and -90 <= latitude <= 90:
            if not points or (longitude, latitude) != points[-1]:
                points.append((longitude, latitude))
    if len(points) < 2:
        return []

    lengths = [_distance_m(a, b) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    if total <= 0:
        return []
    count = min(maximum, max(3, math.ceil(total / 3000) + 1))
    samples: list[dict[str, float]] = []
    for index in range(count):
        target = total * index / (count - 1)
        accumulated = 0.0
        for segment_index, length in enumerate(lengths):
            if accumulated + length >= target or segment_index == len(lengths) - 1:
                ratio = 0.0 if length <= 0 else max(0.0, min(1.0, (target - accumulated) / length))
                first, second = points[segment_index], points[segment_index + 1]
                samples.append({
                    "longitude": first[0] + ratio * (second[0] - first[0]),
                    "latitude": first[1] + ratio * (second[1] - first[1]),
                    "distance_along_route_m": target,
                })
                break
            accumulated += length
    return samples


def _is_delhi_address(address: dict[str, Any]) -> bool:
    values = [str(value).casefold() for value in address.values()]
    state = str(address.get("state") or "").casefold()
    if "delhi" in state:
        return True
    return any(value in {"delhi", "new delhi", "nct of delhi"} for value in values)


def _locality_from_address(address: dict[str, Any]) -> tuple[str | None, str | None]:
    for field in LOCALITY_FIELDS:
        value = str(address.get(field) or "").strip()
        if value and value.casefold() not in BROAD_NAMES:
            return value, field
    return None, None


def resolve_route_localities(
    geometry: Any,
    reverse: Callable[[float, float], dict[str, Any]] = reverse_geocode_location,
) -> dict[str, Any]:
    """Resolve representative route samples to Delhi localities; never infer gaps."""
    points = sample_route(geometry)
    resolved_samples: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for point in points:
        sample = {**point, "status": "unresolved"}
        try:
            result = reverse(point["longitude"], point["latitude"])
            address = result.get("address") if isinstance(result, dict) else None
            if not isinstance(address, dict):
                raise LocationNotFound("No address returned for route sample.")
            if not _is_delhi_address(address):
                sample.update(status="outside_delhi", provider=result.get("provider"))
                resolved_samples.append(sample)
                continue
            locality, precision = _locality_from_address(address)
            if locality:
                sample.update(status="resolved", locality=locality, precision=precision, provider=result.get("provider"))
                key = locality.casefold()
                group = by_name.setdefault(key, {"name": locality, "precision": precision, "sample_distances_m": []})
                group["sample_distances_m"].append(round(point["distance_along_route_m"]))
            else:
                sample.update(status="no_locality_label", provider=result.get("provider"))
        except LocationNotFound:
            sample["status"] = "no_locality_label"
        except GeocodingUnavailable:
            sample["status"] = "provider_unavailable"
        except (OSError, ValueError, TypeError, KeyError):
            sample["status"] = "unresolved"
        resolved_samples.append(sample)

    localities = list(by_name.values())
    failed_count = sum(sample["status"] in {"provider_unavailable", "unresolved", "no_locality_label"} for sample in resolved_samples)
    return {
        "status": "resolved" if localities and failed_count == 0 else "partial" if localities else "unavailable",
        "method": "Nominatim reverse-geocoded route samples",
        "granularity": "Representative samples only; this does not enumerate every neighbourhood or prove an incident location.",
        "sample_count": len(points),
        "resolved_sample_count": sum(sample["status"] == "resolved" for sample in resolved_samples),
        "route_localities": localities,
        "samples": resolved_samples,
    }
