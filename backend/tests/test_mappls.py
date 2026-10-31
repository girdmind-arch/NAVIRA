import pytest
from fastapi.testclient import TestClient

from backend.app import core, main
from backend.app.main import app
from backend.app.services import mappls
from backend.app.services.agents import compare

LINE = {"type": "LineString", "coordinates": [[77.2193, 28.6317], [77.2250, 28.6200], [77.2294, 28.6129]]}
LINE_2 = {"type": "LineString", "coordinates": [[77.2193, 28.6317], [77.2150, 28.6200], [77.2294, 28.6129]]}


class FakeFetch:
    def __init__(self, routes=None, fail=None):
        self.urls = []
        self.routes = routes
        self.fail = fail

    def __call__(self, url, timeout=10):
        self.urls.append(url)
        if self.fail:
            raise mappls.MapplsUnavailable(self.fail)
        if "autosuggest" in url:
            return {"suggestedLocations": [
                {"eLoc": "CP0001", "placeName": "Connaught Place", "placeAddress": "New Delhi, Delhi, 110001", "type": "LOCALITY"},
                {"eLoc": "NOCOORD", "placeName": "Unknown", "placeAddress": "Nowhere"},
            ]}
        if "place-details/CP0001" in url:
            return {"latitude": 28.6315, "longitude": 77.2167}
        if "place-details" in url:
            return {}
        if "route_eta" in url:
            return {"code": "Ok", "routes": [{"duration": 900, "distance": 4200, "geometry": LINE}]}
        if "route_adv" in url:
            return {"code": "Ok", "routes": self.routes if self.routes is not None else [
                {"distance": 4200, "duration": 600, "geometry": LINE},
                {"distance": 4800, "duration": 660, "geometry": LINE_2},
                {"distance": 4200, "duration": 600, "geometry": LINE},
            ]}
        raise AssertionError(url)


def test_search_is_india_only_and_resolves_coordinates():
    fetch = FakeFetch()
    items = mappls.MapplsClient(key="k", fetch=fetch).search("Connaught Place")
    assert items == [{"query": "Connaught Place", "display_name": "Connaught Place, New Delhi, Delhi, 110001", "latitude": 28.6315, "longitude": 77.2167, "provider": "Mappls", "place_type": "locality", "mappls_pin": "CP0001"}]
    assert "region=IND" in fetch.urls[0] and "access_token=k" in fetch.urls[0]


@pytest.mark.parametrize("mode,profile", [("car", "driving"), ("motorcycle", "biking"), ("walking", "walking")])
def test_router_uses_the_matching_mappls_profile_and_drops_duplicates(mode, profile):
    fetch = FakeFetch()
    router = mappls.MapplsRouter(mode, client=mappls.MapplsClient(key="k", fetch=fetch))
    routes = router.routes("77.2193,28.6317", "77.2294,28.6129")
    assert f"/route_adv/{profile}/77.219300,28.631700;77.229400,28.612900" in fetch.urls[0]
    assert "geometries=geojson" in fetch.urls[0]
    assert [r["id"] for r in routes] == [f"mappls-{profile}-1", f"mappls-{profile}-2"]
    result = compare("77.2193,28.6317", "77.2294,28.6129", router=router)
    assert result["provider_status"] == "provider_configured" and len(result["alternatives"]) == 2


def test_missing_key_is_reported_as_not_configured():
    router = mappls.MapplsRouter("car", client=mappls.MapplsClient(key="", fetch=FakeFetch()))
    result = compare("77.2193,28.6317", "77.2294,28.6129", router=router)
    assert result["provider_status"] == "unconfigured" and "MAPPLS_STATIC_KEY" in result["error"]


def test_rejected_key_message_is_specific():
    router = mappls.MapplsRouter("car", client=mappls.MapplsClient(key="bad", fetch=FakeFetch(fail=mappls._describe_http(401))))
    result = compare("77.2193,28.6317", "77.2294,28.6129", router=router)
    assert result["provider_status"] == "unavailable" and "HTTP 401" in result["error"]


def test_traffic_eta_compares_live_time_with_base_time():
    result = mappls.traffic_eta(LINE["coordinates"], 600, 4200, client=mappls.MapplsClient(key="k", fetch=FakeFetch()))
    assert result["status"] == "available" and result["estimated_delay_s"] == 300 and result["level"] == "moderate"


def test_api_uses_mappls_by_default_and_explains_missing_key(monkeypatch, tmp_path):
    monkeypatch.setenv("NAVIRA_MAP_PROVIDER", "mappls")
    monkeypatch.delenv("MAPPLS_STATIC_KEY", raising=False)
    monkeypatch.delenv("MAPPLS_REST_KEY", raising=False)
    monkeypatch.setattr(core, "DB_PATH", tmp_path / "t.sqlite3")
    core.init_db()
    monkeypatch.setattr(main, "seed_delhi_city_dataset", lambda: 0)
    monkeypatch.setattr(main, "seed_pilot_network", lambda: {})
    with TestClient(app) as client:
        config = client.get("/api/v1/config/maps").json()
        assert config["configured"] is False and "MAPPLS_STATIC_KEY" in config["message"]
        search = client.get("/api/v1/geocoding/search", params={"q": "Connaught"})
        assert search.status_code == 503 and "Mappls" in search.json()["detail"]
        place = {"display_name": "CP", "latitude": 28.63, "longitude": 77.21}
        walk = client.post("/api/v1/routes/walking", json={"origin": "CP", "destination": "IG", "origin_location": place, "destination_location": {**place, "latitude": 28.61}}).json()
        assert walk["provider_status"] == "unconfigured" and "MAPPLS_STATIC_KEY" in walk["error"]
        monkeypatch.setenv("MAPPLS_STATIC_KEY", "abc123")
        assert client.get("/api/v1/config/maps").json()["sdk_url"].endswith("access_token=abc123")
