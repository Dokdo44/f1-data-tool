from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import MAX_ROWS, MAX_UPLOAD_BYTES
from app.db import get_db
from app.ingest import IngestError, parse_csv
from app.models import DataPoint, Dataset
from app.schemas import (
    AnomalyReport,
    DatasetOut,
    IngestReport,
    PointOut,
    Summary,
)
from app.stats import find_anomalies, find_anomalies_rolling, summarize

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _load(db: Session, dataset_id: int) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"dataset {dataset_id} not found")
    return dataset


def _points(dataset: Dataset) -> list[tuple]:
    return [(p.ts, p.value) for p in sorted(dataset.points, key=lambda p: p.ts)]


@router.post("", response_model=IngestReport, status_code=201)
async def upload_dataset(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    value_column: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Upload a CSV, validate it row by row, and store the accepted points."""
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file is {len(raw)} bytes; limit is {MAX_UPLOAD_BYTES}",
        )

    try:
        parsed = parse_csv(raw, value_column=value_column, max_rows=MAX_ROWS)
    except IngestError as exc:
        # The file was understood well enough to reject it precisely — 422, not 500.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    dataset = Dataset(
        name=name or (file.filename or "dataset").rsplit(".", 1)[0],
        source_filename=file.filename or "upload.csv",
        value_column=parsed.value_column,
        row_count=len(parsed.rows),
        rejected_rows=parsed.rejected,
    )
    dataset.points = [DataPoint(ts=ts, value=value) for ts, value in parsed.rows]

    db.add(dataset)
    db.commit()
    db.refresh(dataset)

    return IngestReport(
        dataset=DatasetOut.model_validate(dataset),
        accepted=len(parsed.rows),
        rejected=parsed.rejected,
        reasons=dict(parsed.reasons),
    )


@router.get("", response_model=list[DatasetOut])
def list_datasets(db: Session = Depends(get_db)):
    stmt = select(Dataset).order_by(Dataset.created_at.desc())
    return list(db.scalars(stmt).all())


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: int, db: Session = Depends(get_db)):
    return _load(db, dataset_id)


@router.get("/{dataset_id}/summary", response_model=Summary)
def get_summary(dataset_id: int, db: Session = Depends(get_db)):
    dataset = _load(db, dataset_id)
    return Summary(dataset_id=dataset.id, **summarize(_points(dataset)))


@router.get("/{dataset_id}/anomalies", response_model=AnomalyReport)
def get_anomalies(
    dataset_id: int,
    threshold: float = Query(3.0, ge=0.5, le=10.0, description="z-score cutoff"),
    mode: str = Query(
        "global",
        pattern="^(global|rolling)$",
        description="global: z-score against the whole series. "
        "rolling: against the preceding window only — use this on seasonal data, "
        "where a global score flags every cycle peak.",
    ),
    window: int = Query(
        24, ge=2, le=1000, description="rolling mode only: points in the trailing window"
    ),
    db: Session = Depends(get_db),
):
    dataset = _load(db, dataset_id)
    points = _points(dataset)
    if mode == "rolling":
        found = find_anomalies_rolling(points, window=window, threshold=threshold)
    else:
        found = find_anomalies(points, threshold=threshold)
    return AnomalyReport(
        dataset_id=dataset.id,
        mode=mode,
        threshold=threshold,
        window=window if mode == "rolling" else None,
        count=len(found),
        anomalies=found,
    )


@router.get("/{dataset_id}/points", response_model=list[PointOut])
def get_points(
    dataset_id: int,
    limit: int = Query(1000, ge=1, le=10_000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    dataset = _load(db, dataset_id)
    window = _points(dataset)[offset : offset + limit]
    return [PointOut(ts=ts, value=value) for ts, value in window]


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: int, db: Session = Depends(get_db)):
    db.delete(_load(db, dataset_id))
    db.commit()
