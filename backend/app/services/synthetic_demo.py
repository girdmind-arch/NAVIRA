"""Read-only loader for fictional interface demonstration data.

The fixture is deliberately separate from SQLite, incident imports, safety
assessments, model training, and model evaluation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FIXTURE_PATH = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "navira_synthetic_route_demo.json"


def load_synthetic_route_demo() -> dict[str, Any]:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    metadata = data.get("metadata") or {}
    if metadata.get("record_type") != "synthetic_demo_only" or metadata.get("real_source_data_used") is not False:
        raise ValueError("Synthetic demo fixture is missing required provenance.")
    for example in data.get("synthetic_crime_rate_examples", []):
        provenance = example.get("provenance") or {}
        if provenance.get("synthetic") is not True or provenance.get("real_source_data_used") is not False:
            raise ValueError("Synthetic crime-rate example is missing required provenance.")
        if example.get("fictional_population", 0) <= 0:
            raise ValueError("Synthetic crime-rate examples need a positive fictional denominator.")
        expected_rate = round(example.get("example_reports", 0) * 10_000 / example["fictional_population"], 2)
        if example.get("example_rate_per_10000_fictional_residents") != expected_rate:
            raise ValueError("Synthetic example rate does not match its fictional count and denominator.")
    for route in data.get("route_options", []):
        if route.get("safety_score") is not None:
            raise ValueError("Synthetic route fixtures cannot contain numeric safety scores.")
    return data
