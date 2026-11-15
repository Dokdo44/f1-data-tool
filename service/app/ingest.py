"""CSV ingestion.

Every row is guilty until proven valid. A malformed row is counted and dropped,
never silently coerced, and the caller gets a per-reason breakdown so a bad
upload can be diagnosed without opening the file.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

TIMESTAMP_CANDIDATES = ("timestamp", "ts", "time", "date", "datetime")

# Formats are tried in order; ISO-8601 first because it is what most tools emit.
TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
)


class IngestError(ValueError):
    """The file as a whole is unusable (no header, no usable columns, too big)."""


@dataclass
class ParseResult:
    rows: list[tuple[datetime, float]] = field(default_factory=list)
    rejected: int = 0
    reasons: Counter = field(default_factory=Counter)
    timestamp_column: str = ""
    value_column: str = ""


def parse_timestamp(raw: str) -> datetime:
    """Parse a timestamp string, returning an aware UTC datetime."""
    text = raw.strip()
    if not text:
        raise ValueError("empty timestamp")

    # Python 3.11+ fromisoformat handles offsets and the trailing Z.
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None

    if parsed is None:
        for fmt in TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue

    if parsed is None:
        raise ValueError(f"unrecognized timestamp format: {text!r}")

    # Naive input is assumed UTC. Stated here because the assumption is silent otherwise.
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def pick_columns(header: list[str], value_column: str | None) -> tuple[str, str]:
    """Choose the timestamp and value columns, or explain why we cannot."""
    if not header:
        raise IngestError("CSV has no header row")

    cleaned = [h.strip() for h in header]
    lowered = {h.lower(): h for h in cleaned}

    ts_col = next((lowered[c] for c in TIMESTAMP_CANDIDATES if c in lowered), None)
    if ts_col is None:
        raise IngestError(
            "no timestamp column found; expected one of: "
            + ", ".join(TIMESTAMP_CANDIDATES)
        )

    if value_column:
        if value_column not in cleaned:
            raise IngestError(f"value column {value_column!r} not in header: {cleaned}")
        return ts_col, value_column

    # Default to the first column that is not the timestamp.
    remaining = [h for h in cleaned if h != ts_col]
    if not remaining:
        raise IngestError("CSV has a timestamp column but no value column")
    return ts_col, remaining[0]


def parse_csv(
    raw: bytes, value_column: str | None = None, max_rows: int = 200_000
) -> ParseResult:
    """Parse raw CSV bytes into (timestamp, value) pairs."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestError("file is not valid UTF-8 text") from exc

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise IngestError("CSV is empty")

    ts_col, val_col = pick_columns(list(reader.fieldnames), value_column)
    result = ParseResult(timestamp_column=ts_col, value_column=val_col)

    for row in reader:
        if len(result.rows) >= max_rows:
            raise IngestError(f"file exceeds the {max_rows} row limit")

        # DictReader stores surplus fields under None — a ragged row.
        if None in row and row[None]:
            result.rejected += 1
            result.reasons["extra_columns"] += 1
            continue

        raw_ts = (row.get(ts_col) or "").strip()
        raw_val = (row.get(val_col) or "").strip()

        if not raw_ts or not raw_val:
            result.rejected += 1
            result.reasons["missing_value"] += 1
            continue

        try:
            ts = parse_timestamp(raw_ts)
        except ValueError:
            result.rejected += 1
            result.reasons["bad_timestamp"] += 1
            continue

        try:
            value = float(raw_val)
        except ValueError:
            result.rejected += 1
            result.reasons["non_numeric_value"] += 1
            continue

        if value != value or value in (float("inf"), float("-inf")):
            result.rejected += 1
            result.reasons["non_finite_value"] += 1
            continue

        result.rows.append((ts, value))

    if not result.rows:
        raise IngestError(
            f"no valid rows found (rejected {result.rejected}: {dict(result.reasons)})"
        )

    result.rows.sort(key=lambda pair: pair[0])
    return result
