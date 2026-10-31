"""Seed and query the bundled NCRB Delhi City aggregate dataset."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.core import connect

DATASET_PATH = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "ncrb_delhi_city_women_crimes.json"
DATASET_TYPE = "official"
DATASET_CATEGORY = "crime_against_women_total"


def load_dataset() -> dict[str, Any]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def seed_delhi_city_dataset() -> int:
    """Insert the versioned public table once; return its source ID."""
    dataset = load_dataset()
    source = dataset["source"]
    with connect() as db:
        existing = db.execute(
            "select id from sources where source_type=? and name=? and reference=? order by id limit 1",
            (DATASET_TYPE, source["name"], source["reference"]),
        ).fetchone()
        if existing:
            source_id = existing["id"]
        else:
            cursor = db.execute(
                "insert into sources(source_type,name,reference,permission_basis,retrieved_at,version,geographic_precision,notes) "
                "values(?,?,?,?,?,?,?,?)",
                (
                    DATASET_TYPE,
                    source["name"],
                    source["reference"],
                    source["permission_basis"],
                    source["retrieved_at"],
                    source["version"],
                    source["geographic_precision"],
                    source["notes"],
                ),
            )
            source_id = cursor.lastrowid

        for row in dataset["records"]:
            present = db.execute(
                "select 1 from official_stats where source_id=? and year=? and geography_id=? and category=? limit 1",
                (source_id, row["year"], row["geography_id"], row["category"]),
            ).fetchone()
            if not present:
                db.execute(
                    "insert into official_stats(source_id,year,geography_id,geography_type,category,count,notes) "
                    "values(?,?,?,?,?,?,?)",
                    (
                        source_id,
                        row["year"],
                        row["geography_id"],
                        row["geography_type"],
                        row["category"],
                        row["count"],
                        row.get("notes"),
                    ),
                )
    return source_id


def get_delhi_city_dataset(start_year: int | None = None, end_year: int | None = None) -> dict[str, Any]:
    """Return only NCRB metropolitan Delhi City totals and their provenance."""
    source_id = seed_delhi_city_dataset()
    filters = ["source_id=?", "geography_id=?", "geography_type=?", "category=?"]
    params: list[Any] = [source_id, "Delhi City", "metropolitan", DATASET_CATEGORY]
    if start_year is not None:
        filters.append("year>=?")
        params.append(start_year)
    if end_year is not None:
        filters.append("year<=?")
        params.append(end_year)

    with connect() as db:
        rows = [
            dict(row)
            for row in db.execute(
                "select year,geography_id,geography_type,category,count,notes from official_stats where "
                + " and ".join(filters)
                + " order by year",
                params,
            )
        ]
        source = dict(db.execute("select id,name,reference,version,retrieved_at,geographic_precision,notes from sources where id=?", (source_id,)).fetchone())

    return {
        "dataset": "NCRB Crime in India — Crimes against Women, Delhi City",
        "geography": "Delhi City metropolitan entry",
        "measure": "Registered cases (incidence)",
        "unit": "cases",
        "records": rows,
        "available_years": [row["year"] for row in rows],
        "source": source,
        "limitations": [
            "Delhi City is the NCRB metropolitan-city series; it is not the all-Delhi UT/NCT total or the wider NCR.",
            "Registered cases are not a measure of total prevalence; changes can reflect reporting and recording.",
            "The 2024 report spans the transition from IPC to BNS; use care when interpreting year-to-year changes.",
        ],
    }
