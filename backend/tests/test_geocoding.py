import pytest
from fastapi import HTTPException
from urllib.parse import parse_qs, urlparse

from backend.app import main
from backend.app.services.geocoding import (
    GeocodingUnavailable,
    LocationNotFound,
    NominatimGeocoder,
    geocode_incident_location,
)


def test_nominatim_text_query_returns_valid_coordinates():
    requested = []
    payload = [{"lat": "29.3730", "lon": "78.1360", "display_name": "Bijnor, Uttar Pradesh, India"}]
    geocoder = NominatimGeocoder(fetcher=lambda url: requested.append(url) or payload, minimum_interval=0)

    result = geocoder.geocode(" Bijnor,   Uttar Pradesh ")

    assert result["query"] == "Bijnor, Uttar Pradesh"
    assert result["display_name"] == "Bijnor, Uttar Pradesh, India"
    assert result["latitude"] == 29.373
    assert result["longitude"] == 78.136
    assert "format=jsonv2" in requested[0]
    assert parse_qs(urlparse(requested[0]).query)["q"] == ["Bijnor, Uttar Pradesh"]


def test_geocoder_cache_avoids_repeated_public_requests():
    calls = []
    geocoder = NominatimGeocoder(
        fetcher=lambda _url: calls.append(1) or [{"lat": "28.6", "lon": "77.2", "display_name": "Delhi, India"}],
        minimum_interval=0,
    )

    first = geocoder.geocode("Delhi")
    second = geocoder.geocode(" delhi ")

    assert first == second
    assert len(calls) == 1


def test_nominatim_search_returns_locality_suggestions_with_coordinates():
    requested = []
    payload = [
        {"lat": "28.6139", "lon": "77.2090", "display_name": "Connaught Place, New Delhi, India", "type": "commercial"},
        {"lat": "28.6200", "lon": "77.2100", "display_name": "Connaught Place Metro, New Delhi, India", "type": "station"},
    ]
    geocoder = NominatimGeocoder(fetcher=lambda url: requested.append(url) or payload, minimum_interval=0)

    results = geocoder.search("Connaught Place Delhi")

    assert len(results) == 2
    assert results[0]["display_name"] == "Connaught Place, New Delhi, India"
    assert results[0]["place_type"] == "commercial"
    assert results[0]["latitude"] == 28.6139
    assert parse_qs(urlparse(requested[0]).query)["limit"] == ["5"]


def test_incident_geocoder_rejects_city_center_results(monkeypatch):
    from backend.app.services import geocoding
    city = NominatimGeocoder(
        fetcher=lambda _url: [{"lat": "28.6", "lon": "77.2", "display_name": "Delhi, India", "class": "boundary", "type": "city"}],
        minimum_interval=0,
    )
    monkeypatch.setattr(geocoding, "geocoder", city)

    with pytest.raises(LocationNotFound, match="precise place"):
        geocode_incident_location("a specific street incident")


def test_geocoder_rejects_missing_matches_and_bad_coordinates():
    no_match = NominatimGeocoder(fetcher=lambda _url: [], minimum_interval=0)
    with pytest.raises(LocationNotFound):
        no_match.geocode("no such place 984733")

    with pytest.raises(LocationNotFound):
        no_match.geocode("999,999")


def test_geocoder_reports_provider_failures():
    def fail(_url):
        raise GeocodingUnavailable("temporary outage")

    with pytest.raises(GeocodingUnavailable):
        NominatimGeocoder(fetcher=fail, minimum_interval=0).geocode("Delhi")


