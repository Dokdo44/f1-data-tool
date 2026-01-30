# src/main.py
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import fastf1

METRIC_COL = "LapTimeSeconds"

def parse_args():
    p = argparse.ArgumentParser(description="F1 session data -> cleaned csv + stats + plots + report")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--event", type=str, required=True, help='e.g., "Bahrain" or "Monaco"')
    p.add_argument("--session", type=str, required=True, help='e.g., "R", "Q", "FP1"')
    p.add_argument("--cache", type=str, default="cache")
    p.add_argument("--out", type=str, default=".")
    return p.parse_args()

def ensure_dirs(root: Path):
    (root / "data" / "processed").mkdir(parents=True, exist_ok=True)
    (root / "outputs" / "figures").mkdir(parents=True, exist_ok=True)

def load_session(year: int, event: str, session_code: str):
    # Cache speeds up repeated runs and avoids rate limits
    fastf1.Cache.enable_cache("cache")  # can be overridden by args, but safe default
    s = fastf1.get_session(year, event, session_code)
    s.load()  # loads timing/lap/telemetry related session data
    return s

def build_laps_df(session) -> pd.DataFrame:
    laps = session.laps.copy()

    # Minimal columns that are typically useful for "testing-data" style analysis
    cols = []
    for c in ["Time", "Driver", "LapNumber", "LapTime", "Stint", "Compound",
              "TyreLife", "FreshTyre", "TrackStatus", "IsAccurate"]:
        if c in laps.columns:
            cols.append(c)

    df = laps[cols].copy()

    # Standardize names (looks like "experiment pipeline")
    rename_map = {
        "Time": "timestamp",
        "Driver": "entity_id",
        "LapNumber": "run_index",
        "LapTime": "measurement_laptime",
        "Compound": "condition_compound",
        "Stint": "group_stint",
        "TyreLife": "condition_tyre_life",
        "FreshTyre": "condition_fresh_tyre",
        "TrackStatus": "meta_track_status",
        "IsAccurate": "meta_is_accurate",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Convert LapTime to seconds for easier stats/plots
    if "measurement_laptime" in df.columns:
        # measurement_laptime is a timedelta-like
        df[METRIC_COL] = df["measurement_laptime"].dt.total_seconds()

    # Basic cleaning
    if "meta_is_accurate" in df.columns:
        df = df[df["meta_is_accurate"] == True]

    # Drop impossible rows
    if METRIC_COL in df.columns:
        df = df.dropna(subset=[METRIC_COL])

    # Timestamp normalize
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    return df

def summary_stats(df: pd.DataFrame) -> pd.DataFrame:
    group_cols = [c for c in ["entity_id", "group_stint", "condition_compound"] if c in df.columns]
    if METRIC_COL not in df.columns:
        return pd.DataFrame({"n": [len(df)]})

    if group_cols:
        out = df.groupby(group_cols)[METRIC_COL].agg(["count", "mean", "std", "min", "max"]).reset_index()
        return out

    return df[[METRIC_COL]].agg(["count", "mean", "std", "min", "max"]).reset_index()

def plot_trend(df: pd.DataFrame, fig_path: Path):
    if "run_index" not in df.columns or METRIC_COL not in df.columns:
        return
    d = df.dropna(subset=["run_index", METRIC_COL]).sort_values("run_index")
    if d.empty:
        return

    plt.figure()
    plt.plot(d["run_index"], d[METRIC_COL])
    plt.xlabel("LapNumber")
    plt.ylabel("LapTime (s)")
    plt.tight_layout()
    plt.savefig(fig_path, dpi=200)
    plt.close()

def plot_hist(df: pd.DataFrame, fig_path: Path):
    if METRIC_COL not in df.columns:
        return
    d = df[METRIC_COL].dropna()
    if d.empty:
        return

    plt.figure()
    plt.hist(d, bins=30)
    plt.xlabel("LapTime (s)")
    plt.ylabel("Count")
    plt.tight_layout()
    plt.savefig(fig_path, dpi=200)
    plt.close()

def write_report(root: Path, meta: dict, figures: list[str], outputs: dict):
    report = root / "outputs" / "report.md"
    with report.open("w", encoding="utf-8") as f:
        f.write("# Session Data Analysis Report\n\n")
        f.write("## Run Info\n")
        for k, v in meta.items():
            f.write(f"- {k}: {v}\n")
        f.write("\n## Outputs\n")
        for k, v in outputs.items():
            f.write(f"- {k}: {v}\n")
        f.write("\n## Figures\n")
        for fig in figures:
            f.write(f"![{fig}](figures/{fig})\n\n")

def main():
    args = parse_args()
    root = Path(args.out).resolve()
    ensure_dirs(root)

    # cache dir from args
    Path(args.cache).mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(Path(args.cache).resolve()))

    session = fastf1.get_session(args.year, args.event, args.session)
    session.load()  # standard entry point
    # docs: session.load and laps object usage
    # (see FastF1 docs)
    # :contentReference[oaicite:3]{index=3}

    df = build_laps_df(session)

    processed_path = root / "data" / "processed" / f"{args.year}_{args.event}_{args.session}_cleaned.csv"
    df.to_csv(processed_path, index=False)

    summary = summary_stats(df)
    summary_path = root / "outputs" / f"{args.year}_{args.event}_{args.session}_summary.csv"
    summary.to_csv(summary_path, index=False)

    fig_dir = root / "outputs" / "figures"
    trend_name = f"{args.year}_{args.event}_{args.session}_trend.png"
    hist_name = f"{args.year}_{args.event}_{args.session}_hist.png"
    plot_trend(df, fig_dir / trend_name)
    plot_hist(df, fig_dir / hist_name)

    write_report(
        root=root,
        meta={"year": args.year, "event": args.event, "session": args.session},
        figures=[trend_name, hist_name],
        outputs={
            "cleaned_csv": str(processed_path.relative_to(root)),
            "summary_csv": str(summary_path.relative_to(root)),
        },
    )

    print("Done.")
    print("Cleaned:", processed_path)
    print("Summary:", summary_path)
    print("Report:", root / "outputs" / "report.md")

if __name__ == "__main__":
    main()

