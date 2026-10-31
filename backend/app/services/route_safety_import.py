"""Local, repeatable importer for reviewed route-safety JSON records.

No network access or geocoding occurs here. Keep source references and short,
redacted evidence spans; sensitive records may only retain coarse place text.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from backend.app.services.agents import sanitize
from backend.app.core import connect


def _required(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def validate_dataset(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    source = dataset.get("source") or {}
    for field in ("name", "reference", "permission_basis", "geographic_precision"):
        _required(source.get(field), f"source.{field}")
    records = dataset.get("records")
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"records[{index}] must be an object")
        rid = _required(record.get("id"), f"records[{index}].id")
        if rid in seen:
            raise ValueError(f"duplicate record id: {rid}")
        seen.add(rid)
        if not isinstance(record.get("sources"), list) or not record["sources"]:
            raise ValueError(f"records[{index}].sources must contain a source link")
        for source_link in record["sources"]:
            url = _required(source_link.get("canonical_url"), "source canonical_url")
            if urlparse(url).scheme not in {"http", "https"} or not urlparse(url).netloc:
                raise ValueError(f"invalid canonical URL: {url}")
        for place in record.get("places", []):
            if place.get("sensitivity_flag") and (place.get("latitude") is not None or place.get("longitude") is not None):
                raise ValueError("sensitive locations cannot include coordinates; generalize to coarse locality")
            lat, lon = place.get("latitude"), place.get("longitude")
            if (lat is None) != (lon is None):
                raise ValueError("place latitude and longitude must be supplied together")
            if lat is not None and (not -90 <= float(lat) <= 90 or not -180 <= float(lon) <= 180):
                raise ValueError("place coordinates are outside valid ranges")
    return records


def import_dataset(db, dataset: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    records = validate_dataset(dataset)
    source = dataset["source"]
    if dry_run:
        return {"records_seen": len(records), "records_imported": 0, "records_skipped": 0, "dry_run": True}
    now = datetime.now(timezone.utc).isoformat()
    with db:
        existing = db.execute("select id from sources where name=? and reference=?", (source["name"], source["reference"])).fetchone()
        if existing:
            source_id = existing["id"]
        else:
            source_id = db.execute(
                "insert into sources(source_type,name,reference,permission_basis,retrieved_at,version,geographic_precision,notes) values('news',?,?,?,?,?,?,?)",
                (source["name"], source["reference"], source["permission_basis"], source.get("retrieved_at", now), source.get("version"), source["geographic_precision"], source.get("notes")),
            ).lastrowid
        run_id = db.execute(
            "insert into route_safety_import_runs(source_id,source_version,started_at,status,records_seen) values(?,?,?,'running',?)",
            (source_id, source.get("version"), now, len(records)),
        ).lastrowid
        coverage = dataset.get("coverage") or {}
        requested_years = sorted({int(year) for year in coverage.get("requested_years", [])})
        declared_processed = sorted({int(year) for year in coverage.get("processed_years", [])})
        declared_missing = sorted({int(year) for year in coverage.get("missing_years", [])})
        db.execute(
            "insert into news_source_coverage(source_id,requested_years,processed_years,missing_years,gap_reasons,checkpoint,last_checked_at,coverage_note) values(?,?,?,?,?,?,?,?) "
            "on conflict(source_id) do update set requested_years=excluded.requested_years,processed_years=excluded.processed_years,missing_years=excluded.missing_years,gap_reasons=excluded.gap_reasons,coverage_note=excluded.coverage_note,last_checked_at=excluded.last_checked_at",
            (source_id, json.dumps(requested_years), json.dumps(declared_processed), json.dumps(declared_missing), json.dumps(coverage.get("gap_reasons", {})), None, now, coverage.get("note")),
        )
        db.commit()
        imported = skipped = 0
        for record in records:
            rid = record["id"].strip()
            if db.execute("select 1 from incident_events where id=?", (rid,)).fetchone():
                # A rerun or a follow-up import may add another publisher URL
                # to the same event. Keep that provenance without a new event.
                for link in record["sources"]:
                    db.execute(
                        "insert or ignore into incident_sources(incident_id,source_id,canonical_url,headline,published_at,updated_at,accessed_at,source_kind,primary_or_secondary,quoted_location_text,quoted_date_text,evidence_location,corroboration_group_id,source_quality_notes) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (rid, source_id, link["canonical_url"], sanitize(link.get("headline", "")), link.get("published_at"), link.get("updated_at"), link.get("accessed_at", now), link.get("source_kind", "news"), link.get("primary_or_secondary"), sanitize(link.get("quoted_location_text", "")), sanitize(link.get("quoted_date_text", "")), sanitize(link.get("evidence_location", "")), link.get("corroboration_group_id"), sanitize(link.get("source_quality_notes", ""))),
                    )
                skipped += 1
                db.execute("update news_source_coverage set checkpoint=?,last_checked_at=? where source_id=?", (rid, datetime.now(timezone.utc).isoformat(), source_id))
                db.commit()
                continue
            db.execute(
                "insert into incident_events(id,event_date_start,event_date_end,date_precision,incident_type_raw,incident_type_normalized,event_status,status_as_of,summary_neutral,public_space_relevance,sensitivity_flag,created_at,record_version) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, record.get("event_date_start"), record.get("event_date_end"), record.get("date_precision", "unknown"), sanitize(record.get("incident_type_raw", "")), sanitize(record.get("incident_type_normalized", "")), record.get("event_status", "reported"), record.get("status_as_of"), sanitize(record.get("summary_neutral", "")), record.get("public_space_relevance", "unknown"), int(bool(record.get("sensitivity_flag"))), now, str(record.get("record_version", "1"))),
            )
            for link in record["sources"]:
                db.execute(
                    "insert or ignore into incident_sources(incident_id,source_id,canonical_url,headline,published_at,updated_at,accessed_at,source_kind,primary_or_secondary,quoted_location_text,quoted_date_text,evidence_location,corroboration_group_id,source_quality_notes) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, source_id, link["canonical_url"], sanitize(link.get("headline", "")), link.get("published_at"), link.get("updated_at"), link.get("accessed_at", now), link.get("source_kind", "news"), link.get("primary_or_secondary"), sanitize(link.get("quoted_location_text", "")), sanitize(link.get("quoted_date_text", "")), sanitize(link.get("evidence_location", "")), link.get("corroboration_group_id"), sanitize(link.get("source_quality_notes", ""))),
                )
            for index, place in enumerate(record.get("places", [])):
                place_id = hashlib.sha256(f"{rid}:{index}".encode()).hexdigest()[:32]
                db.execute(
                    "insert into place_observations(id,incident_id,place_role,place_text_verbatim,normalized_place,locality,landmark,latitude,longitude,coordinate_crs,uncertainty_radius_m,geocode_method,geocoder_and_version,location_confidence,privacy_generalization_level,review_status) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (place_id, rid, place.get("place_role", "other"), sanitize(place.get("place_text_verbatim", "")), sanitize(place.get("normalized_place", "")), sanitize(place.get("locality", "")), sanitize(place.get("landmark", "")), place.get("latitude"), place.get("longitude"), place.get("coordinate_crs"), place.get("uncertainty_radius_m"), place.get("geocode_method"), place.get("geocoder_and_version"), place.get("location_confidence", "unresolved"), place.get("privacy_generalization_level", "coarse"), place.get("review_status", "needs_review")),
                )
            imported += 1
            db.execute("update news_source_coverage set checkpoint=?,last_checked_at=? where source_id=?", (rid, datetime.now(timezone.utc).isoformat(), source_id))
            db.commit()
        # The checkpoint is the last stable event id. Re-running the same batch
        # is safe: event ids and source URLs are unique and existing records skip.
        years = sorted({int((r.get("event_date_start") or "")[:4]) for r in records if (r.get("event_date_start") or "")[:4].isdigit()})
        if not declared_processed:
            declared_processed = years
        db.execute("update news_source_coverage set processed_years=?,record_count=(select count(distinct incident_id) from incident_sources where source_id=?) where source_id=?", (json.dumps(declared_processed), source_id, source_id))
        db.execute("update route_safety_import_runs set finished_at=?,status='complete',records_imported=?,records_skipped=? where id=?", (datetime.now(timezone.utc).isoformat(), imported, skipped, run_id))
    return {"records_seen": len(records), "records_imported": imported, "records_skipped": skipped, "source_id": source_id, "import_run_id": run_id, "dry_run": False}
