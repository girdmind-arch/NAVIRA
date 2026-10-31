"""FastAPI endpoints for news triage and the NAVIRA ML workflows."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.core import connect
from backend.app.services.agents import extract_candidate, find_duplicate_candidates
from backend.app.services.ml import evaluate, predict, train

router = APIRouter(tags=["ML and news triage"])


class TextBatch(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=100)


class LabeledNewsRecord(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    label: int = Field(ge=0, le=1, description="Explicit human label: 1 relevant, 0 not relevant")
    source_group: str | None = Field(default=None, max_length=200)


class ModelRecords(BaseModel):
    records: list[LabeledNewsRecord] = Field(min_length=1, max_length=5000)


class DuplicateReview(BaseModel):
    decision: str = Field(pattern="^(confirmed_duplicate|not_duplicate|needs_review)$")


@router.post("/api/v1/news/extract")
def extract_news(body: TextBatch):
    with connect() as db:
        items = [extract_candidate(text, db) for text in body.texts]
    return {
        "items": items,
        "notice": "Dates and localities are candidates requiring human review; publication date is not used as incident date.",
    }


@router.post("/api/v1/news/classify")
def classify_news(body: TextBatch):
    return {
        "items": predict(body.texts),
        "notice": "Every candidate requires human review; model confidence is not verification.",
    }


@router.post("/api/v1/models/evaluate")
def evaluate_news_model(body: ModelRecords):
    result = evaluate([record.model_dump() for record in body.records])
    return {
        **result,
        "persisted": False,
        "notice": "Evaluation fits an in-memory candidate model; it does not replace the saved model.",
    }


@router.post("/api/v1/models/train")
def train_news_model(body: ModelRecords):
    result = train([record.model_dump() for record in body.records], persist=True)
    artifact_saved = bool(result.pop("artifact_path", None))
    return {
        **result,
        "persisted": artifact_saved,
        "notice": "Training requires explicit human labels. Predictions remain candidates for human review.",
    }


@router.get("/api/v1/models/runs")
def model_runs(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    with connect() as db:
        items = [dict(row) for row in db.execute(
            "select * from model_runs order by id desc limit ? offset ?", (limit, offset)
        )]
    return {"items": items, "limit": limit, "offset": offset}


@router.post("/api/v1/review/duplicates/detect")
def detect_duplicates(threshold: float = Query(0.8, ge=0, le=1)):
    with connect() as db:
        candidate_ids = find_duplicate_candidates(db, threshold)
    return {
        "created": len(candidate_ids),
        "candidate_ids": candidate_ids,
        "threshold": threshold,
        "notice": "Similarity identifies review candidates only; records are never merged automatically.",
    }


@router.get("/api/v1/review/duplicates")
def duplicate_queue(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    with connect() as db:
        items = [dict(row) for row in db.execute(
            "select * from duplicate_candidates where status='needs_review' "
            "order by score desc limit ? offset ?", (limit, offset)
        )]
    return {"items": items, "limit": limit, "offset": offset}


@router.post("/api/v1/review/duplicates/{candidate_id}")
def review_duplicate(candidate_id: int, body: DuplicateReview):
    status = "reviewed" if body.decision != "needs_review" else "needs_review"
    with connect() as db:
        cursor = db.execute(
            "update duplicate_candidates set status=?,reviewer_decision=? where id=?",
            (status, body.decision, candidate_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Duplicate candidate not found")
    return {
        "candidate_id": candidate_id,
        "status": status,
        "reviewer_decision": body.decision,
        "records_merged": False,
    }
