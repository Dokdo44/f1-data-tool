# Time-Series Session Data Analysis Tool

A one-command pipeline that ingests a Formula 1 session, cleans it into a generic
time-series schema, computes summary statistics, plots the result, and writes a
markdown report — all from a single CLI invocation.

The F1 data is a convenient public source of messy, real time-series measurements.
The pipeline itself is domain-agnostic: columns are renamed into a neutral
`entity / run_index / measurement / condition / meta` schema on ingest, so the same
stages apply to any repeated-measurement dataset.

**Stack** — Python 3 · pandas · matplotlib · FastF1 · argparse

---

## Usage

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install fastf1 pandas matplotlib

python src/main.py --year 2024 --event Bahrain --session R
```

| Flag | Required | Description |
|---|---|---|
| `--year` | yes | Season, e.g. `2024` |
| `--event` | yes | Event name, e.g. `Bahrain`, `Monaco` |
| `--session` | yes | Session code — `R`, `Q`, `FP1`, … |
| `--cache` | no | FastF1 cache directory (default `cache`) |
| `--out` | no | Output root (default `.`) |

## Pipeline

1. **Ingest** — load the session through FastF1, with an on-disk cache so repeated runs
   do not re-download or hit rate limits
2. **Select and standardize** — keep only columns present in the source, then rename them
   into a neutral schema (`timestamp`, `entity_id`, `run_index`, `measurement_laptime`,
   `condition_*`, `meta_*`) so downstream stages do not depend on F1 vocabulary
3. **Clean** — convert lap times to seconds, drop rows the source marks inaccurate
4. **Summarize** — per-entity descriptive statistics written to CSV
5. **Plot** — trend over run index, and distribution histogram
6. **Report** — a markdown report linking the cleaned data, the summary, and both figures

## Outputs

```
data/processed/{year}_{event}_{session}_cleaned.csv   cleaned measurements
outputs/{year}_{event}_{session}_summary.csv          per-entity statistics
outputs/figures/{...}_trend.png                       measurement over run index
outputs/figures/{...}_hist.png                        distribution
outputs/report.md                                     generated report
```

A complete run for the 2024 Bahrain Grand Prix is committed under `outputs/` and
`data/processed/` as a worked example.

## Design notes

**Column selection is defensive.** The source schema varies by session and season, so the
loader keeps only the columns that are actually present rather than assuming a fixed set —
a missing `TyreLife` column degrades the output instead of raising.

**Caching is on by default.** Sessions are large and the upstream API is rate-limited, so
repeated runs during development read from disk.

## Roadmap

- [ ] Outlier detection on the measurement column
- [ ] Multi-session comparison in one run
- [ ] Unit tests for the cleaning and summary stages
