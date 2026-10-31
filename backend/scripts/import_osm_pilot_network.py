"""Import the checked local OSM pilot GeoJSON into NAVIRA's SQLite database."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.app.core import connect, init_db


DEFAULT_DATA = Path(__file__).resolve().parents[1] / "data" / "osm" / "delhi_pilot_walkable.geojson"


def import_network(path: Path = DEFAULT_DATA, *, dry_run: bool = False) -> dict:
    collection = json.loads(path.read_text(encoding="utf-8"))
    meta = collection.get("metadata", {})
    if meta.get("license") != "Open Database License (ODbL) 1.0" or not meta.get("attribution"):
        raise ValueError("OSM license and attribution metadata are required")
    features = collection.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("GeoJSON must contain pedestrian-tagged features")
    ids = [str(f.get("properties", {}).get("osm_way_id", "")) for f in features]
    if any(not value for value in ids):
        raise ValueError("Each feature must have an OSM way id")
    if dry_run:
        return {"features_seen": len(features), "features_imported": 0, "dry_run": True}

    now = datetime.now(timezone.utc).isoformat()
    ref = meta.get("source_url", "https://api.openstreetmap.org/api/0.6/map")
    with connect() as db:
        source = db.execute("select id from sources where name=? and reference=?", ("OpenStreetMap contributors", ref)).fetchone()
        if source:
            source_id = source["id"]
        else:
            source_id = db.execute(
                "insert into sources(source_type,name,reference,permission_basis,retrieved_at,version,geographic_precision,notes) values('map',?,?,?,?,?,?,?)",
                ("OpenStreetMap contributors", ref, "Open Data Commons Open Database License (ODbL) 1.0; attribution and share-alike obligations apply", meta.get("retrieved_at", now), str(meta.get("osm_base_versions") or "OSM API response date/version not exposed"), "six bounded locality pilot windows", "OSM highway tags indicate candidate walkable ways, not field-verified pedestrian access or safety; pilot windows are incomplete."),
            ).lastrowid
        network = db.execute("select id from pedestrian_networks where source_id=? and version_date=?", (source_id, "2026-10-29")).fetchone()
        if network:
            network_id = network["id"]
        else:
            network_id = db.execute(
                "insert into pedestrian_networks(source_id,version_date,license,attribution,source_url,notes) values(?,?,?,?,?,?)",
                (source_id, "2026-10-29", meta["license"], meta["attribution"], ref, meta.get("scope", "")),
            ).lastrowid
        imported = 0
        for feature in features:
            props = feature["properties"]
            way_id = str(props["osm_way_id"])
            geometry = feature.get("geometry")
            if geometry is None or geometry.get("type") != "LineString" or len(geometry.get("coordinates", [])) < 2:
                raise ValueError(f"way {way_id} has invalid line geometry")
            segment_id = f"osm-network-{network_id}-way-{way_id}"
            cursor = db.execute(
                "insert or ignore into pedestrian_segments(id,network_id,osm_way_id,geometry_geojson,walkable_status,segment_length_m) values(?,?,?,?,?,?)",
                (segment_id, network_id, way_id, json.dumps(feature, separators=(",", ":")), props.get("walkable_status", "OSM tag candidate; unverified"), None),
            )
            imported += cursor.rowcount
        db.execute(
            "insert into route_safety_import_runs(source_id,source_version,started_at,finished_at,status,records_seen,records_imported,records_skipped,notes) values(?,?,?,?,?,?,?,?,?)",
            (source_id, str(meta.get("osm_base_versions") or "response snapshot date not provided"), now, datetime.now(timezone.utc).isoformat(), "complete", len(features), imported, len(features)-imported, "OSM pilot map import; no incident snapping performed."),
        )
    return {"features_seen": len(features), "features_imported": imported, "features_skipped": len(features)-imported, "network_id": network_id, "source_id": source_id, "dry_run": False}


def seed_pilot_network() -> dict:
    collection = json.loads(DEFAULT_DATA.read_text(encoding="utf-8"))
    complete = False
    expected_count = len(collection["features"])
    with connect() as db:
        network = db.execute("select id from pedestrian_networks where version_date=? order by id limit 1", ("2026-10-29",)).fetchone()
        if network:
            expected = {f"osm-network-{network['id']}-way-{f['properties']['osm_way_id']}" for f in collection["features"]}
            present = {r[0] for r in db.execute("select id from pedestrian_segments")}
            complete = expected <= present
    if complete:
        return {"features_seen": expected_count, "features_imported": 0, "features_skipped": expected_count, "seeded": True}
    return {**import_network(DEFAULT_DATA), "seeded": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    init_db()
    print(json.dumps(import_network(args.file, dry_run=args.dry_run), indent=2))


if __name__ == "__main__":
    main()
