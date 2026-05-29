"""
sync_daily.py
-------------
Incremental sync: fetch Strava activities since the last known date,
append to activities_normalized.csv, and regenerate training_load_features.csv.

Usage:
    python src/ingestion/sync_daily.py
"""

import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pandas as pd
from garmin_parser import compute_training_load
from src.ingestion.strava_auth import get_access_token
from src.ingestion.strava_fetch import fetch_activities, to_dataframe

PROCESSED = ROOT / "data" / "processed"
ACTIVITIES_CSV = PROCESSED / "activities_normalized.csv"
LOAD_CSV = PROCESSED / "training_load_features.csv"


def load_existing() -> pd.DataFrame:
    """Load the existing activities CSV, or return an empty DataFrame if absent."""
    if ACTIVITIES_CSV.exists():
        df = pd.read_csv(ACTIVITIES_CSV, parse_dates=["athlete_date", "start_utc"])
        if "source" not in df.columns:
            df["source"] = "garmin"
        return df
    return pd.DataFrame()


def last_strava_date(df: pd.DataFrame):
    """Return the most recent athlete_date that came from Strava, or None."""
    strava = df[df.get("source", pd.Series(dtype=str)) == "strava"] if not df.empty else pd.DataFrame()
    if strava.empty:
        return None
    return strava["athlete_date"].max().to_pydatetime()


def main():
    """Incrementally sync new Strava activities and regenerate both processed CSVs."""
    PROCESSED.mkdir(parents=True, exist_ok=True)

    existing = load_existing()
    after_dt = last_strava_date(existing)
    if after_dt:
        print(f"→ Fetching Strava activities after {after_dt.date()}")
    else:
        print("→ No previous Strava data found — fetching full history")

    token = get_access_token()
    raw = fetch_activities(token, after_dt=after_dt)
    print(f"→ {len(raw)} new activities fetched from Strava")

    if not raw:
        print("Nothing to sync.")
        return

    new_df = to_dataframe(raw)

    if not existing.empty:
        combined = (
            pd.concat([existing, new_df], ignore_index=True)
            .drop_duplicates(subset=["activity_id"])
            .sort_values("athlete_date")
            .reset_index(drop=True)
        )
    else:
        combined = new_df

    combined.to_csv(ACTIVITIES_CSV, index=False)
    print(f"✓ activities_normalized.csv updated — {len(combined)} total rows")

    load_df = compute_training_load(combined, sport_types=("RUNNING",))
    load_df.to_csv(LOAD_CSV, index=False)
    print(f"✓ training_load_features.csv regenerated — {len(load_df)} days")


if __name__ == "__main__":
    main()
