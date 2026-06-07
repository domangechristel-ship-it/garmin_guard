"""
garmin_connect_fetch.py
-----------------------
Fetch activities and daily wellness data from the Garmin Connect API
and normalise them to the same schema as garmin_parser.py / wellness_parser.py.

Authentication uses GARMIN_EMAIL / GARMIN_PASSWORD env vars; tokens are
cached in .garmin_tokens/ so subsequent runs skip the full login flow.
"""

import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from garminconnect import Garmin

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TOKEN_DIR = ROOT / ".garmin_tokens"

CYCLE_PHASE_MAP = {
    1: "menstruation",
    2: "follicular",
    3: "ovulation",
    4: "luteal",
    5: "pregnant",
}

ACTIVITY_TYPE_MAP = {
    "running": "RUNNING",
    "cycling": "CYCLING",
    "mountain_biking": "CYCLING",
    "walking": "STEPS",
    "hiking": "HIKING",
    "swimming": "SWIMMING",
    "strength_training": "STRENGTH_TRAINING",
    "yoga": "YOGA",
    "cardio_training": "TRAINING",
    "fitness_equipment": "TRAINING",
    "other": "OTHER",
}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def get_client(email: str, password: str) -> Garmin:
    """Authenticate and return a Garmin Connect client with token cache."""
    TOKEN_DIR.mkdir(exist_ok=True)
    client = Garmin(email, password)
    client.login(tokenstore=str(TOKEN_DIR))
    print(f"→ Authentifié sur Garmin Connect (tokens dans {TOKEN_DIR})")
    return client


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------

def _pace(speed_ms: float | None) -> float | None:
    if not speed_ms:
        return None
    return round(1000 / speed_ms, 1)


