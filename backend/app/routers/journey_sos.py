"""Automatic journey SOS: heartbeats, missed-heartbeat (connectivity) detection,
SOS escalation with a live location link, and honest notification reporting.

Stationary detection and the three safety-check alerts run on the device
(see frontend/src/services/journeySafety.js). The backend owns what the device
cannot do while it is unreachable: noticing missed heartbeats during an
in-progress journey and raising SOS with the last known GPS fix.

Notifications are only reported as sent when a configured provider accepted
them. Without a provider every contact is reported as ``not_configured``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from backend.app.core import connect

log = logging.getLogger("navira.journey_sos")
router = APIRouter(tags=["Journey automatic SOS"])

SOS_MESSAGE_TEMPLATE = (
    "SOS EMERGENCY! I am in danger and need immediate help. "
    "My current location is: {link}. Please help me immediately!"
)
IST = timezone(timedelta(hours=5, minutes=30), "IST")
LIVE_LINK_HOURS = 24

SCHEMA = """
CREATE TABLE IF NOT EXISTS journey_safety_monitors(
 journey_id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,last_heartbeat_at TEXT NOT NULL,
 last_latitude REAL,last_longitude REAL,last_accuracy REAL,last_location_at TEXT,app_origin TEXT,
 FOREIGN KEY(journey_id) REFERENCES journeys(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS journey_sos_events(
 id TEXT PRIMARY KEY,journey_id INTEGER NOT NULL,user_id INTEGER NOT NULL,reason TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'active',created_at TEXT NOT NULL,resolved_at TEXT,
 live_token_hash TEXT NOT NULL UNIQUE,live_link TEXT NOT NULL,live_expires_at TEXT NOT NULL,message TEXT NOT NULL,
 notifications_json TEXT NOT NULL,
 FOREIGN KEY(journey_id) REFERENCES journeys(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS ix_journey_sos_active ON journey_sos_events(journey_id,status);
"""


def _int_env(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, default))
    except ValueError:
        return default
    return max(low, min(high, value))


def settings() -> dict:
    """Runtime configuration (env-overridable)."""
    return {
        "stationary_minutes": 5,
        "safety_check_alerts": 3,
        "safety_check_window_s": _int_env("NAVIRA_SAFETY_CHECK_WINDOW_S", 180, 30, 1800),
        "heartbeat_interval_s": _int_env("NAVIRA_HEARTBEAT_INTERVAL_S", 30, 10, 300),
        "missed_heartbeats": _int_env("NAVIRA_MISSED_HEARTBEATS", 4, 2, 20),
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_schema(db) -> None:
    db.executescript(SCHEMA)


def _account(authorization: str | None = Header(None), navira_session: str | None = Cookie(None)):
    # Lazy import: main.py includes this router, so import its auth helper at call time.
    from backend.app.main import _current_user
    return _current_user(authorization, navira_session)


def _journey(db, journey_id: int, user_id: int):
    row = db.execute("select * from journeys where id=? and user_id=?", (journey_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Journey not found")
    return row


def _active_sos(db, journey_id: int):
    return db.execute(
        "select * from journey_sos_events where journey_id=? and status='active' order by created_at desc limit 1",
        (journey_id,),
    ).fetchone()


# ---------------------------------------------------------------- notifications
def _twilio_config():
    sid, token, sender = (os.getenv(k, "").strip() for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"))
    return (sid, token, sender) if sid and token and sender else None


def _send_sms(config, to_phone: str, body: str) -> dict:
    sid, token, sender = config
    to = re.sub(r"[^\d+]", "", to_phone)
    data = urllib.parse.urlencode({"To": to, "From": sender, "Body": body}).encode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{urllib.parse.quote(sid)}/Messages.json", data=data, method="POST",
        headers={"Authorization": "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode()},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read() or b"{}")
        # Provider acceptance is not proof of delivery; report it as such.
        return {"status": "accepted_by_provider", "provider": "twilio", "provider_status": payload.get("status")}
    except Exception as error:  # network errors, HTTP 4xx/5xx
        log.warning("SOS SMS to a trusted contact failed: %s", error)
        return {"status": "failed", "provider": "twilio", "error": "The SMS provider did not accept the message."}


def notify_contacts(contacts: list[dict], message: str) -> list[dict]:
    config = _twilio_config()
    results = []
    for contact in contacts:
        base = {"contact_id": contact["id"], "name": contact["name"], "phone": contact["phone"]}
        if config is None:
            results.append({**base, "status": "not_configured",
                            "detail": "No SMS provider is configured on the server, so NAVIRA did not send this message."})
        else:
            results.append({**base, **_send_sms(config, contact["phone"], message)})
    return results


# ---------------------------------------------------------------- SOS creation
def _format_ist(iso_value: str | None) -> str | None:
    if not iso_value:
        return None
    return datetime.fromisoformat(iso_value).astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


def _live_link(origin: str | None, token: str) -> str:
    base = os.getenv("NAVIRA_PUBLIC_BASE_URL", "").strip().rstrip("/") or (origin or "").rstrip("/")
    return f"{base}/#/live/{token}"


def build_message(link: str, *, connectivity_lost: bool, location_at: str | None, lat=None, lng=None) -> str:
    message = SOS_MESSAGE_TEMPLATE.format(link=link)
    if connectivity_lost:
        if location_at and lat is not None:
            message += (f" Last known location: {lat:.6f},{lng:.6f} recorded at {_format_ist(location_at)}."
                        " NAVIRA lost connection with my phone; it may be out of network coverage.")
        else:
            message += " NAVIRA lost connection with my phone and has no GPS fix for this journey."
    return message


def create_sos(db, journey, reason: str, *, now: datetime | None = None) -> tuple[dict, bool]:
    """Create (or return the existing active) SOS for a journey. Returns (sos, deduplicated)."""
    existing = _active_sos(db, journey["id"])
    if existing is not None:
        return _sos_dict(db, existing), True
    now = now or _now()
    monitor = db.execute("select * from journey_safety_monitors where journey_id=?", (journey["id"],)).fetchone()
    token = secrets.token_hex(32)
    link = _live_link(monitor["app_origin"] if monitor else None, token)
    message = build_message(
        link, connectivity_lost=reason == "connectivity_lost",
        location_at=monitor["last_location_at"] if monitor else None,
        lat=monitor["last_latitude"] if monitor else None, lng=monitor["last_longitude"] if monitor else None,
    )
    contacts = [dict(r) for r in db.execute(
        "select id,name,phone from trusted_contacts where user_id=? order by id", (journey["user_id"],))]
    notifications = {
        "contacts": notify_contacts(contacts, message),
        "police": {"status": "unavailable",
                   "detail": "No police-station alert integration is available, so the nearest police station was not notified."},
    }
    sos_id = str(uuid4())
    db.execute(
        "insert into journey_sos_events(id,journey_id,user_id,reason,status,created_at,live_token_hash,live_link,live_expires_at,message,notifications_json) "
        "values(?,?,?,?,'active',?,?,?,?,?,?)",
        (sos_id, journey["id"], journey["user_id"], reason, now.isoformat(),
         hashlib.sha256(token.encode()).hexdigest(), link, (now + timedelta(hours=LIVE_LINK_HOURS)).isoformat(),
         message, json.dumps(notifications)),
    )
    row = db.execute("select * from journey_sos_events where id=?", (sos_id,)).fetchone()
    return _sos_dict(db, row), False


def _sos_dict(db, row) -> dict:
    notifications = json.loads(row["notifications_json"])
    return {
        "id": row["id"], "journey_id": row["journey_id"], "reason": row["reason"], "status": row["status"],
        "created_at": row["created_at"], "resolved_at": row["resolved_at"], "message": row["message"],
        "live_link": row["live_link"],
        "notifications": notifications,
        "contacts_notified": sum(1 for c in notifications["contacts"] if c["status"] == "accepted_by_provider"),
    }


# ---------------------------------------------------------------- watchdog
def sweep_missed_heartbeats(now: datetime | None = None) -> list[str]:
    """Raise SOS for in-progress journeys whose device stopped sending heartbeats."""
    now = now or _now()
    cfg = settings()
    cutoff = (now - timedelta(seconds=cfg["heartbeat_interval_s"] * cfg["missed_heartbeats"])).isoformat()
    created = []
    with connect() as db:
        _ensure_schema(db)
        rows = db.execute(
            "select j.* from journey_safety_monitors m join journeys j on j.id=m.journey_id "
            "where j.status='in_progress' and m.last_heartbeat_at<=? "
            "and not exists(select 1 from journey_sos_events s where s.journey_id=j.id and s.status='active')",
            (cutoff,),
        ).fetchall()
        for journey in rows:
            sos, dedup = create_sos(db, journey, "connectivity_lost", now=now)
            if not dedup:
                created.append(sos["id"])
                log.warning("Missed heartbeats on journey %s; automatic SOS %s raised", journey["id"], sos["id"])
    return created


_watchdog_lock = threading.Lock()
_watchdog_started = False


def _ensure_watchdog() -> None:
    global _watchdog_started
    if os.getenv("NAVIRA_SOS_WATCHDOG", "1") == "0":
        return
    with _watchdog_lock:
        if _watchdog_started:
            return
        _watchdog_started = True

    def loop():
        while True:
            try:
                sweep_missed_heartbeats()
            except Exception:  # keep the watchdog alive
                log.exception("Missed-heartbeat sweep failed")
            time.sleep(max(5, settings()["heartbeat_interval_s"] // 2))

    threading.Thread(target=loop, name="navira-sos-watchdog", daemon=True).start()


# ---------------------------------------------------------------- API
class HeartbeatIn(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100000)
    location_at: datetime | None = None
    app_origin: str | None = Field(default=None, max_length=200)


class SosIn(BaseModel):
    reason: str = Field(pattern="^(user_requested_help|no_response_to_safety_checks)$")


def _status(db, journey) -> dict:
    sos = _active_sos(db, journey["id"])
    return {"journey_id": journey["id"], "journey_status": journey["status"], "config": settings(),
            "active_sos": _sos_dict(db, sos) if sos else None}


@router.get("/api/journeys/{journey_id}/safety")
def safety_state(journey_id: int, user=Depends(_account)):
    with connect() as db:
        _ensure_schema(db)
        return _status(db, _journey(db, journey_id, user["id"]))


@router.post("/api/journeys/{journey_id}/safety/heartbeat")
def heartbeat(journey_id: int, body: HeartbeatIn, user=Depends(_account)):
    now = _now()
    origin = body.app_origin if body.app_origin and re.fullmatch(r"https?://[A-Za-z0-9.\-:\[\]]+", body.app_origin) else None
    with connect() as db:
        _ensure_schema(db)
        journey = _journey(db, journey_id, user["id"])
        if journey["status"] != "in_progress":
            return {**_status(db, journey), "monitoring": False}
        has_fix = body.latitude is not None and body.longitude is not None
        location_at = (body.location_at or now).astimezone(timezone.utc)
        location_at = min(location_at, now).isoformat()
        db.execute(
            "insert into journey_safety_monitors(journey_id,user_id,last_heartbeat_at,last_latitude,last_longitude,last_accuracy,last_location_at,app_origin) "
            "values(?,?,?,?,?,?,?,?) on conflict(journey_id) do update set last_heartbeat_at=excluded.last_heartbeat_at,"
            "last_latitude=coalesce(excluded.last_latitude,last_latitude),last_longitude=coalesce(excluded.last_longitude,last_longitude),"
            "last_accuracy=case when excluded.last_latitude is null then last_accuracy else excluded.last_accuracy end,"
            "last_location_at=coalesce(excluded.last_location_at,last_location_at),app_origin=coalesce(excluded.app_origin,app_origin)",
            (journey_id, user["id"], now.isoformat(),
             body.latitude if has_fix else None, body.longitude if has_fix else None,
             body.accuracy_m if has_fix else None, location_at if has_fix else None, origin),
        )
        result = {**_status(db, journey), "monitoring": True}
    _ensure_watchdog()
    return result


@router.post("/api/journeys/{journey_id}/safety/sos", status_code=201)
def trigger_sos(journey_id: int, body: SosIn, user=Depends(_account)):
    with connect() as db:
        _ensure_schema(db)
        journey = _journey(db, journey_id, user["id"])
        if journey["status"] != "in_progress":
            raise HTTPException(409, "Automatic SOS is only available during an in-progress journey.")
        sos, dedup = create_sos(db, journey, body.reason)
    return {**sos, "deduplicated": dedup}


@router.post("/api/journeys/{journey_id}/safety/sos/resolve")
def resolve_sos(journey_id: int, user=Depends(_account)):
    with connect() as db:
        _ensure_schema(db)
        _journey(db, journey_id, user["id"])
        cur = db.execute("update journey_sos_events set status='resolved',resolved_at=? where journey_id=? and status='active'",
                         (_now().isoformat(), journey_id))
        if not cur.rowcount:
            raise HTTPException(404, "No active SOS for this journey.")
    return {"status": "resolved",
            "notice": "SOS marked resolved in NAVIRA. Contacts were not told automatically; let them know you are safe."}


@router.get("/api/v1/journey-sos/live/{token}")
def live_location(token: str):
    """Public view for trusted contacts: latest known location for an active SOS link."""
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise HTTPException(404, "This live location link is invalid or has expired.")
    now = _now()
    with connect() as db:
        _ensure_schema(db)
        row = db.execute(
            "select s.created_at sos_at,s.status sos_status,s.live_expires_at,j.status journey_status,m.* "
            "from journey_sos_events s join journeys j on j.id=s.journey_id "
            "left join journey_safety_monitors m on m.journey_id=s.journey_id "
            "where s.live_token_hash=? and s.live_expires_at>?",
            (hashlib.sha256(token.encode()).hexdigest(), now.isoformat()),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "This live location link is invalid or has expired.")
    cfg = settings()
    hb = row["last_heartbeat_at"]
    connected = bool(hb) and datetime.fromisoformat(hb) > now - timedelta(seconds=cfg["heartbeat_interval_s"] * cfg["missed_heartbeats"])
    return {
        "sos_created_at": row["sos_at"], "sos_status": row["sos_status"], "expires_at": row["live_expires_at"],
        "journey_status": row["journey_status"],
        "latitude": row["last_latitude"], "longitude": row["last_longitude"], "accuracy_m": row["last_accuracy"],
        "location_recorded_at": row["last_location_at"], "last_contact_at": hb,
        "connection": "live" if connected and row["journey_status"] == "in_progress" else "lost" if row["journey_status"] == "in_progress" else "journey_ended",
        "notice": ("Location updates while the phone has GPS and connectivity. If the connection is lost, this shows the "
                   "last known location and when it was recorded."),
    }
