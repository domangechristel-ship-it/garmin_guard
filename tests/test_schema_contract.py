"""
Schema contract tests: verify that garmin_connect_fetch produces DataFrames
with columns identical to the reference headers of activities_normalized.csv
and wellness_normalized.csv.

These tests run without real credentials — the Garmin client is mocked.
"""

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.ingestion.garmin_connect_fetch import fetch_activities, fetch_wellness

# ---------------------------------------------------------------------------
# Reference column snapshots (taken from data/processed/*.csv headers)
# ---------------------------------------------------------------------------

ACTIVITIES_COLUMNS = [
    "activity_id", "name", "sport_type", "location",
    "start_utc", "start_local", "athlete_date",
    "distance_m", "duration_s", "moving_s", "elapsed_s",
    "avg_speed_ms", "max_speed_ms", "avg_pace_s_km",
    "avg_hr_bpm", "max_hr_bpm", "min_hr_bpm",
    "avg_cadence_spm", "max_cadence_spm", "avg_stride_m",
    "elev_gain_m", "elev_loss_m", "min_elev_m", "max_elev_m",
    "calories", "tss", "aerobic_te", "vo2max", "body_battery_delta", "water_ml",
    "hr_high_zone_pct",
    "hr_zone_0_s", "hr_zone_1_s", "hr_zone_2_s", "hr_zone_3_s",
    "hr_zone_4_s", "hr_zone_5_s", "hr_zone_6_s",
    "lap_count", "device_id", "moderate_intensity_min", "vigorous_intensity_min",
    "is_pr", "elev_corrected", "start_lat", "start_lon", "source",
]

WELLNESS_COLUMNS = [
    "athlete_date", "sleep_score", "deep_sleep_s", "light_sleep_s", "rem_sleep_s",
    "awake_s", "avg_respiration", "avg_sleep_stress", "sleep_confirmed",
    "cycle_day", "cycle_phase", "in_fertile_window", "period_active",
    "symptoms", "moods", "weight_kg", "vo2max_biometric",
    "rhr_bpm", "bio_age", "bmi", "hrv_rmssd", "hrv_sdrr",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_ACTIVITY = {
    "activityId": 1234567890,
    "activityName": "Morning Run",
    "activityType": {"typeKey": "running"},
    "startTimeGMT": "2026-05-30 05:00:00",
    "startTimeLocal": "2026-05-30 07:00:00",
    "distance": 10000.0,
    "duration": 3600.0,
    "movingDuration": 3540.0,
    "elapsedDuration": 3600.0,
    "averageSpeed": 2.78,
    "maxSpeed": 3.5,
    "averageHR": 155,
    "maxHR": 175,
    "calories": 550,
}

_MINIMAL_HR = {"restingHeartRate": 52}

_MINIMAL_HRV = {"hrvSummary": {"rmssd": 42.0, "sdrr": 25.1}}

_MINIMAL_SLEEP = {
    "dailySleepDTO": {
        "sleepScores": {"overall": {"value": 78}},
        "deepSleepSeconds": 4200,
        "lightSleepSeconds": 12600,
        "remSleepSeconds": 6000,
        "awakeSleepSeconds": 1800,
        "averageRespiration": 14.5,
        "averageStress": 27.0,
        "validation": "ENHANCED_CONFIRMED_FINAL",
    }
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_activities_schema_column_names():
    """fetch_activities returns a DataFrame with exactly the canonical column set."""
    mock_client = MagicMock()
    mock_client.get_activities_by_date.return_value = [_MINIMAL_ACTIVITY]

    df = fetch_activities(mock_client, after_date=date(2026, 5, 30))

    assert list(df.columns) == ACTIVITIES_COLUMNS, (
        f"Column mismatch.\nExpected: {ACTIVITIES_COLUMNS}\nGot:      {list(df.columns)}"
    )


def test_activities_schema_empty_client():
    """fetch_activities returns the correct column set even when the API returns no data."""
    mock_client = MagicMock()
    mock_client.get_activities_by_date.return_value = []

    df = fetch_activities(mock_client, after_date=date(2026, 5, 30))

    assert list(df.columns) == ACTIVITIES_COLUMNS
    assert len(df) == 0


def test_activities_source_is_garmin_connect():
    """All rows produced by fetch_activities carry source='garmin_connect'."""
    mock_client = MagicMock()
    mock_client.get_activities_by_date.return_value = [_MINIMAL_ACTIVITY]

    df = fetch_activities(mock_client, after_date=date(2026, 5, 30))

    assert (df["source"] == "garmin_connect").all()


def test_wellness_schema_column_names():
    """fetch_wellness returns a DataFrame with exactly the canonical column set."""
    mock_client = MagicMock()
    mock_client.get_heart_rates.return_value = _MINIMAL_HR
    mock_client.get_hrv_data.return_value = _MINIMAL_HRV
    mock_client.get_sleep_data.return_value = _MINIMAL_SLEEP

    df = fetch_wellness(mock_client, date(2026, 5, 30), date(2026, 5, 30))

    assert list(df.columns) == WELLNESS_COLUMNS, (
        f"Column mismatch.\nExpected: {WELLNESS_COLUMNS}\nGot:      {list(df.columns)}"
    )


def test_wellness_one_row_per_day():
    """fetch_wellness produces exactly one row per requested day."""
    mock_client = MagicMock()
    mock_client.get_heart_rates.return_value = _MINIMAL_HR
    mock_client.get_hrv_data.return_value = _MINIMAL_HRV
    mock_client.get_sleep_data.return_value = _MINIMAL_SLEEP

    df = fetch_wellness(mock_client, date(2026, 5, 30), date(2026, 6, 1))

    assert len(df) == 3


def test_wellness_graceful_on_api_error():
    """fetch_wellness fills None values when an endpoint raises an exception."""
    mock_client = MagicMock()
    mock_client.get_heart_rates.side_effect = Exception("404 not found")
    mock_client.get_hrv_data.side_effect = Exception("404 not found")
    mock_client.get_sleep_data.side_effect = Exception("404 not found")

    df = fetch_wellness(mock_client, date(2026, 5, 30), date(2026, 5, 30))

    assert list(df.columns) == WELLNESS_COLUMNS
    assert len(df) == 1
    assert pd.isna(df.loc[0, "rhr_bpm"])
    assert pd.isna(df.loc[0, "hrv_rmssd"])
    assert pd.isna(df.loc[0, "sleep_score"])