def _normalise_activity(a: dict) -> dict:
    atype = (a.get("activityType") or {}).get("typeKey", "")
    sport_type = ACTIVITY_TYPE_MAP.get(atype, atype.upper())

    start_utc = None
    start_local = None
    gmt_str = a.get("startTimeGMT")
    local_str = a.get("startTimeLocal")
    if gmt_str:
        try:
            start_utc = datetime.strptime(gmt_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    if local_str:
        try:
            start_local = datetime.strptime(local_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    avg_speed = a.get("averageSpeed")

    zones = [a.get(f"hrTimeInZone_{i}") for i in range(1, 6)]
    zone_total = sum(z for z in zones if z)
    hr_high = None
    if zone_total:
        high_s = sum(z for z in zones[2:] if z)  # zones 3,4,5 = index 2,3,4
        hr_high = round(high_s / zone_total * 100, 1)

    return {
        "activity_id": a.get("activityId"),
        "name": a.get("activityName"),
        "sport_type": sport_type,
        "location": a.get("locationName"),
        "start_utc": start_utc,
        "start_local": start_local,
        "athlete_date": start_local.date() if start_local else None,
        "distance_m": round(a["distance"], 1) if a.get("distance") else None,
        "duration_s": round(a["duration"], 1) if a.get("duration") else None,
        "moving_s": round(a["movingDuration"], 1) if a.get("movingDuration") else None,
        "elapsed_s": round(a["elapsedDuration"], 1) if a.get("elapsedDuration") else None,
        "avg_speed_ms": round(avg_speed, 4) if avg_speed else None,
        "max_speed_ms": round(a["maxSpeed"], 4) if a.get("maxSpeed") else None,
        "avg_pace_s_km": _pace(avg_speed),
        "avg_hr_bpm": a.get("averageHR"),
        "max_hr_bpm": a.get("maxHR"),
        "min_hr_bpm": None,
        "avg_cadence_spm": a.get("averageRunningCadenceInStepsPerMinute") or a.get("averageCadence"),
        "max_cadence_spm": a.get("maxRunningCadenceInStepsPerMinute"),
        "avg_stride_m": round(a["avgStrideLength"], 2) if a.get("avgStrideLength") else None,
        "elev_gain_m": a.get("elevationGain"),
        "elev_loss_m": a.get("elevationLoss"),
        "min_elev_m": a.get("minElevation"),
        "max_elev_m": a.get("maxElevation"),
        "calories": a.get("calories"),
        "tss": a.get("trainingStressScore"),
        "aerobic_te": a.get("aerobicTrainingEffect"),
        "vo2max": a.get("vO2MaxValue"),
        "body_battery_delta": a.get("bodyBatteryDrainedDuringActivity"),
        "water_ml": None,
        "hr_high_zone_pct": hr_high,
        "hr_zone_0_s": None,
        "hr_zone_1_s": a.get("hrTimeInZone_1"),
        "hr_zone_2_s": a.get("hrTimeInZone_2"),
        "hr_zone_3_s": a.get("hrTimeInZone_3"),
        "hr_zone_4_s": a.get("hrTimeInZone_4"),
        "hr_zone_5_s": a.get("hrTimeInZone_5"),
        "hr_zone_6_s": None,
        "lap_count": a.get("lapCount"),
        "device_id": a.get("deviceId"),
        "moderate_intensity_min": a.get("moderateIntensityMinutes"),
        "vigorous_intensity_min": a.get("vigorousIntensityMinutes"),
        "is_pr": bool(a.get("pr")),
        "elev_corrected": bool(a.get("elevationCorrected")),
        "start_lat": a.get("startLatitude"),
        "start_lon": a.get("startLongitude"),
        "source": "garmin_connect",
    }


def fetch_activities(client: Garmin, after_date: date | None = None) -> pd.DataFrame:
    """Fetch activities from Garmin Connect and return an activities_normalized DataFrame."""
    start_str = after_date.isoformat() if after_date else "2000-01-01"
    end_str = date.today().isoformat()
    raw = client.get_activities_by_date(start_str, end_str)
    print(f"→ {len(raw)} activités fetched depuis {start_str}")
    if not raw:
        return pd.DataFrame(columns=list(_normalise_activity({}).keys()))
    rows = [_normalise_activity(a) for a in raw]
    df = pd.DataFrame(rows)
    df["athlete_date"] = pd.to_datetime(df["athlete_date"])
    df["start_utc"] = pd.to_datetime(df["start_utc"])
    df["start_local"] = pd.to_datetime(df["start_local"])
    return df.sort_values("athlete_date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Wellness
# ---------------------------------------------------------------------------

def _parse_wellness_day(date_str: str, hr_data: dict, hrv_data: dict, sleep_data: dict, menstrual_data: dict) -> dict:
    row: dict = {
        "athlete_date": date_str,
        "sleep_score": None,
        "deep_sleep_s": None,
        "light_sleep_s": None,
        "rem_sleep_s": None,
        "awake_s": None,
        "avg_respiration": None,
        "avg_sleep_stress": None,
        "sleep_confirmed": None,
        "cycle_day": None,
        "cycle_phase": None,
        "in_fertile_window": None,
        "period_active": None,
        "symptoms": None,
        "moods": None,
        "weight_kg": None,
        "vo2max_biometric": None,
        "rhr_bpm": None,
        "bio_age": None,
        "bmi": None,
        "hrv_rmssd": None,
        "hrv_sdrr": None,
    }

    # RHR
    if isinstance(hr_data, dict):
        row["rhr_bpm"] = hr_data.get("restingHeartRate")

    # HRV
    if isinstance(hrv_data, dict):
        summary = hrv_data.get("hrvSummary") or {}
        row["hrv_rmssd"] = summary.get("rmssd")
        row["hrv_sdrr"] = summary.get("sdrr")

    # Sleep
    if isinstance(sleep_data, dict):
        dto = sleep_data.get("dailySleepDTO") or {}
        scores = dto.get("sleepScores") or {}
        overall = scores.get("overall") or {}
        row["sleep_score"] = overall.get("value")
        row["deep_sleep_s"] = dto.get("deepSleepSeconds")
        row["light_sleep_s"] = dto.get("lightSleepSeconds")
        row["rem_sleep_s"] = dto.get("remSleepSeconds")
        row["awake_s"] = dto.get("awakeSleepSeconds")
        row["avg_respiration"] = dto.get("averageRespirationValue")
        row["avg_sleep_stress"] = dto.get("avgSleepStress")
        row["sleep_confirmed"] = bool(dto.get("sleepWindowConfirmed", False))

    # Menstrual cycle
    if isinstance(menstrual_data, dict):
        summary = menstrual_data.get("daySummary") or {}
        if summary:
            day = summary.get("dayInCycle")
            row["cycle_day"] = day
            row["cycle_phase"] = CYCLE_PHASE_MAP.get(summary.get("currentPhase"))
            period_len = summary.get("periodLength") or 0
            row["period_active"] = bool(day and day <= period_len)
            fw_start = summary.get("fertileWindowStart") or 0
            fw_len = summary.get("lengthOfFertileWindow") or 0
            row["in_fertile_window"] = bool(day and fw_start <= day < fw_start + fw_len)
        day_log = menstrual_data.get("dayLog") or {}
        if day_log:
            syms = day_log.get("symptoms") or []
            row["symptoms"] = ",".join(syms) if syms else None
            moods = day_log.get("moods") or []
            row["moods"] = ",".join(moods) if moods else None

    return row


def fetch_wellness(client: Garmin, start_date: date, end_date: date) -> pd.DataFrame:
    """Fetch daily wellness data (sleep, HRV, RHR) and return a wellness_normalized DataFrame."""
    rows = []
    current = start_date
    delta = timedelta(days=1)
    total = (end_date - start_date).days + 1
    print(f"→ Fetch wellness {start_date} → {end_date} ({total} jours)")

    while current <= end_date:
        date_str = current.isoformat()
        hr_data, hrv_data, sleep_data, menstrual_data = {}, {}, {}, {}

        try:
            hr_data = client.get_heart_rates(date_str) or {}
        except Exception as e:
            print(f"  ⚠ heart_rates {date_str}: {e}")

        try:
            hrv_data = client.get_hrv_data(date_str) or {}
        except Exception as e:
            print(f"  ⚠ hrv_data {date_str}: {e}")

        try:
            sleep_data = client.get_sleep_data(date_str) or {}
        except Exception as e:
            print(f"  ⚠ sleep_data {date_str}: {e}")

        try:
            menstrual_data = client.get_menstrual_data_for_date(date_str) or {}
        except Exception as e:
            print(f"  ⚠ menstrual_data {date_str}: {e}")

        rows.append(_parse_wellness_day(date_str, hr_data, hrv_data, sleep_data, menstrual_data))
        current += delta
        time.sleep(0.5)

    df = pd.DataFrame(rows)
    df["athlete_date"] = pd.to_datetime(df["athlete_date"])
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Self-evaluations
# ---------------------------------------------------------------------------

def fetch_self_evals(client: Garmin, activity_ids: list[int]) -> pd.DataFrame:
    """Fetch post-activity self-evaluations (perceived_effort, perceived_recovery).

    Returns an empty DataFrame if the endpoint is unavailable.
    """
    cols = ["activity_id", "athlete_date", "perceived_effort", "perceived_recovery", "notes"]
    rows = []
    for aid in activity_ids:
        try:
            data = client.get_activity_evaluation(aid) or {}
            rows.append({
                "activity_id": aid,
                "athlete_date": data.get("calendarDate"),
                "perceived_effort": data.get("perceivedEffort") or data.get("userPerceivedEffort"),
                "perceived_recovery": data.get("perceivedRecovery") or data.get("userPerceivedRecovery"),
                "notes": data.get("comment") or data.get("notes"),
            })
        except Exception as e:
            print(f"  ⚠ self-eval non disponible pour activité {aid}: {e}")
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Incremental sync
# ---------------------------------------------------------------------------

def run_incremental_sync(
    email: str,
    password: str,
    activities_csv: Path,
    wellness_csv: Path,
    after_date: date | None = None,
) -> None:
    """Orchestrate full incremental sync: fetch → merge → save both CSVs."""
    client = get_client(email, password)
    today = date.today()

    # --- Determine after_date ---
    if after_date is None:
        after_date = date(2026, 5, 30)  # default backfill start
        if activities_csv.exists():
            existing_acts = pd.read_csv(activities_csv, parse_dates=["athlete_date"])
            if "source" in existing_acts.columns:
                gc_rows = existing_acts[existing_acts["source"] == "garmin_connect"]
                if not gc_rows.empty:
                    last_dt = gc_rows["athlete_date"].max()
                    after_date = last_dt.date() + timedelta(days=1)

    if after_date > today:
        print("→ Rien à synchroniser (after_date > aujourd'hui)")
        _print_summary(0, 0, 0, 0, 0)
        return

    print(f"→ Sync depuis {after_date} jusqu'à {today}")

    # --- Fetch ---
    new_acts = fetch_activities(client, after_date=after_date)
    new_wellness = fetch_wellness(client, after_date, today)

    activity_ids = new_acts["activity_id"].dropna().astype(int).tolist() if not new_acts.empty else []
    new_evals = fetch_self_evals(client, activity_ids)

    # --- Merge activities ---
    n_new_acts = 0
    total_acts = 0
    if not new_acts.empty:
        if activities_csv.exists():
            existing = pd.read_csv(activities_csv, parse_dates=["athlete_date", "start_utc", "start_local"])
            if "source" not in existing.columns:
                existing["source"] = "garmin"
            combined = (
                pd.concat([existing, new_acts], ignore_index=True)
                .drop_duplicates(subset=["activity_id"])
                .sort_values("athlete_date")
                .reset_index(drop=True)
            )
            n_new_acts = len(combined) - len(existing)
        else:
            activities_csv.parent.mkdir(parents=True, exist_ok=True)
            combined = new_acts
            n_new_acts = len(combined)
        combined.to_csv(activities_csv, index=False)
        total_acts = len(combined)
    elif activities_csv.exists():
        total_acts = len(pd.read_csv(activities_csv))

    # --- Merge wellness ---
    n_wellness = len(new_wellness)
    if not new_wellness.empty:
        if wellness_csv.exists():
            existing_w = pd.read_csv(wellness_csv, parse_dates=["athlete_date"])
            combined_w = (
                pd.concat([existing_w, new_wellness], ignore_index=True)
                .drop_duplicates(subset=["athlete_date"], keep="last")
                .sort_values("athlete_date")
                .reset_index(drop=True)
            )
        else:
            wellness_csv.parent.mkdir(parents=True, exist_ok=True)
            combined_w = new_wellness
        combined_w.to_csv(wellness_csv, index=False)

    # --- Régénère training_load_features.csv ---
    load_csv = activities_csv.parent / "training_load_features.csv"
    final_acts = pd.read_csv(activities_csv, parse_dates=["athlete_date"]) if activities_csv.exists() else combined
    from ingestion.garmin_parser import compute_training_load
    load_df = compute_training_load(final_acts, sport_types=("RUNNING",))
    load_df.to_csv(load_csv, index=False)
    print(f"✓ training_load_features.csv régénéré — {len(load_df)} jours")

    _print_summary(n_new_acts, total_acts, n_wellness, len(new_evals))


def _print_summary(n_new_acts: int, total_acts: int, n_wellness: int, n_evals: int) -> None:
    print(f"\n✓ Activités  : {n_new_acts} nouvelles ajoutées (total : {total_acts})")
    print(f"✓ Wellness   : {n_wellness} jours mis à jour")
    print(f"✓ Self-evals : {n_evals} évaluations fetched")
