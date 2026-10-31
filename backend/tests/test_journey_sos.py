from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app import core, main
from backend.app.main import app
from backend.app.routers import journey_sos

ROUTE = {"id": "osrm-test", "distance_m": 4200, "duration_s": 900, "geometry": {"coordinates": [[77.2, 28.6], [77.3, 28.7]]}}
EXPECTED_PREFIX = "SOS EMERGENCY! I am in danger and need immediate help. My current location is: "


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NAVIRA_SOS_WATCHDOG", "0")
    for key in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "NAVIRA_PUBLIC_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(core, "DB_PATH", tmp_path / "test.sqlite3")
    core.init_db()
    monkeypatch.setattr(main, "seed_delhi_city_dataset", lambda: 0)
    monkeypatch.setattr(main, "seed_pilot_network", lambda: {})
    with TestClient(app) as test_client:
        assert test_client.post("/api/auth/register", json={"email": "u@example.com", "password": "strong-password", "name": "U"}).status_code == 201
        assert test_client.post("/api/contacts", json={"name": "Mum", "phone": "+91 98765 43210"}).status_code == 201
        yield test_client


def start_journey(client):
    journey_id = client.post("/api/journeys/plan", json={"origin": "A", "destination": "B", "route_id": "osrm-test", "route": ROUTE}).json()["id"]
    assert client.post(f"/api/journeys/{journey_id}/start").status_code == 200
    return journey_id


def beat(client, journey_id, **body):
    response = client.post(f"/api/journeys/{journey_id}/safety/heartbeat", json={"app_origin": "https://navira.test", **body})
    assert response.status_code == 200
    return response.json()


def test_help_request_sends_exact_message_with_live_link_and_reports_missing_integrations(client):
    journey_id = start_journey(client)
    beat(client, journey_id, latitude=28.61, longitude=77.21, accuracy_m=12)
    response = client.post(f"/api/journeys/{journey_id}/safety/sos", json={"reason": "user_requested_help"})
    assert response.status_code == 201
    sos = response.json()
    assert sos["live_link"].startswith("https://navira.test/#/live/")
    assert sos["message"] == f"{EXPECTED_PREFIX}{sos['live_link']}. Please help me immediately!"
    contact = sos["notifications"]["contacts"][0]
    assert contact["name"] == "Mum" and contact["status"] == "not_configured"
    assert sos["contacts_notified"] == 0
    assert sos["notifications"]["police"]["status"] == "unavailable"


def test_duplicate_sos_is_deduplicated_and_resolve_allows_a_new_one(client):
    journey_id = start_journey(client)
    first = client.post(f"/api/journeys/{journey_id}/safety/sos", json={"reason": "no_response_to_safety_checks"}).json()
    second = client.post(f"/api/journeys/{journey_id}/safety/sos", json={"reason": "user_requested_help"}).json()
    assert second["deduplicated"] is True and second["id"] == first["id"]
    assert client.post(f"/api/journeys/{journey_id}/safety/sos/resolve").status_code == 200
    third = client.post(f"/api/journeys/{journey_id}/safety/sos", json={"reason": "user_requested_help"}).json()
    assert third["deduplicated"] is False and third["id"] != first["id"]


def test_live_link_follows_movement(client):
    journey_id = start_journey(client)
    beat(client, journey_id, latitude=28.61, longitude=77.21, accuracy_m=10)
    token = client.post(f"/api/journeys/{journey_id}/safety/sos", json={"reason": "user_requested_help"}).json()["live_link"].rsplit("/", 1)[1]
    assert client.get(f"/api/v1/journey-sos/live/{token}").json()["latitude"] == 28.61
    beat(client, journey_id, latitude=28.62, longitude=77.22, accuracy_m=10)
    live = client.get(f"/api/v1/journey-sos/live/{token}").json()
    assert (live["latitude"], live["longitude"], live["connection"]) == (28.62, 77.22, "live")
    beat(client, journey_id)  # heartbeat without GPS keeps the last known fix
    assert client.get(f"/api/v1/journey-sos/live/{token}").json()["latitude"] == 28.62
    assert client.get("/api/v1/journey-sos/live/" + "0" * 64).status_code == 404


def test_missed_heartbeats_trigger_one_sos_with_last_known_location_and_no_switched_off_claim(client):
    journey_id = start_journey(client)
    fix_time = datetime.now(timezone.utc) - timedelta(seconds=5)
    beat(client, journey_id, latitude=28.6139, longitude=77.209, accuracy_m=15, location_at=fix_time.isoformat())
    assert journey_sos.sweep_missed_heartbeats() == []  # still within the allowed window
    later = datetime.now(timezone.utc) + timedelta(minutes=10)
    created = journey_sos.sweep_missed_heartbeats(now=later)
    assert len(created) == 1
    assert journey_sos.sweep_missed_heartbeats(now=later + timedelta(minutes=1)) == []  # no duplicates
    sos = client.get(f"/api/journeys/{journey_id}/safety").json()["active_sos"]
    assert sos["reason"] == "connectivity_lost"
    assert sos["message"].startswith(EXPECTED_PREFIX)
    assert "28.613900,77.209000" in sos["message"] and "IST" in sos["message"]
    assert "switched off" not in sos["message"].lower() and "lost connection" in sos["message"]


def test_monitoring_stops_when_journey_ends(client):
    journey_id = start_journey(client)
    beat(client, journey_id, latitude=28.61, longitude=77.21)
    assert client.post(f"/api/journeys/{journey_id}/complete").status_code == 200
    assert beat(client, journey_id)["monitoring"] is False
    assert journey_sos.sweep_missed_heartbeats(now=datetime.now(timezone.utc) + timedelta(hours=1)) == []
    assert client.post(f"/api/journeys/{journey_id}/safety/sos", json={"reason": "user_requested_help"}).status_code == 409


def test_journeys_without_heartbeats_are_not_flagged(client):
    start_journey(client)
    assert journey_sos.sweep_missed_heartbeats(now=datetime.now(timezone.utc) + timedelta(hours=1)) == []


def test_provider_acceptance_is_reported_only_when_configured(client, monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "t")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+10000000000")
    sent = []
    monkeypatch.setattr(journey_sos, "_send_sms", lambda cfg, to, body: sent.append((to, body)) or {"status": "accepted_by_provider", "provider": "twilio"})
    journey_id = start_journey(client)
    sos = client.post(f"/api/journeys/{journey_id}/safety/sos", json={"reason": "user_requested_help"}).json()
    assert sos["contacts_notified"] == 1 and sent[0][1] == sos["message"]


def test_other_users_cannot_access_journey_safety(client):
    journey_id = start_journey(client)
    client.post("/api/auth/logout")
    assert client.post(f"/api/journeys/{journey_id}/safety/heartbeat", json={}).status_code == 401
    client.post("/api/auth/register", json={"email": "x@example.com", "password": "strong-password", "name": "X"})
    assert client.post(f"/api/journeys/{journey_id}/safety/sos", json={"reason": "user_requested_help"}).status_code == 404
