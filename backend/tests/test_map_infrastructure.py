from urllib.parse import parse_qs

from fastapi.testclient import TestClient

from backend.app import core, main
from backend.app.main import app
from backend.app.services.map_infrastructure import MapInfrastructureUnavailable, ViewportInfrastructure


BBOX = (77.20, 28.60, 77.22, 28.62)


def test_visible_area_query_returns_geojson_layers_and_non_verified_tags():
    captured = {}

    def fetcher(endpoint, body):
        captured["endpoint"] = endpoint
        captured["query"] = parse_qs(body.decode())["data"][0]
        return {"osm3s": {"timestamp_osm_base": "2026-10-30T00:00:00Z"}, "elements": [
            {"type": "way", "id": 1, "geometry": [{"lat": 28.61, "lon": 77.201}, {"lat": 28.611, "lon": 77.202}],
             "tags": {"highway": "primary", "name": "Test Road", "surface": "asphalt", "lit": "yes", "sidewalk": "no"}},
            {"type": "way", "id": 2, "geometry": [{"lat": 28.612, "lon": 77.203}, {"lat": 28.613, "lon": 77.204}],
             "tags": {"highway": "footway", "sidewalk": "both"}},
            {"type": "node", "id": 3, "lat": 28.614, "lon": 77.205, "tags": {"highway": "street_lamp", "lit": "yes"}},
        ]}

    result = ViewportInfrastructure(fetcher=fetcher, endpoints=("https://overpass.example/api",)).search(BBOX, use_cache=False)
    assert "way[\"highway\"](28.6,77.2,28.62,77.22)" in captured["query"]
    assert "node[\"highway\"=\"street_lamp\"]" in captured["query"]
    assert result["type"] == "FeatureCollection"
    assert result["counts"] == {"roads": 1, "pedestrian": 1, "lighting": 1, "surface": 1}
    road = next(feature for feature in result["features"] if feature["id"] == "way/1")
    assert road["geometry"]["type"] == "LineString"
    assert road["properties"]["layers"] == ["roads", "surface"]
    assert road["properties"]["sidewalk_status"] == "explicitly_absent"
    lamp = next(feature for feature in result["features"] if feature["id"] == "node/3")
    assert lamp["properties"]["working_status"] == "not_verified"
    assert result["coverage_status"] == "mapped"


def test_no_matching_features_are_not_mapped_not_provider_failure():
    result = ViewportInfrastructure(fetcher=lambda *_: {"elements": []}, endpoints=("https://overpass.example/api",)).search(BBOX, use_cache=False)
    assert result["status"] == "available"
    assert result["coverage_status"] == "not_mapped"
    assert result["counts"] == {"roads": 0, "pedestrian": 0, "lighting": 0, "surface": 0}
    assert "not absent in the real world" in result["note"]


def test_provider_failure_is_unavailable():
    def fail(*_):
        raise MapInfrastructureUnavailable("provider timed out")

    try:
        ViewportInfrastructure(fetcher=fail, endpoints=("https://overpass.example/api",)).search(BBOX, use_cache=False)
        assert False, "Expected an unavailable provider result"
    except MapInfrastructureUnavailable as error:
        assert "timed out" in str(error)


def test_viewport_api_validates_bbox_and_returns_geojson(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "DB_PATH", tmp_path / "map-infrastructure.sqlite3")
    core.init_db()
    monkeypatch.setattr(main, "get_viewport_infrastructure", lambda bounds: {
        "type": "FeatureCollection", "features": [], "counts": {"roads": 0}, "status": "available", "bbox": list(bounds),
    })
    with TestClient(app) as client:
        response = client.get("/api/v1/map/infrastructure", params={"bbox": "77.2,28.6,77.22,28.62"})
        assert response.status_code == 200
        assert response.json()["bbox"] == list(BBOX)
        assert client.get("/api/v1/map/infrastructure", params={"bbox": "77.2,28.6,77.3,28.62"}).status_code == 422
        assert client.get("/api/v1/map/infrastructure", params={"bbox": "invalid"}).status_code == 422


def test_viewport_api_retains_unavailable_status(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "DB_PATH", tmp_path / "map-infrastructure-unavailable.sqlite3")
    core.init_db()
    monkeypatch.setattr(main, "get_viewport_infrastructure", lambda *_: (_ for _ in ()).throw(MapInfrastructureUnavailable("Overpass timed out")))
    with TestClient(app) as client:
        response = client.get("/api/v1/map/infrastructure", params={"bbox": "77.2,28.6,77.22,28.62"})
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["counts"]["roads"] is None
    assert "does not mean" in response.json()["note"]
