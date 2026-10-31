from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from backend.app import main
from backend.app.services.traffic import TomTomTraffic


def test_tomtom_traffic_samples_route_and_computes_delay():
    urls = []

    def fetch(url):
        urls.append(url)
        return {"flowSegmentData": {"currentSpeed": 20, "freeFlowSpeed": 50, "confidence": 0.9, "roadClosure": False, "dateTime": "2026-10-29T07:00:00Z", "coordinates": {"coordinate": [{"latitude": 28, "longitude": 77}, {"latitude": 28.01, "longitude": 77.01}]}}}

    coordinates = [[77.0 + i / 100, 28.0 + i / 100] for i in range(101)]
    result = TomTomTraffic(api_key="test-secret", fetcher=fetch).route_conditions(coordinates, 600, 12000)

    assert len(urls) == 5
    assert result["status"] == "available"
    assert result["level"] == "heavy"
    assert result["estimated_delay_s"] == 900
    assert result["estimated_travel_time_s"] == 1500
    assert result["coverage"] == {"sampled": 5, "requested": 5}
    assert all(parse_qs(urlparse(url).query)["key"] == ["test-secret"] for url in urls)
    assert result["points"][0]["latitude"] == coordinates[0][1]
    assert result["points"][0]["provider_observed_at"] == "2026-10-29T07:00:00Z"
    assert result["points"][0]["segment_coordinates"][1] == {"latitude": 28.01, "longitude": 77.01}


def test_tomtom_missing_key_is_unconfigured_and_does_not_call_provider():
    def fail(_url):
        raise AssertionError("provider must not be called without a key")

    result = TomTomTraffic(api_key="", fetcher=fail).route_conditions([[77, 28], [77.1, 28.1]], 60, 1000)
    assert result["status"] == "unconfigured"


def test_tomtom_partial_and_no_coverage_are_explicit():
    calls = 0

    def fetch(_url):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("provider down")
        return {"flowSegmentData": {"currentSpeed": 45, "freeFlowSpeed": 50}}

    partial = TomTomTraffic(api_key="key", fetcher=fetch).route_conditions([[77, 28], [77.1, 28.1]], 100, 2000)
    assert partial["status"] == "partial"
    assert partial["coverage"] == {"sampled": 1, "requested": 2}

    unavailable = TomTomTraffic(api_key="key", fetcher=lambda _url: {}).route_conditions(
        [[77, 28], [77.1, 28.1]], 100, 2000
    )
    assert unavailable["status"] == "unavailable"
    assert "points" not in unavailable


def test_route_traffic_endpoint_rejects_invalid_coordinates():
    with pytest.raises(ValidationError):
        main.RouteTrafficIn(coordinates=[[181, 28], [77, 28]], duration_s=60, distance_m=1000)
    with pytest.raises(ValidationError):
        main.RouteTrafficIn(coordinates=[[77, 28], [float("nan"), 28]], duration_s=60, distance_m=1000)


def test_route_traffic_endpoint_is_registered():
    assert "/api/v1/routes/traffic" in main.app.openapi()["paths"]


def test_route_traffic_endpoint_returns_unconfigured_without_secret(monkeypatch):
    monkeypatch.setattr(main, "get_route_traffic", lambda coordinates, duration, distance: {"status": "unconfigured"})
    body = main.RouteTrafficIn(coordinates=[[77, 28], [77.1, 28.1]], duration_s=60, distance_m=1000)
    assert main.route_traffic(body) == {"status": "unconfigured"}
