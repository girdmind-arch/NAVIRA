"""Standalone ML workflow for human-labelled news relevance records.

This module contains the model fitting and inference logic. Backend data access,
privacy filtering, and persistence live in ``backend.app.services.ml``.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

SEED = 17


def dataset_fingerprint(records: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        sorted(
            (
                {
                    "text": row.get("text", ""),
                    "label": str(row.get("label")),
                    "source_group": row.get("source_group"),
                }
                for row in records
            ),
            key=lambda row: (
                row["source_group"] or "",
                row["label"] or "",
                row["text"],
            ),
        ),
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fit_evaluate(records: list[dict[str, Any]]) -> tuple[dict[str, Any], Any | None]:
    labels: list[int] = []
    texts: list[str] = []
    groups: list[str] = []
    for index, row in enumerate(records):
        label = row.get("label")
        if label not in (0, 1, "0", "1", False, True):
            return {"status": "skipped", "reason": f"Record {index} lacks an explicit human label (0 or 1)."}, None
        text = row.get("text")
        if not isinstance(text, str) or not text.strip():
            return {"status": "skipped", "reason": f"Record {index} has no text."}, None
        labels.append(int(label))
        texts.append(text)
        groups.append(str(row.get("source_group") or ""))

    if len(records) < 10 or min(labels.count(0), labels.count(1)) < 2:
        return {
            "status": "skipped",
            "reason": "Need at least 10 human-labelled examples with at least two records per class.",
        }, None

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
        from sklearn.model_selection import GroupShuffleSplit, train_test_split
        from sklearn.pipeline import Pipeline
    except ImportError:
        return {"status": "skipped", "reason": "Install ml/requirements.txt to train."}, None

    split = "stratified_random_fallback"
    indices = list(range(len(records)))
    unique_groups = {group for group in groups if group}
    if len(unique_groups) >= 4:
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=SEED)
        train_indices, test_indices = next(splitter.split(texts, labels, groups))
        if (
            len({labels[index] for index in test_indices}) == 2
            and len({labels[index] for index in train_indices}) == 2
        ):
            split = "group_holdout_by_source"
        else:
            train_indices, test_indices = train_test_split(
                indices, test_size=0.25, random_state=SEED, stratify=labels
            )
    else:
        train_indices, test_indices = train_test_split(
            indices, test_size=0.25, random_state=SEED, stratify=labels
        )

    pipeline = Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1)),
            (
                "classifier",
                LogisticRegression(random_state=SEED, max_iter=1000, class_weight="balanced"),
            ),
        ]
    )
    pipeline.fit([texts[index] for index in train_indices], [labels[index] for index in train_indices])
    truth = [labels[index] for index in test_indices]
    predicted = pipeline.predict([texts[index] for index in test_indices])
    precision, recall, f1, _ = precision_recall_fscore_support(
        truth, predicted, average="binary", zero_division=0
    )
    result = {
        "status": "trained",
        "model": "tfidf_logistic_regression",
        "version": "1",
        "seed": SEED,
        "split": split,
        "train_size": len(train_indices),
        "test_size": len(test_indices),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "confusion_matrix": confusion_matrix(truth, predicted, labels=[0, 1]).tolist(),
        "class_distribution": {"0": labels.count(0), "1": labels.count(1)},
        "dataset_fingerprint": dataset_fingerprint(records),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return result, pipeline


def predict_with_pipeline(pipeline: Any, texts: list[str]) -> list[dict[str, Any]]:
    labels = pipeline.predict(texts)
    probabilities = pipeline.predict_proba(texts)
    return [
        {
            "mode": "tfidf_logistic_regression",
            "relevant": bool(label),
            "confidence": float(max(probabilities_row)),
            "review_status": "needs_review",
            "note": "Classifier confidence is not factual verification.",
        }
        for label, probabilities_row in zip(labels, probabilities)
    ]
