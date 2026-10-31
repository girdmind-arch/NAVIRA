"""Private trusted contacts, expiring location shares, and SOS event receipts."""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator

from backend.app.core import connect

router = APIRouter(prefix="/api/v1/safety", tags=["Safety and sharing"])


def _owner_hash(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "This safety workspace needs its private browser key.")
    token = authorization[7:].strip()
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise HTTPException(401, "The safety workspace key is invalid.")
    owner_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    now = _now().isoformat()
    with connect() as db:
        db.execute("delete from safety_location_shares where expires_at<=? or revoked_at is not null", (now,))
        db.execute("delete from safety_sos_events where expires_at<=?", (now,))
    return owner_hash


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ContactInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=7, max_length=30)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Enter a contact name.")
        return value

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[+0-9().\-\s]{7,30}", value) or sum(ch.isdigit() for ch in value) < 7:
            raise ValueError("Enter a valid phone number with at least 7 digits.")
        return value


class LocationInput(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100000)


class ShareInput(LocationInput):
    expires_minutes: int = Field(default=60, ge=5, le=1440)


@router.get("/status")
def safety_status(owner_hash: str = Depends(_owner_hash)):
    return {"status": "ok", "service": "navira-safety"}


@router.get("/contacts")
def list_contacts(owner_hash: str = Depends(_owner_hash)):
    with connect() as db:
        rows = db.execute(
            "select id,name,phone,created_at from safety_contacts where owner_hash=? order by created_at",
            (owner_hash,),
        )
        return {"items": [dict(row) for row in rows]}


@router.post("/contacts", status_code=201)
def add_contact(body: ContactInput, owner_hash: str = Depends(_owner_hash)):
    contact_id = str(uuid4())
    created_at = _now().isoformat()
    with connect() as db:
        db.execute(
            "insert into safety_contacts(id,owner_hash,name,phone,created_at) values(?,?,?,?,?)",
            (contact_id, owner_hash, body.name, body.phone, created_at),
        )
    return {"id": contact_id, "name": body.name, "phone": body.phone, "created_at": created_at}


@router.delete("/contacts/{contact_id}", status_code=204)
def remove_contact(contact_id: str, owner_hash: str = Depends(_owner_hash)):
    with connect() as db:
        cursor = db.execute(
            "delete from safety_contacts where id=? and owner_hash=?", (contact_id, owner_hash)
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Trusted contact not found.")
    return Response(status_code=204)


@router.get("/shares")
def list_shares(owner_hash: str = Depends(_owner_hash)):
    now = _now().isoformat()
    with connect() as db:
        db.execute("delete from safety_location_shares where expires_at<=? or revoked_at is not null", (now,))
        rows = db.execute(
            "select id,created_at,expires_at from safety_location_shares "
            "where owner_hash=? and revoked_at is null and expires_at>? order by created_at desc",
            (owner_hash, now),
        )
        return {"items": [dict(row) for row in rows]}


@router.post("/shares", status_code=201)
def create_share(body: ShareInput, owner_hash: str = Depends(_owner_hash)):
    share_id = str(uuid4())
    token = secrets.token_hex(32)
    created_at = _now()
    expires_at = created_at + timedelta(minutes=body.expires_minutes)
    with connect() as db:
        db.execute("delete from safety_location_shares where expires_at<=? or revoked_at is not null", (created_at.isoformat(),))
        db.execute(
            "insert into safety_location_shares(id,owner_hash,token_hash,latitude,longitude,accuracy,created_at,expires_at) "
            "values(?,?,?,?,?,?,?,?)",
            (
                share_id, owner_hash, hashlib.sha256(token.encode("ascii")).hexdigest(),
                body.latitude, body.longitude, body.accuracy_m,
                created_at.isoformat(), expires_at.isoformat(),
            ),
        )
    return {
        "id": share_id,
        "token": token,
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "notice": "This link shares one location snapshot until it expires or you revoke it.",
    }


@router.get("/shares/public/{token}")
def view_share(token: str):
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise HTTPException(404, "This location link is invalid or has expired.")
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    with connect() as db:
        db.execute("delete from safety_location_shares where expires_at<=? or revoked_at is not null", (_now().isoformat(),))
        row = db.execute(
            "select latitude,longitude,accuracy,created_at,expires_at from safety_location_shares "
            "where token_hash=? and revoked_at is null and expires_at>?",
            (token_hash, _now().isoformat()),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "This location link is invalid or has expired.")
    return {**dict(row), "notice": "This is a one-time location snapshot, not live tracking."}


@router.delete("/shares/{share_id}", status_code=204)
def revoke_share(share_id: str, owner_hash: str = Depends(_owner_hash)):
    with connect() as db:
        cursor = db.execute(
            "delete from safety_location_shares where id=? and owner_hash=? and revoked_at is null",
            (share_id, owner_hash),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Active location share not found.")
    return Response(status_code=204)


@router.post("/sos", status_code=201)
def record_sos(owner_hash: str = Depends(_owner_hash)):
    created_at = _now()
    event_id = str(uuid4())
    expires_at = created_at + timedelta(hours=24)
    with connect() as db:
        db.execute("delete from safety_sos_events where expires_at<=?", (created_at.isoformat(),))
        db.execute(
            "insert into safety_sos_events(id,owner_hash,created_at,expires_at) values(?,?,?,?)",
            (event_id, owner_hash, created_at.isoformat(), expires_at.isoformat()),
        )
    return {
        "id": event_id,
        "recorded_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "status": "recorded",
        "notice": "NAVIRA recorded the SOS request but did not call emergency services or notify contacts.",
    }


@router.get("/sos")
def list_sos_events(
    owner_hash: str = Depends(_owner_hash),
    limit: int = Query(default=20, ge=1, le=100),
):
    now = _now().isoformat()
    with connect() as db:
        db.execute("delete from safety_sos_events where expires_at<=?", (now,))
        rows = db.execute(
            "select id,created_at,expires_at from safety_sos_events "
            "where owner_hash=? and expires_at>? order by created_at desc limit ?",
            (owner_hash, now, limit),
        )
        return {"items": [dict(row) for row in rows]}
