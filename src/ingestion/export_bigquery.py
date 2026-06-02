"""
export_bigquery.py
------------------
Export non-sensitive tables from local DuckDB to BigQuery.
Sensitive health data (menstrual cycle, HRV, sleep durations, weight, GPS)
is deliberately excluded — GDPR article 9 special-category data.

Usage:
    python src/ingestion/export_bigquery.py
"""

import os
import duckdb
from pathlib import Path

from pandas_gbq import to_gbq

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "garmin_guard.duckdb"

GCP_PROJECT = os.getenv("GCP_PROJECT", "garmin-guard")
DATASET = f"{GCP_PROJECT}.garmin_guard"

# Non-sensitive columns only — no GPS, no device IDs, no raw health signals
ACTIVITIES_COLS = [
    "activity_id", "sport_type", "athlete_date",
    "distance_m", "duration_s", "moving_s", "elapsed_s",
    "avg_speed_ms", "max_speed_ms", "avg_pace_s_km",
    "avg_hr_bpm", "max_hr_bpm", "min_hr_bpm",
    "avg_cadence_spm", "max_cadence_spm", "avg_stride_m",
    "elev_gain_m", "elev_loss_m", "min_elev_m", "max_elev_m",
    "calories", "tss", "aerobic_te", "vo2max",
    "hr_high_zone_pct",
    "hr_zone_0_s", "hr_zone_1_s", "hr_zone_2_s", "hr_zone_3_s",
    "hr_zone_4_s", "hr_zone_5_s", "hr_zone_6_s",
    "lap_count", "moderate_intensity_min", "vigorous_intensity_min",
    "is_pr", "elev_corrected", "source",
    # EXCLUDED: name, location, start_utc, start_local,
    #           start_lat, start_lon, device_id, body_battery_delta, water_ml
]

TRAINING_LOAD_COLS = [
    "athlete_date", "daily_tss", "n_sessions",
    "total_distance_m", "total_duration_s", "avg_hr",
    "atl_7d", "ctl_42d", "tsb", "acwr",
    "has_session", "consecutive_training_days", "load_spike_pct", "acwr_zone",
    # EXCLUDED: body_battery_delta
]

# Wellness: only non-sensitive aggregate signals
WELLNESS_PUBLIC_COLS = [
    "athlete_date", "sleep_score", "rhr_bpm", "vo2max_biometric",
    # EXCLUDED: all menstrual data, sleep durations, HRV, weight, bio_age, bmi
]


def _upload(df, table_id: str) -> None:
    to_gbq(df, table_id, project_id=GCP_PROJECT, if_exists="replace")
    print(f"✓ {table_id}: {len(df)} rows")


def main() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)

    acts = con.execute(f"SELECT {', '.join(ACTIVITIES_COLS)} FROM activities").df()
    _upload(acts, f"garmin_guard.activities")

    load = con.execute(f"SELECT {', '.join(TRAINING_LOAD_COLS)} FROM training_load").df()
    _upload(load, f"garmin_guard.training_load")

    well = con.execute(f"SELECT {', '.join(WELLNESS_PUBLIC_COLS)} FROM wellness").df()
    _upload(well, f"garmin_guard.wellness_public")

    con.close()
    print(f"\nExport complete → BigQuery dataset {DATASET}")


if __name__ == "__main__":
    main()
