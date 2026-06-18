"""
daily_pipeline.py
-----------------
Prefect flow that runs the full garmin_guard pipeline:
  1. garmin_sync   — fetch from Garmin Connect API → CSVs
  2. load_duckdb   — reload DuckDB from CSVs
  3. export_bq     — push non-sensitive tables to BigQuery

Scheduled daily at 07:00 Europe/Paris via Prefect Cloud (see prefect.yaml).

Manual run:
    python -c "from src.flows.daily_pipeline import daily_pipeline; daily_pipeline()"
"""

import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PROCESSED = ROOT / "data" / "processed"
ACTIVITIES_CSV = PROCESSED / "activities_normalized.csv"
WELLNESS_CSV = PROCESSED / "wellness_normalized.csv"
PLANNED_WORKOUTS_CSV = PROCESSED / "planned_workouts.csv"


def _credentials() -> tuple[str, str]:
    email = os.environ.get("GARMIN_EMAIL", "")
    password = os.environ.get("GARMIN_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("GARMIN_EMAIL and GARMIN_PASSWORD must be set in environment or .env")
    return email, password


from prefect import flow, task


@task(name="garmin-sync", retries=2, retry_delay_seconds=60, log_prints=True)
def garmin_sync_task() -> None:
    from src.ingestion.garmin_connect_fetch import run_incremental_sync

    email, password = _credentials()
    run_incremental_sync(
        email=email,
        password=password,
        activities_csv=ACTIVITIES_CSV,
        wellness_csv=WELLNESS_CSV,
        planned_workouts_csv=PLANNED_WORKOUTS_CSV,
    )


@task(name="load-duckdb", log_prints=True)
def load_duckdb_task() -> None:
    from src.ingestion.load_duckdb import main

    main()


@task(name="export-bigquery", log_prints=True)
def export_bigquery_task() -> None:
    from src.ingestion.export_bigquery import main

    main()


@flow(name="garmin-daily-pipeline", log_prints=True)
def daily_pipeline() -> None:
    """Full pipeline: Garmin sync → DuckDB reload → BigQuery export."""
    garmin_sync_task()
    load_duckdb_task()
    export_bigquery_task()


if __name__ == "__main__":
    daily_pipeline()
