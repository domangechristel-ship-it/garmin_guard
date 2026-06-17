# Garmin Guard

Personal athletic performance dashboard built on top of Garmin Connect data. Syncs directly from the Garmin Connect API, computes training load metrics, and serves them through a FastAPI backend with a Streamlit dashboard — with an optional sync to BigQuery for cloud deployment.

---

## Architecture

```
Garmin DI_CONNECT export          Garmin Connect API
         │                              │
         ▼                              ▼
  garmin_parser.py          sync_garmin_connect.py
  wellness_parser.py        (activities · wellness ·
                             planned workouts)
         │                              │
         └──────────────┬───────────────┘
                        ▼
               data/processed/*.csv
                        │
                        ▼
               load_duckdb.py  ──────→  garmin_guard.duckdb  (local, private)
                        │
                        ▼
              export_bigquery.py ────→  BigQuery (anonymised subset)
                        │
               ┌────────┴────────┐
               ▼                 ▼
         FastAPI (local)    FastAPI (Cloud Run)
         reads DuckDB        reads BigQuery
               │                 │
               └────────┬────────┘
                        ▼
               Streamlit dashboard
```

The API is dual-mode: when `ENV=local` it queries the local DuckDB file; when `ENV=prod` it queries BigQuery. The Streamlit app always talks to the API, so it works identically in both environments.

---

## Data sources

### Garmin DI_CONNECT export (historical backfill)

| Parser | Garmin export file | Output |
|---|---|---|
| `garmin_parser.py` | `DI-Connect-Fitness/*_summarizedActivities.json` | `activities_normalized.csv` |
| `wellness_parser.py` | `DI-Connect-Wellness/*` | `wellness_normalized.csv` |

### Garmin Connect API (daily sync)

`sync_garmin_connect.py` connects to the Garmin Connect API directly and fetches activities, wellness data, and planned workouts incrementally from the last known date. Planned workouts are stored in `data/processed/planned_workouts.csv` and exposed via the `/planned-workouts` API endpoint.

Requires `GARMIN_EMAIL` and `GARMIN_PASSWORD` in `.env`. Optionally deployable as a Prefect flow (`garmin_connect_daily_sync`) for automated daily runs at 07:00.

---

**Wellness signals parsed:** sleep score & durations (deep / light / REM / awake), menstrual cycle phases (day in cycle, period active flag), daily symptoms & moods, weight, resting HR, VO2max (biometric), biological age, BMI, HRV (RMSSD & SDRR).

**Activity fields parsed:** distance, duration, moving time, pace, HR (avg / max / min / zones), cadence, stride length, elevation (gain / loss / min / max), calories, TSS, aerobic training effect, VO2max, body battery delta, GPS start coordinates, gear.

**Computed training load metrics:**

| Metric | Formula |
|---|---|
| ATL | 7-day exponential weighted mean of daily TSS |
| CTL | 42-day exponential weighted mean of daily TSS |
| TSB | CTL − ATL (positive = fresh, negative = fatigued) |
| ACWR | ATL / CTL |
| ACWR zone | < 0.8 under-load · 0.8–1.3 optimal · 1.3–1.5 caution · > 1.5 risk |

A TSS proxy (`duration_s × avg_hr / 3600 / 10`) is used automatically when Garmin does not provide a TSS value.

---

## GDPR design

Sensitive data (GPS coordinates, device ID, menstrual cycle, sleep durations, HRV, weight, body battery) **stays local in DuckDB and is never exported to BigQuery**. The BigQuery export contains only anonymised aggregate performance signals.

---

## Requirements

- Python 3.12
- A Garmin Connect account with credentials set in `.env`:
  ```
  GARMIN_EMAIL=...
  GARMIN_PASSWORD=...
  ```
- (Optional) A Garmin DI_CONNECT data export placed under `data/raw/DI_CONNECT/` for historical backfill
- (Optional) GCP project for BigQuery / Cloud Run deployment

Install dependencies:

```bash
make install
```

---

## Running locally

