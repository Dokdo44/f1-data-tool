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


def find_anomalies_rolling(
    points: list[tuple[datetime, float]],
    window: int = 24,
    threshold: float = 3.0,
    min_periods: int = 3,
) -> list[dict]:
    """Score each point against the window immediately before it, not the whole series.

    `find_anomalies` divides by the standard deviation of the entire series. When the
    series drifts or steps, that spread is dominated by the movement itself, and a
    genuine spike sitting on top of the drift no longer looks far from the mean. On a
    series rising 0.25/step for 120 steps, a +6 spike scores under 1.0 globally and is
    never reported; measured against its own preceding window it scores above 4 and is.
    A sensor recalibration — a clean step from one level to another — is invisible
    globally for the same reason, and shows up here as the transition it is.

    What this does NOT fix, measured rather than assumed: a smooth cycle. On a daily
    sine wave the trailing window lags the curve, so a window short enough to track the
    local level (4-8 points against a 24-point period) reports the steep flanks as
    anomalies, and a window long enough to span the cycle reproduces the global result
    and reports nothing. Seasonal data needs the cycle modelled and removed first, or
    each point compared against the same phase of earlier cycles. Neither is done here.

    Three design decisions, all of them arguable:

    1. **Trailing window, excluding the point itself.** A point included in its own
       baseline pulls the mean toward itself and shrinks its own score — the larger the
       outlier, the better it hides. Centred windows detect better but cannot run on a
       live stream, so a trailing window is the choice that keeps this usable on
       incoming data.

    2. **The startup period is skipped, not approximated.** The first points have no
       history. Judging them against two or three neighbours, where one value swings
       the standard deviation enough to make the verdict meaningless, is worse than
       saying nothing — so nothing is reported until `min_periods` points exist. The
       cost: a true anomaly in the opening readings is missed.

    3. **A flat window yields no verdict.** If the baseline is constant the standard
       deviation is zero and no score is defined. The next point could be a real jump,
       but there is no scale to measure it against, so it is passed over rather than
       flagged. A stuck sensor that starts moving again is the case this misses.

    A further limitation left in deliberately: an outlier that enters the window
    inflates the baseline spread and can mask a second outlier just behind it. Median
    and MAD in place of mean and standard deviation would resist that.
    """
    if window < 2:
        raise ValueError("window must be at least 2")
    if min_periods < 2:
        raise ValueError("min_periods must be at least 2")

    out = []
    for i, (ts, value) in enumerate(points):
        baseline = [v for _, v in points[max(0, i - window) : i]]
        if len(baseline) < min_periods:
            continue  # decision 2 — not enough history to judge

        stdev = statistics.stdev(baseline)
        if stdev == 0:
            continue  # decision 3 — no scale to measure against

        z = (value - statistics.fmean(baseline)) / stdev
        if abs(z) >= threshold:
            out.append({"ts": ts, "value": value, "z_score": z})
    return out
