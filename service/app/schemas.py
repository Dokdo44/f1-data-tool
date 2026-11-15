from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source_filename: str
    value_column: str
    row_count: int
    rejected_rows: int
    created_at: datetime


class IngestReport(BaseModel):
    """What the parser accepted, what it threw away, and why."""

    dataset: DatasetOut
    accepted: int
    rejected: int
    reasons: dict[str, int]


class Summary(BaseModel):
    dataset_id: int
    count: int
    min: float
    max: float
    mean: float
    median: float
    stdev: float
    first_ts: datetime
    last_ts: datetime


class Anomaly(BaseModel):
    ts: datetime
    value: float
    z_score: float


class AnomalyReport(BaseModel):
    dataset_id: int
    mode: str
    threshold: float
    window: int | None = None
    count: int
    anomalies: list[Anomaly]


class PointOut(BaseModel):
    ts: datetime
    value: float
