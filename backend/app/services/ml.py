"""Backend adapter for the separate ML classifier package."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from backend.app.services.agents import classify_rules, sanitize
from ml.news_classifier import fit_evaluate, predict_with_pipeline

MODEL_PATH = Path(
    os.getenv(
        "NAVIRA_MODEL_PATH",
        str(Path(__file__).resolve().parents[2] / "models" / "news_classifier.joblib"),
    )
)


def _safe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**row, "text": sanitize(row.get("text", ""))} for row in records]


def train(records: list[dict[str, Any]], persist: bool = True) -> dict[str, Any]:
    safe_records = _safe_records(records)
    result, pipeline = fit_evaluate(safe_records)
    if result.get("status") != "trained" or not persist or pipeline is None:
        return result

    try:
        import joblib
    except ImportError:
        return {"status": "skipped", "reason": "Install ml/requirements.txt to persist the classifier."}

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, MODEL_PATH)
    from backend.app.core import connect

    with connect() as db:
        db.execute(
            "insert into model_runs(model_name,version,dataset_fingerprint,metrics,created_at,config) "
            "values(?,?,?,?,?,?)",
            (
                "tfidf_logistic_regression",
                "1",
                result["dataset_fingerprint"],
                json.dumps({
                    key: result[key]
                    for key in (
                        "precision", "recall", "f1", "confusion_matrix", "class_distribution", "split"
                    )
                }),
                result["created_at"],
                json.dumps({"seed": result["seed"], "artifact_path": str(MODEL_PATH)}),
            ),
        )
    result["artifact_path"] = str(MODEL_PATH)
    return result


def evaluate(records: list[dict[str, Any]]) -> dict[str, Any]:
    result, _ = fit_evaluate(_safe_records(records))
    return result


def predict(texts: list[str]) -> list[dict[str, Any]]:
    safe_texts = [sanitize(text) for text in texts]
    try:
        import joblib

        pipeline = joblib.load(MODEL_PATH)
    except (ImportError, FileNotFoundError, ValueError, OSError):
        return [{"mode": "rules_only", **classify_rules(text)} for text in safe_texts]
    return predict_with_pipeline(pipeline, safe_texts)
