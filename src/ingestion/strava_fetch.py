"""
strava_fetch.py
---------------
Fetch Strava activities and normalise them to the same schema as
activities_normalized.csv produced by garmin_parser.py.
"""

import time
import requests
import pandas as pd
from datetime import datetime, timezone


STRAVA_ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"

SPORT_TYPE_MAP = {
    "Run": "RUNNING",
    "Ride": "CYCLING",
    "Walk": "STEPS",
    "WeightTraining": "TRAINING",
    "Workout": "TRAINING",
}


def _fetch_page(access_token: str, after: int | None, page: int) -> list[dict]:
    """Fetch one page of activities from the Strava API."""
    params = {"per_page": 100, "page": page}
    if after:
        params["after"] = after
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(STRAVA_ACTIVITIES_URL, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def fetch_activities(access_token: str, after_dt: datetime | None = None) -> list[dict]:
    """
    Fetch all Strava activities, optionally filtered to those starting after *after_dt*.
    Paginates automatically until the API returns an empty page.
    """
    after_ts = int(after_dt.replace(tzinfo=timezone.utc).timestamp()) if after_dt else None
    all_activities, page = [], 1
    while True:
        batch = _fetch_page(access_token, after_ts, page)
        if not batch:
            break
        all_activities.extend(batch)
        page += 1
        time.sleep(0.5)  # stay under Strava rate limit (600 req/15 min)
    return all_activities


def _pace(speed_ms: float | None) -> float | None:
    """Convert m/s to s/km."""
    if not speed_ms:
        return None
    return round(1000 / speed_ms, 1)


def normalise_activity(a: dict) -> dict:
    """
    Map a raw Strava activity dict to the shared activity schema.
    Fields absent from the Strava summary are set to None.
    """
    latlng = a.get("start_latlng") or []
    sport_raw = a.get("sport_type") or a.get("type", "")
    avg_speed = a.get("average_speed")
    start_utc = datetime.strptime(a["start_date"], "%Y-%m-%dT%H:%M:%SZ") if a.get("start_date") else None
    start_local = datetime.strptime(a["start_date_local"], "%Y-%m-%dT%H:%M:%SZ") if a.get("start_date_local") else None

    return {
        "activity_id": a.get("id"),
        "name": a.get("name"),
        "sport_type": SPORT_TYPE_MAP.get(sport_raw, sport_raw.upper()),
        "location": a.get("location_city"),
        "start_utc": start_utc,
        "start_local": start_local,
        "athlete_date": start_local.date() if start_local else None,
        "distance_m": round(a["distance"], 1) if a.get("distance") else None,
        "duration_s": a.get("elapsed_time"),
        "moving_s": a.get("moving_time"),
        "elapsed_s": a.get("elapsed_time"),
        "avg_speed_ms": round(avg_speed, 4) if avg_speed else None,
        "max_speed_ms": round(a["max_speed"], 4) if a.get("max_speed") else None,
        "avg_pace_s_km": _pace(avg_speed),
        "avg_hr_bpm": a.get("average_heartrate"),
        "max_hr_bpm": a.get("max_heartrate"),
        "min_hr_bpm": None,
        "avg_cadence_spm": a.get("average_cadence"),  # Strava already in steps/min
        "max_cadence_spm": None,
        "avg_stride_m": None,
        "elev_gain_m": a.get("total_elevation_gain"),
        "elev_loss_m": None,
        "min_elev_m": a.get("elev_low"),
        "max_elev_m": a.get("elev_high"),
        "calories": a.get("calories"),
        "tss": None,
        "aerobic_te": None,
        "vo2max": None,
        "body_battery_delta": None,
        "water_ml": None,
        "hr_high_zone_pct": None,
        **{f"hr_zone_{i}_s": None for i in range(7)},
        "lap_count": None,
        "device_id": None,
        "moderate_intensity_min": None,
        "vigorous_intensity_min": None,
        "is_pr": (a.get("pr_count", 0) or 0) > 0,
        "elev_corrected": False,
        "start_lat": latlng[0] if len(latlng) >= 2 else None,
        "start_lon": latlng[1] if len(latlng) >= 2 else None,
        "source": "strava",
    }


def to_dataframe(activities: list[dict]) -> pd.DataFrame:
    """Convert a list of raw Strava activity dicts to a normalised DataFrame."""
    rows = [normalise_activity(a) for a in activities]
    df = pd.DataFrame(rows)
    df["athlete_date"] = pd.to_datetime(df["athlete_date"])
    df["start_utc"] = pd.to_datetime(df["start_utc"])
    return df.sort_values("athlete_date").reset_index(drop=True)
