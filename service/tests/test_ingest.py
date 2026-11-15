from datetime import datetime, timezone

import pytest

from app.ingest import IngestError, parse_csv, parse_timestamp
from app.stats import find_anomalies, summarize


def test_parse_timestamp_handles_iso_and_common_formats():
    assert parse_timestamp("2026-01-01T12:30:00") == datetime(
        2026, 1, 1, 12, 30, tzinfo=timezone.utc
    )
    assert parse_timestamp("2026-01-01 12:30:00").hour == 12
    assert parse_timestamp("2026-01-01").day == 1


def test_parse_timestamp_normalizes_offsets_to_utc():
    assert parse_timestamp("2026-01-01T12:00:00+02:00").hour == 10


def test_parse_timestamp_rejects_garbage():
    with pytest.raises(ValueError):
        parse_timestamp("yesterday")


def test_parse_csv_sorts_out_of_order_rows():
    raw = b"timestamp,value\n2026-01-02,5\n2026-01-01,3\n"
    result = parse_csv(raw)
    assert [v for _, v in result.rows] == [3.0, 5.0]


def test_parse_csv_picks_first_non_timestamp_column_by_default():
    raw = b"ts,temperature,humidity\n2026-01-01,20,50\n"
    assert parse_csv(raw).value_column == "temperature"


def test_parse_csv_honours_explicit_value_column():
    raw = b"ts,temperature,humidity\n2026-01-01,20,50\n"
    result = parse_csv(raw, value_column="humidity")
    assert result.rows[0][1] == 50.0


def test_parse_csv_rejects_ragged_rows():
    raw = b"timestamp,value\n2026-01-01,1,oops\n2026-01-02,2\n"
    result = parse_csv(raw)
    assert result.reasons["extra_columns"] == 1
    assert len(result.rows) == 1


def test_parse_csv_rejects_non_finite_values():
    raw = b"timestamp,value\n2026-01-01,nan\n2026-01-02,2\n"
    result = parse_csv(raw)
    assert result.reasons["non_finite_value"] == 1


def test_parse_csv_raises_when_every_row_is_bad():
    with pytest.raises(IngestError):
        parse_csv(b"timestamp,value\nbad,bad\n")


def test_parse_csv_enforces_row_limit():
    rows = b"".join(f"2026-01-0{i%9+1},{i}\n".encode() for i in range(50))
    with pytest.raises(IngestError):
        parse_csv(b"timestamp,value\n" + rows, max_rows=10)


def test_summarize_computes_expected_statistics():
    points = [(datetime(2026, 1, d, tzinfo=timezone.utc), float(d)) for d in range(1, 6)]
    s = summarize(points)
    assert (s["count"], s["min"], s["max"], s["mean"], s["median"]) == (5, 1, 5, 3, 3)


def test_summarize_handles_single_point_without_stdev_error():
    points = [(datetime(2026, 1, 1, tzinfo=timezone.utc), 7.0)]
    assert summarize(points)["stdev"] == 0.0


def test_find_anomalies_returns_nothing_for_a_flat_series():
    points = [(datetime(2026, 1, d, tzinfo=timezone.utc), 5.0) for d in range(1, 6)]
    assert find_anomalies(points) == []


def test_find_anomalies_flags_outlier():
    points = [(datetime(2026, 1, d, tzinfo=timezone.utc), 10.0) for d in range(1, 10)]
    points.append((datetime(2026, 1, 10, tzinfo=timezone.utc), 500.0))
    found = find_anomalies(points, threshold=2.0)
    assert len(found) == 1 and found[0]["value"] == 500.0
