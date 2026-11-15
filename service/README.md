# Time-Series Insights API

A REST service wrapping the same validation ideas as the CLI pipeline in `../src`:
upload a CSV of measurements, have every row validated before it is stored, and get
back summary statistics and outlier detection.

The CLI answers "analyze this file for me." The service answers "store this, and let
me query it later" — which meant the validation had to stop being a side effect of
reading a file and become something with a reportable result.

**Stack** — Python 3.12 · FastAPI · PostgreSQL (SQLAlchemy 2.0) · Docker · pytest

---

## Run it

### Docker (Postgres included)

```bash
cp .env.example .env
docker compose up --build
```

Upload page at <http://localhost:8000>, OpenAPI docs at <http://localhost:8000/docs>.

### Local (SQLite, no Postgres)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

`DATABASE_URL` is unset locally, so it falls back to a SQLite file. Nothing else changes.

### Tests

```bash
pytest -q          # 29 tests, no database required
```

---

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/datasets` | Upload a CSV. Returns the stored dataset plus an accepted/rejected breakdown. |
| `GET` | `/datasets` | List datasets, newest first. |
| `GET` | `/datasets/{id}` | One dataset's metadata. |
| `GET` | `/datasets/{id}/summary` | count, min, max, mean, median, stdev, time range. |
| `GET` | `/datasets/{id}/anomalies?threshold=3.0&mode=global\|rolling&window=24` | Points whose z-score exceeds the threshold. |
| `GET` | `/datasets/{id}/points?limit=&offset=` | Raw points, paginated. |
| `DELETE` | `/datasets/{id}` | Delete a dataset and its points. |
| `GET` | `/healthz` | Liveness probe. |

```bash
curl -F "file=@samples/sensor_clean.csv" http://localhost:8000/datasets
curl http://localhost:8000/datasets/1/summary
curl "http://localhost:8000/datasets/1/anomalies?threshold=2.5"
```

---

## Validation

A row is rejected, counted, and reported — never silently coerced — when it is ragged,
has a missing field, an unparseable timestamp, a non-numeric value, or a NaN/infinite value.

`samples/messy.csv` triggers one of each:

```json
{
  "accepted": 2,
  "rejected": 5,
  "reasons": {
    "bad_timestamp": 1, "non_numeric_value": 1, "missing_value": 1,
    "extra_columns": 1, "non_finite_value": 1
  }
}
```

**Timestamp handling.** ISO-8601 is tried first, then a list of common formats. A timestamp
with no offset is assumed UTC — stated here because the assumption is otherwise invisible.

**Column selection.** The timestamp column is found by name (`timestamp`, `ts`, `time`,
`date`, `datetime`); the value column defaults to the first non-timestamp column, or is
named explicitly in the request.

---

## Layout

```
app/main.py              FastAPI app, static mount, health check
app/config.py            env config, postgres:// URL normalization
app/db.py                engine, session, Base
app/models.py            Dataset, DataPoint (+ composite index on dataset_id, ts)
app/schemas.py           Pydantic request/response models
app/ingest.py            CSV parsing and row-level validation
app/stats.py             summary statistics, z-score anomaly detection
app/routers/datasets.py  HTTP layer
static/index.html        upload page with Chart.js chart
tests/                   29 tests (unit + API)
samples/                 clean and deliberately malformed CSVs
```

---

## Known limitations

- Schema is created with `create_all()` at startup. Fine for one service; Alembic before
  the schema starts changing in production.
- Summary statistics load the full dataset into memory. Acceptable at the 200k-row cap;
  beyond that, push the aggregation into SQL.
- Two detection modes. `global` scores against the whole series; `rolling` scores each
  point against the preceding `window` only. Rolling finds spikes riding on a drift and
  clean level shifts, both of which global misses because the movement itself dominates
  the spread. Neither handles a smooth cycle: a short window reports the flanks, a long
  one washes the cycle out. Seasonal data needs the cycle modelled and removed first —
  `test_rolling_does_not_solve_a_smooth_cycle` pins that down.
- No authentication. Every dataset is readable by anyone with the URL.

## Roadmap

- [ ] Median/MAD scoring, so one outlier stops masking the next
- [ ] Seasonal decomposition before scoring
- [ ] SQL-side aggregation for the summary endpoint
- [ ] Alembic migrations
- [ ] GitHub Actions running `pytest` on every push
