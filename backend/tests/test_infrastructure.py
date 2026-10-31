from urllib.parse import parse_qs

from fastapi.testclient import TestClient

from backend.app import core, main
from backend.app.main import app
from backend.app.services.infrastructure import InfrastructureUnavailable, RouteInfrastructure


ROUTE = [[77.2000, 28.6000], [77.2010, 28.6000]]


def test_osm_route_corridor_counts_mapped_features_without_claiming_they_work():
    captured = {}

    def fetcher(endpoint, body):
        captured["query"] = parse_qs(body.decode())["data"][0]
        return {"elements": [
            {"type": "node", "id": 100, "lat": 28.6001, "lon": 77.2003, "tags": {"highway": "street_lamp"}},
            {"type": "node", "id": 101, "lat": 28.6020, "lon": 77.2003, "tags": {"highway": "street_lamp"}},
            {"type": "way", "id": 200, "center": {"lat": 28.6001, "lon": 77.2005}, "geometry": [{"lat": 28.6001, "lon": 77.2004}, {"lat": 28.6001, "lon": 77.2006}], "tags": {"highway": "footway", "lit": "yes"}},
            {"type": "way", "id": 201, "center": {"lat": 28.6001, "lon": 77.2007}, "geometry": [{"lat": 28.6001, "lon": 77.2006}, {"lat": 28.6001, "lon": 77.2008}], "tags": {"highway": "path", "lit": "no"}},
        ]}

    result = RouteInfrastructure(fetcher=fetcher, endpoints=("https://overpass.example/api",)).search(ROUTE, 100)

    assert 'highway="street_lamp"' in captured["query"]
    assert "footway|path|pedestrian|steps" in captured["query"]
    assert captured["query"].count("(around:100,") == 2
    assert result["streetlights_mapped"] == 1
    assert result["footpaths_mapped"] == 2
    assert result["mapped_feature_count"] == 3
    assert result["working_status"] == "unverified"
    assert result["night_visibility"] == "not_assessed"
    assert result["lighting_tags_on_paths"]["lit_tagged"] == 1
    assert result["lighting_tags_on_paths"]["unlit_tagged"] == 1
    assert all(source["status"] == "unavailable" for source in result["official_sources"])
    assert result["retrieved_at"] and result["coverage"]["route_points_sampled"] >= 2


def test_osm_route_corridor_zero_features_is_mapped_empty_not_unavailable():
    result = RouteInfrastructure(fetcher=lambda *_: {"elements": []}, endpoints=("https://overpass.example/api",)).search(ROUTE)
    assert result["status"] == "available"
    assert result["streetlights_mapped"] == 0
    assert result["footpaths_mapped"] == 0
    assert "Map completeness and field condition are unknown" in result["coverage"]["note"]


def test_osm_provider_failure_remains_unavailable():
    def fail(*_):
        raise InfrastructureUnavailable("provider is down")

    try:
        RouteInfrastructure(fetcher=fail, endpoints=("https://overpass.example/api",)).search(ROUTE)
        assert False, "Expected an explicit provider failure"
    except InfrastructureUnavailable as error:
        assert "provider is down" in str(error)


def test_route_infrastructure_endpoint_uses_validated_route_coordinates(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "DB_PATH", tmp_path / "infrastructure.sqlite3")
    core.init_db()
    expected = {"status": "available", "streetlights_mapped": 3, "footpaths_mapped": 2}
    monkeypatch.setattr(main, "get_route_infrastructure", lambda coordinates, corridor: {**expected, "coordinates": coordinates, "corridor_m": corridor})

    with TestClient(app) as client:
        response = client.post("/api/v1/routes/infrastructure", json={"coordinates": ROUTE, "corridor_m": 150})
        assert response.status_code == 200
        assert response.json()["coordinates"] == ROUTE
        assert response.json()["corridor_m"] == 150
        assert client.post("/api/v1/routes/infrastructure", json={"coordinates": [[181, 28], [77, 29]]}).status_code == 422
        assert client.post("/api/v1/routes/infrastructure", json={"coordinates": ROUTE, "corridor_m": 501}).status_code == 422


def test_route_infrastructure_endpoint_reports_provider_failure_as_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "DB_PATH", tmp_path / "infrastructure-unavailable.sqlite3")
    core.init_db()
    monkeypatch.setattr(main, "get_route_infrastructure", lambda *_: (_ for _ in ()).throw(InfrastructureUnavailable("Overpass is down")))

    with TestClient(app) as client:
        response = client.post("/api/v1/routes/infrastructure", json={"coordinates": ROUTE})
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["streetlights_mapped"] is None
    assert response.json()["footpaths_mapped"] is None
    assert response.json()["working_status"] == "unavailable"