def test_route_api_geocodes_text_and_preserves_internal_coordinate_contract(monkeypatch, tmp_path):
    from backend.app import core as db_core
    monkeypatch.setattr(db_core, "DB_PATH", tmp_path / "geocode-route.sqlite3")
    db_core.init_db()
    resolved = {
        "Bijnor, Uttar Pradesh": {"query": "Bijnor, Uttar Pradesh", "display_name": "Bijnor, Uttar Pradesh, India", "latitude": 29.373, "longitude": 78.136, "provider": "Nominatim"},
        "AIIMS Delhi": {"query": "AIIMS Delhi", "display_name": "AIIMS, New Delhi, India", "latitude": 28.5672, "longitude": 77.21, "provider": "Nominatim"},
    }
    calls = []
    monkeypatch.setattr(main, "geocode_location", lambda query: resolved[query])
    monkeypatch.setattr(main, "compare", lambda origin, destination, **_kwargs: calls.append((origin, destination)) or {"alternatives": [], "provider_status": "provider_configured"})

    result = main.routes(main.RouteIn(origin="Bijnor, Uttar Pradesh", destination="AIIMS Delhi"))

    assert calls == [("78.136,29.373", "77.21,28.5672")]
    assert result["resolved_locations"]["origin"]["display_name"] == "Bijnor, Uttar Pradesh, India"


def test_route_api_uses_selected_suggestion_coordinates_without_city_center_fallback(monkeypatch, tmp_path):
    from backend.app import core as db_core
    monkeypatch.setattr(db_core, "DB_PATH", tmp_path / "selected-route.sqlite3")
    db_core.init_db()
    monkeypatch.setattr(main, "geocode_location", lambda _query: pytest.fail("selected place should not be re-geocoded"))
    calls = []
    monkeypatch.setattr(main, "compare", lambda origin, destination, **_kwargs: calls.append((origin, destination)) or {"alternatives": [], "provider_status": "provider_configured"})
    origin = {"query": "Connaught Place", "display_name": "Connaught Place, New Delhi", "latitude": 28.6315, "longitude": 77.2167, "provider": "Nominatim"}
    destination = {"query": "AIIMS", "display_name": "AIIMS, New Delhi", "latitude": 28.5672, "longitude": 77.21, "provider": "Nominatim"}

    result = main.routes(main.RouteIn(origin="Connaught Place", destination="AIIMS", origin_location=origin, destination_location=destination))

    assert calls == [("77.2167,28.6315", "77.21,28.5672")]
    assert result["resolved_locations"]["origin"]["display_name"] == origin["display_name"]


def test_route_api_returns_clear_location_errors(monkeypatch):
    monkeypatch.setattr(main, "geocode_location", lambda _query: (_ for _ in ()).throw(LocationNotFound()))
    with pytest.raises(HTTPException) as error:
        main.routes(main.RouteIn(origin="Unknown Place", destination="Delhi"))
    assert error.value.status_code == 422
    assert "couldn't find the starting location" in error.value.detail

    monkeypatch.setattr(main, "geocode_location", lambda _query: (_ for _ in ()).throw(GeocodingUnavailable()))
    with pytest.raises(HTTPException) as error:
        main.routes(main.RouteIn(origin="Delhi", destination="Bijnor"))
    assert error.value.status_code == 503
    assert "temporarily unavailable" in error.value.detail


def test_route_validation_accepts_text_and_rejects_blank_locations():
    assert main.RouteIn(origin="Delhi", destination="AIIMS Delhi").origin == "Delhi"
    with pytest.raises(ValueError):
        main.RouteIn(origin="   ", destination="Delhi")


def test_geocoding_search_endpoint_returns_bounded_suggestions(monkeypatch):
    monkeypatch.setattr(main, "search_locations", lambda query, limit: [{
        "query": query, "display_name": "Delhi, India", "latitude": 28.6, "longitude": 77.2, "provider": "Nominatim"
    }])
    result = main.geocoding_search(q="Delhi", limit=5)
    assert result["items"][0]["display_name"] == "Delhi, India"


def test_traffic_endpoint_explicitly_reports_unconfigured_provider():
    body = main.RouteTrafficIn(coordinates=[[77.2, 28.6], [77.3, 28.7]], duration_s=1200, distance_m=5000)
    result = main.route_traffic(body)
    assert result["status"] == "unconfigured"
    assert result["provider"] == "TomTom"
    assert "TOMTOM_API_KEY" in result["reason"]


def test_traffic_endpoint_rejects_invalid_geometry():
    with pytest.raises(ValueError):
        main.RouteTrafficIn(coordinates=[[181, 28.6], [77.3, 28.7]], duration_s=1200, distance_m=5000)
