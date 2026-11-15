"""Summary statistics and z-score anomaly detection.

Plain stdlib: the volumes here are small enough that pandas would be a
dependency without a payoff, and keeping it out makes the container smaller.
"""

from __future__ import annotations

import statistics
from datetime import datetime


def summarize(points: list[tuple[datetime, float]]) -> dict:
    if not points:
        raise ValueError("cannot summarize an empty dataset")

    values = [v for _, v in points]
    timestamps = [ts for ts, _ in points]

    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        # A single point has no spread; stdev would raise.
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "first_ts": min(timestamps),
        "last_ts": max(timestamps),
    }


def find_anomalies(
    points: list[tuple[datetime, float]], threshold: float = 3.0
) -> list[dict]:
    """Return points whose z-score exceeds the threshold.

    A flat series has stdev 0, which would divide by zero — it has no outliers
    by definition, so we return nothing rather than raising.
    """
    if len(points) < 2:
        return []

    values = [v for _, v in points]
    mean = statistics.fmean(values)
    stdev = statistics.stdev(values)
    if stdev == 0:
        return []

    out = []
    for ts, value in points:
        z = (value - mean) / stdev
        if abs(z) >= threshold:
            out.append({"ts": ts, "value": value, "z_score": z})
    return out
