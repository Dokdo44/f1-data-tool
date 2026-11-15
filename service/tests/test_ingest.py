from datetime import datetime, timedelta, timezone

import pytest

from app.ingest import IngestError, parse_csv, parse_timestamp
from app.stats import find_anomalies, find_anomalies_rolling, summarize


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



# ---- rolling-window anomaly detection ----
#
# These assert measured behaviour, including where the method does not help.

import math
import random


def _series(values):
    """Build (ts, value) points one minute apart."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [(base + timedelta(minutes=i), float(v)) for i, v in enumerate(values)]


def _drift_with_spike():
    random.seed(11)
    v = [10 + i * 0.25 + random.gauss(0, 0.3) for i in range(120)]
    v[80] += 6.0
    return _series(v), v[80]


def test_rolling_catches_a_spike_on_a_drift_that_global_misses():
    # The drift dominates the global spread, so the spike scores low against the
    # whole series and is never reported. Against its own window it is obvious.
    points, spike = _drift_with_spike()
    assert find_anomalies(points, threshold=3.0) == []
    found = find_anomalies_rolling(points, window=20, threshold=3.0)
    assert [f["value"] for f in found] == [spike]


def test_rolling_catches_a_level_shift_that_global_misses():
    # A clean step between two stable levels: globally the two levels define the
    # spread, so nothing is extreme. The transition shows up in a trailing window.
    random.seed(11)
    v = [5 + random.gauss(0, 0.2) for _ in range(60)]
    v += [25 + random.gauss(0, 0.2) for _ in range(60)]
    points = _series(v)
    assert find_anomalies(points, threshold=3.0) == []
    assert len(find_anomalies_rolling(points, window=20, threshold=3.0)) > 0


def test_rolling_does_not_solve_a_smooth_cycle():
    # Documented limitation. A short window does surface the planted fault, but
    # alongside ~14 false positives from the cycle's own steep flanks — a signal
    # nobody would act on. A window long enough to span the cycle reproduces the
    # global result and finds nothing. Seasonal data needs the cycle removed first;
    # this test records that so the next person does not assume otherwise.
    random.seed(7)
    v = [20 + 10 * math.sin(i / 12 * math.pi) + random.gauss(0, 0.4) for i in range(144)]
    v[90] = 30.0  # daytime level during the nightly trough — a genuine fault
    points = _series(v)

    short = find_anomalies_rolling(points, window=6, threshold=3.0)
    long = find_anomalies_rolling(points, window=24, threshold=3.0)

    # Short window: the fault is found, but buried among the cycle's own flanks.
    assert 30.0 in [f["value"] for f in short]
    assert len(short) > 10                      # i.e. mostly false positives
    # Long window: spans the cycle, reproduces the global result, finds nothing.
    assert long == []


def test_rolling_skips_the_startup_period():
    # The spike sits before min_periods of history exists.
    points = _series([10, 10, 900, 10, 10, 10])
    assert find_anomalies_rolling(points, window=24, threshold=2.0, min_periods=3) == []


def test_rolling_passes_over_a_flat_window():
    # Constant baseline → stdev 0 → no scale, so no verdict rather than a crash.
    points = _series([5] * 10 + [99])
    assert find_anomalies_rolling(points, window=5, threshold=2.0) == []


def test_rolling_excludes_the_point_from_its_own_baseline():
    # Included in its own window, a large outlier would shrink its own score.
    points = _series([1, 2, 1, 2, 1, 50])
    found = find_anomalies_rolling(points, window=5, threshold=2.0, min_periods=3)
    assert [f["value"] for f in found] == [50.0]


def test_rolling_rejects_a_degenerate_window():
    with pytest.raises(ValueError):
        find_anomalies_rolling(_series([1, 2, 3]), window=1)
