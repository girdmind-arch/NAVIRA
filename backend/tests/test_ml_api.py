import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.app import core
from backend.app.services.agents import OSRMRouter
from backend.app.main import (
    GazetteerIn,
    HazardIn,
    RouteIn,
    NewsIn,
    add_hazard,
    data_status,
    emergency_resources,
    health,
    ingest_localities,
    ingest_news,
    list_hazards,
    localities,
    locality_summary,
    ncrb_delhi_city_women_crimes,
    quality_endpoint,
    routes,
    trends_endpoint,
)
from backend.app.routers import ml as ml_api
from backend.app.services import ml


def configure_test_app(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "DB_PATH", tmp_path / "api-test.sqlite3")
    monkeypatch.setattr(ml, "MODEL_PATH", tmp_path / "models" / "news-classifier.joblib")
    core.init_db()
    return ml_api


def labeled_records():
    relevant = [
        "Police reported a harassment incident in a public area.",
        "An assault case was reported and is under investigation.",
        "A woman reported stalking near a market this week.",
        "A harassment complaint was filed with local authorities.",
        "The report describes an assault against a woman.",
        "Police investigated a stalking complaint after a report.",
    ]
    unrelated = [
        "The city announced a new public library opening.",
        "A cricket match ended with a close score.",
        "The weather department expects light rain tomorrow.",
        "A new metro station opened for daily commuters.",
        "The school hosted its annual science exhibition.",
        "The council approved repairs to a public park.",
    ]
    return [
        {"text": text, "label": 1, "source_group": f"relevant-{index}"}
        for index, text in enumerate(relevant)
    ] + [
        {"text": text, "label": 0, "source_group": f"unrelated-{index}"}
        for index, text in enumerate(unrelated)
    ]


def test_ml_api_extraction_classification_evaluation_and_training(monkeypatch, tmp_path):
    api = configure_test_app(monkeypatch, tmp_path)

    extracted = api.extract_news(
        api.TextBatch(texts=["A harassment report was filed on 2024-03-05 in Delhi."])
    )
    assert extracted["items"][0]["incident_date_candidate"] == "2024-03-05"

    classified = api.classify_news(
        api.TextBatch(texts=["A woman reported harassment."])
    )
    assert classified["items"][0]["mode"] == "rules_only"

    records = api.ModelRecords(records=[api.LabeledNewsRecord(**row) for row in labeled_records()])
    evaluated = api.evaluate_news_model(records)
    assert evaluated["status"] == "trained"
    assert evaluated["persisted"] is False
    assert not ml.MODEL_PATH.exists()

    trained = api.train_news_model(records)
    assert trained["status"] == "trained"
    assert trained["persisted"] is True
    assert ml.MODEL_PATH.exists()

    classified_with_model = api.classify_news(
        api.TextBatch(texts=["A woman reported harassment."])
    )
    assert classified_with_model["items"][0]["mode"] == "tfidf_logistic_regression"

    runs = api.model_runs(limit=100, offset=0)
    assert len(runs["items"]) == 1


def test_duplicate_detection_review_and_invalid_ml_payloads(monkeypatch, tmp_path):
    api = configure_test_app(monkeypatch, tmp_path)
    source = {
        "name": "Test source",
        "reference": "test:news-fixture",
        "permission_basis": "synthetic test fixture",
        "geographic_precision": "unknown",
    }
    ingested = ingest_news(
        NewsIn(
            source=source,
            records=[
                {
                    "article_reference": "test:article-1",
                    "incident_date": "2024-03-05",
                    "category": "harassment",
                    "excerpt": "A harassment report in the central market.",
                },
                {
                    "article_reference": "test:article-2",
                    "incident_date": "2024-03-05",
                    "category": "harassment",
                    "excerpt": "A harassment report in the central market.",
                },
            ],
        )
    )
    assert ingested["accepted"] == 2

    detected = api.detect_duplicates(threshold=0.8)
    assert detected["created"] == 1

    queue = api.duplicate_queue(limit=100, offset=0)
    candidate_id = queue["items"][0]["id"]

    reviewed = api.review_duplicate(
        candidate_id,
        api.DuplicateReview(decision="confirmed_duplicate"),
    )
    assert reviewed["records_merged"] is False

    with pytest.raises(ValidationError):
        api.LabeledNewsRecord(text="bad label", label=2)


def test_health_and_ncrb_dataset_api(monkeypatch, tmp_path):
    configure_test_app(monkeypatch, tmp_path)

    assert health()["status"] == "ok"

    dataset = ncrb_delhi_city_women_crimes(start_year=2020, end_year=2024)
    assert dataset["available_years"] == [2020, 2021, 2022, 2023, 2024]

    with pytest.raises(HTTPException) as invalid_range:
        ncrb_delhi_city_women_crimes(start_year=2024, end_year=2020)
    assert invalid_range.value.status_code == 422


def test_ml_routes_are_registered_in_fastapi():
    from backend.app.main import app

    paths = app.openapi()["paths"]
    assert "/api/v1/news/extract" in paths
    assert "/api/v1/news/classify" in paths
    assert "/api/v1/models/evaluate" in paths
    assert "/api/v1/models/train" in paths
    assert "/api/v1/models/runs" in paths
    assert "/api/v1/review/duplicates/detect" in paths
    assert "/api/v1/review/duplicates" in paths
    assert "/api/v1/review/duplicates/{candidate_id}" in paths
    assert "/health" in paths
    assert "/api/v1/datasets/ncrb/delhi-city/crimes-against-women" in paths


def test_remaining_backend_routes(monkeypatch, tmp_path):
    configure_test_app(monkeypatch, tmp_path)

    assert data_status()["scope"] == "Delhi NCT only"
    assert "coverage" in quality_endpoint()

    source = {
        "name": "Test gazetteer",
        "reference": "test:localities",
        "permission_basis": "synthetic test fixture",
        "geographic_precision": "locality",
    }
    ingested = ingest_localities(
        GazetteerIn(
            source=source,
            records=[{"id": "central", "name": "Central", "aliases": ["Central Area"]}],
        )
    )
    assert ingested["accepted"] == 1
    assert localities(limit=100, offset=0)["items"][0]["id"] == "central"
    assert locality_summary("central")["locality"]["name"] == "Central"
    assert trends_endpoint(years=None, category=None)["comparability_warning"]

    monkeypatch.setattr(
        OSRMRouter,
        "routes",
        lambda _self, _origin, _destination: [
            {"id": "test-road-1", "distance_m": 1200, "duration_s": 240, "geometry": {"type": "LineString", "coordinates": [[77.2, 28.6], [77.21, 28.61]]}},
            {"id": "test-road-2", "distance_m": 1500, "duration_s": 300, "geometry": {"type": "LineString", "coordinates": [[77.2, 28.6], [77.22, 28.62]]}},
        ],
    )
    route_result = routes(RouteIn(origin="77.2000,28.6000", destination="77.2100,28.6100"))
    assert route_result["provider_status"] == "provider_configured"
    assert len(route_result["alternatives"]) == 2

    hazard = add_hazard(
        HazardIn(category="lighting", description="A test report", approximate_geography="Central")
    )
    assert hazard["status"] == "unverified"
    assert len(list_hazards(limit=100, offset=0)["items"]) == 1
    assert emergency_resources()["country"] == "India"