Start the API and the dashboard in one command:

```bash
make start_local
```

This kills any stale process on port 8000, starts the FastAPI backend, waits until it is healthy, then launches Streamlit. The API process is cleaned up automatically on Ctrl+C.

Or run the dashboard alone (assumes the API is already running):

```bash
make run_dashboard
```

The dashboard is available at `http://localhost:8501`.

---

## Data pipeline

| Command | What it does |
|---|---|
| `make garmin_update` | Parse activities + wellness CSVs from raw DI_CONNECT export |
| `make load_duckdb` | Load processed CSVs into `data/garmin_guard.duckdb` |
| `make garmin_full_update` | Parse DI_CONNECT export + load DuckDB |
| `make garmin_daily_sync` | Sync from Garmin Connect API (incremental) + load DuckDB |
| `make fetch_new_data` | Full pipeline: parse DI_CONNECT · sync Garmin Connect API · load DuckDB · export BigQuery |
| `make export_bigquery` | Push anonymised tables to BigQuery |

---

## Dashboard

Four tabs, with date range and sport type filters in the sidebar:

**Training Load** — ATL/CTL trend, TSB bar chart (green = fresh / red = fatigued), ACWR with colour-coded risk zones.

**Activities** — total distance, sessions, average HR, cumulative elevation; weekly volume chart (running + cycling stacked); sortable activity table.

**Wellness** — sleep score with 7-day rolling average; sleep duration breakdown (deep / REM / light / awake). All charts support an optional menstrual cycle phase overlay (coloured vertical bands), disabled in prod mode to protect private data.

**Plan d'entraînement** — ACWR dashboard showing the last 30 days of actual load alongside a 60-day forward projection based on planned workouts synced from Garmin Connect. Planned sessions are shown as diamond markers on the projected ACWR curve. An optional menstrual cycle overlay is auto-derived from synced Garmin wellness data (no manual input required). The training plan generator backend (`src/training_plan/`) supports cycle-aware plan generation; the form UI is currently in progress.

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Status + active environment |
| GET | `/activities` | All activities, optional `start_date`, `end_date`, `sport_type` filters |
| GET | `/training-load` | Daily ATL/CTL/TSB/ACWR, optional date filters |
| GET | `/wellness` | Daily wellness data, optional date filters |
| GET | `/planned-workouts` | Planned workouts from Garmin Connect, optional `start_date`, `end_date` filters |
| POST | `/training-plan` | Generate a cycle-aware training plan from a `TrainingPlanRequest` body |

---

## Training plan engine

`src/training_plan/` is a standalone module that generates periodised running plans:

- **Macrocycle** — BUILD / RECOVERY / TAPER blocks, auto-sized based on weeks to race
- **ACWR-constrained load** — weekly target TSS is adjusted iteratively to keep projected ACWR in the 0.8–1.3 optimal zone
- **Cycle-aware modulation** — when `last_period_start` is provided, load and session type are modulated per menstrual phase (MENSTRUAL / FOLLICULAR / OVULATION / LUTEAL_EARLY / LUTEAL_LATE)
- **Session distribution** — long run anchored on a preferred day, with INTERVAL / TEMPO / SHORT_RUN / RECOVERY slots assigned per block and cycle phase

---

## Deployment to GCP Cloud Run

Set the required environment variables in `.env`:

```
GCP_PROJECT=...
GCP_REGION=...
ARTIFACTSREPO=...
IMAGE=...
DASHBOARD_IMAGE=...
MEMORY=...
API_URL=...
GCP_EMAIL=...
```

One-time setup:

```bash
make auth
make check_permission
make create_artifact
```

Deploy API + dashboard:

```bash
make deploy_full
```

---

## Tech stack

- **Ingestion** — Python, pandas, garminconnect, prefect (optional)
- **Storage** — DuckDB (local), BigQuery (cloud)
- **Backend** — FastAPI, uvicorn
- **Frontend** — Streamlit, Plotly
- **Infrastructure** — Docker, GCP Artifact Registry, GCP Cloud Run
