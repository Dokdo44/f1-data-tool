from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Dataset(Base):
    """One uploaded CSV file."""

    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    value_column: Mapped[str] = mapped_column(String(100), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    points: Mapped[list["DataPoint"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", lazy="selectin"
    )


class DataPoint(Base):
    """One (timestamp, value) pair belonging to a dataset."""

    __tablename__ = "data_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)

    dataset: Mapped[Dataset] = relationship(back_populates="points")


# Summary and anomaly queries both scan one dataset in timestamp order.
Index("ix_points_dataset_ts", DataPoint.dataset_id, DataPoint.ts)
