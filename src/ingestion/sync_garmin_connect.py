"""
sync_garmin_connect.py
----------------------
CLI wrapper and Prefect flow for garmin_connect_fetch.run_incremental_sync().

Usage:
    python src/ingestion/sync_garmin_connect.py           # incremental from last known date
    python src/ingestion/sync_garmin_connect.py --full    # force backfill from 2026-05-30

Prefect deploy:
    prefect deploy src/ingestion/sync_garmin_connect.py:garmin_connect_daily_sync
"""

import argparse
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

BACKFILL_START = date(2026, 5, 30)


def _credentials() -> tuple[str, str]:
    email = os.environ.get("GARMIN_EMAIL", "")
    password = os.environ.get("GARMIN_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("GARMIN_EMAIL and GARMIN_PASSWORD must be set in environment or .env")
    return email, password


# ---------------------------------------------------------------------------
# Prefect flow
# ---------------------------------------------------------------------------

try:
    from prefect import flow

    @flow(name="garmin_connect_daily_sync")
    def garmin_connect_daily_sync() -> None:
        """Prefect flow: incremental Garmin Connect sync, scheduled daily at 07:00."""
        from src.ingestion.garmin_connect_fetch import run_incremental_sync

        email, password = _credentials()
        run_incremental_sync(
            email=email,
            password=password,
            activities_csv=ACTIVITIES_CSV,
            wellness_csv=WELLNESS_CSV,
            planned_workouts_csv=PLANNED_WORKOUTS_CSV,
        )

except ImportError:
    # prefect not installed — flow unavailable but CLI still works
    def garmin_connect_daily_sync():  # type: ignore[misc]
        raise RuntimeError("prefect is not installed — run: pip install prefect")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Garmin Connect data incrementally.")
    parser.add_argument(
        "--full",
        action="store_true",
        help=f"Force full backfill from {BACKFILL_START} (ignores existing CSV dates)",
    )
    args = parser.parse_args()

    from src.ingestion.garmin_connect_fetch import run_incremental_sync

    email, password = _credentials()
    after = BACKFILL_START if args.full else None
    run_incremental_sync(
        email=email,
        password=password,
        activities_csv=ACTIVITIES_CSV,
        wellness_csv=WELLNESS_CSV,
        planned_workouts_csv=PLANNED_WORKOUTS_CSV,
        after_date=after,
    )


if __name__ == "__main__":
    main()
