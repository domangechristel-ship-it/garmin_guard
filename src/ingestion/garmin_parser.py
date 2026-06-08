"""
garmin_parser.py
----------------
Parse l'export JSON Garmin (summarizedActivities) vers un DataFrame
normalisé, prêt pour insertion en base ou feature engineering.

263 activités · 2023-04-02 → 2025-11-13
Sports : RUNNING (167), TRAINING (50), STEPS (26), CYCLING (11)...

Conversions d'unités Garmin :
  distance      : centimètres → mètres  (/ 100)
  duration      : millisecondes → secondes (/ 1000)
  elevation     : centimètres → mètres (/ 100)
  avgSpeed      : cm/ms → vitesse recalculée depuis distance_m / moving_s
  maxSpeed      : cm/ms → m/s (/ 100)
  timestamp     : epoch ms → datetime UTC
  strideLength  : centimètres → mètres (/ 100)
  hrTimeInZone  : millisecondes → secondes (/ 1000)
"""

import json
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path


CM_TO_M = 1 / 100
MS_TO_S = 1 / 1000


def parse_timestamp(ts_ms):
    """Convert a Garmin millisecond epoch timestamp to a UTC datetime. Returns None if the value is missing."""
    if ts_ms is None:
        return None
    return datetime.utcfromtimestamp(float(ts_ms) / 1000)


def pace_s_per_km(speed_m_per_s):
    """Convert a speed in m/s to a pace in seconds per kilometre. Returns None if speed is zero or missing."""
    if not speed_m_per_s or speed_m_per_s == 0:
        return None
    return round(1000 / speed_m_per_s, 1)


def parse_activity(a):
    """
    Parse a single raw Garmin activity dict and return a normalised flat row.

    Applies all unit conversions (cm→m, ms→s, double cadence→spm) and computes
    derived metrics: avg_speed, pace, hr_high_zone_pct, and hr_zone_*_s columns.
    """
    raw_dist = a.get("distance")       # centimètres
    raw_dur = a.get("duration")        # millisecondes
    raw_moving = a.get("movingDuration")
    raw_elapsed = a.get("elapsedDuration")

    distance_m = round(raw_dist * CM_TO_M, 1) if raw_dist else None
    duration_s = round(raw_dur * MS_TO_S, 1) if raw_dur else None
    moving_s = round(raw_moving * MS_TO_S, 1) if raw_moving else None
    elapsed_s = round(raw_elapsed * MS_TO_S, 1) if raw_elapsed else None

    # Vitesse recalculée depuis distance / moving duration (plus fiable que avgSpeed)
    if distance_m and moving_s and moving_s > 0:
        avg_speed = round(distance_m / moving_s, 4)
    else:
        avg_speed = None

    # maxSpeed : cm/ms → m/s
    raw_max_speed = a.get("maxSpeed")
    max_speed = round(raw_max_speed / 100, 4) if raw_max_speed else None

    # Élévation : cm → m
    elev_gain = round(a.get("elevationGain", 0) * CM_TO_M, 1)
    elev_loss = round(a.get("elevationLoss", 0) * CM_TO_M, 1)
    min_elev = round(a.get("minElevation", 0) * CM_TO_M, 1) if a.get("minElevation") else None
    max_elev = round(a.get("maxElevation", 0) * CM_TO_M, 1) if a.get("maxElevation") else None

    # Stride length : cm → m
    stride_m = round(a.get("avgStrideLength", 0) * CM_TO_M, 3) if a.get("avgStrideLength") else None

    # Timestamps
    start_utc = parse_timestamp(a.get("beginTimestamp"))
    start_local = parse_timestamp(a.get("startTimeLocal"))

    # Cadence : avgDoubleCadence = pas/min doubles → diviser par 2
    cadence_raw = a.get("avgDoubleCadence")
    cadence_spm = round(cadence_raw / 2, 1) if cadence_raw else None
    max_cad_raw = a.get("maxDoubleCadence")
    max_cadence_spm = round(max_cad_raw / 2) if max_cad_raw else None

    # Zones FC (ms → s)
    hr_zones = {
        f"hr_zone_{i}_s": round(a.get(f"hrTimeInZone_{i}", 0) * MS_TO_S)
        for i in range(7)
    }
    total_hr_s = sum(hr_zones.values())
    if total_hr_s > 0:
        high_s = hr_zones.get("hr_zone_3_s", 0) + hr_zones.get("hr_zone_4_s", 0) + hr_zones.get("hr_zone_5_s", 0)
        hr_high_pct = round(high_s / total_hr_s * 100, 1)
    else:
        hr_high_pct = None

    row = {
        "activity_id": a.get("activityId"),
        "name": a.get("name"),
        "sport_type": a.get("sportType"),
        "location": a.get("locationName"),
        "start_utc": start_utc,
        "start_local": start_local,
        "athlete_date": start_local.date() if start_local else None,
        "distance_m": distance_m,
        "duration_s": duration_s,
        "moving_s": moving_s,
        "elapsed_s": elapsed_s,
        "avg_speed_ms": avg_speed,
        "max_speed_ms": max_speed,
        "avg_pace_s_km": pace_s_per_km(avg_speed),
        "avg_hr_bpm": a.get("avgHr"),
        "max_hr_bpm": a.get("maxHr"),
        "min_hr_bpm": a.get("minHr"),
        "avg_cadence_spm": cadence_spm,
        "max_cadence_spm": max_cadence_spm,
        "avg_stride_m": stride_m,
        "elev_gain_m": elev_gain,
        "elev_loss_m": elev_loss,
        "min_elev_m": min_elev,
        "max_elev_m": max_elev,
        "calories": round(a.get("calories", 0), 1) if a.get("calories") else None,
        "tss": a.get("trainingStressScore"),
        "aerobic_te": a.get("aerobicTrainingEffect"),
        "vo2max": a.get("vO2MaxValue"),
        "body_battery_delta": a.get("differenceBodyBattery"),
        "water_ml": a.get("waterEstimated"),
        "hr_high_zone_pct": hr_high_pct,
        **hr_zones,
        "lap_count": a.get("lapCount"),
        "device_id": a.get("deviceId"),
        "moderate_intensity_min": a.get("moderateIntensityMinutes"),
        "vigorous_intensity_min": a.get("vigorousIntensityMinutes"),
        "is_pr": a.get("pr", False),
        "elev_corrected": a.get("elevationCorrected", False),
        "start_lat": a.get("startLatitude"),
        "start_lon": a.get("startLongitude"),
        "source": "garmin",
    }
    return row


def load_garmin_export(filepath):
    """
    Load a Garmin summarizedActivities JSON export and return a normalised DataFrame.

    Reads the file at *filepath*, parses every activity via parse_activity, and
    coerces date/numeric columns before sorting chronologically by athlete_date.
    """
    with open(filepath, encoding="utf-8") as f:
        raw = json.load(f)
    activities_raw = raw[0]["summarizedActivitiesExport"]
    print(f"→ {len(activities_raw)} activités trouvées dans l'export")
    rows = [parse_activity(a) for a in activities_raw]
    df = pd.DataFrame(rows)
    df["athlete_date"] = pd.to_datetime(df["athlete_date"])
    df["start_utc"] = pd.to_datetime(df["start_utc"])
    df["body_battery_delta"] = pd.to_numeric(df["body_battery_delta"], errors="coerce")
    df = df.sort_values("athlete_date").reset_index(drop=True)
    return df


def compute_training_load(df, sport_types=("RUNNING",)):
    """
    Compute daily training load metrics for the given sport types.

    ATL  = Acute Training Load   → 7-day EWM
    CTL  = Chronic Training Load → 42-day EWM
    TSB  = CTL - ATL  (positive = fresh, negative = fatigued)
    ACWR = ATL / CTL  (>1.5 = injury risk zone)

    A TSS (Training Stress Score) proxy is used when the raw TSS field is absent: duration_s × avg_hr / 3600 / 10.
    Returns a daily DataFrame with ATL, CTL, TSB, ACWR, consecutive training days,
    weekly load spike percentage, and an ACWR zone label.
    """
    df_sport = df[df["sport_type"].isin(sport_types)].copy()

    # Proxy TSS si absent : duration_s × avg_hr / 3600 / 10
    df_sport["tss_proxy"] = df_sport["tss"].fillna(
        df_sport["duration_s"] * df_sport["avg_hr_bpm"] / 3600 / 10
    )

    daily = (
        df_sport.groupby("athlete_date")
        .agg(
            daily_tss=("tss_proxy", "sum"),
            n_sessions=("activity_id", "count"),
            total_distance_m=("distance_m", "sum"),
            total_duration_s=("duration_s", "sum"),
            avg_hr=("avg_hr_bpm", "mean"),
            body_battery_delta=("body_battery_delta", "sum"),
        )
        .reset_index()
    )

    end_date = max(daily["athlete_date"].max(), pd.Timestamp.today().normalize())
    date_range = pd.date_range(daily["athlete_date"].min(), end_date, freq="D")
    daily = (
        pd.DataFrame({"athlete_date": date_range})
        .merge(daily, on="athlete_date", how="left")
        .fillna({"daily_tss": 0, "n_sessions": 0, "total_distance_m": 0, "total_duration_s": 0})
    )

    daily["atl_7d"] = daily["daily_tss"].ewm(span=7, adjust=False).mean().round(2)
    daily["ctl_42d"] = daily["daily_tss"].ewm(span=42, adjust=False).mean().round(2)
    daily["tsb"] = (daily["ctl_42d"] - daily["atl_7d"]).round(2)
    daily["acwr"] = (daily["atl_7d"] / daily["ctl_42d"].replace(0, np.nan)).round(3)

    daily["has_session"] = (daily["n_sessions"] > 0).astype(int)
    groups = (daily["has_session"] == 0).cumsum()
    daily["consecutive_training_days"] = daily.groupby(groups)["has_session"].cumsum()

    weekly_load = daily["daily_tss"].rolling(7, min_periods=1).sum()
    prev_weekly = weekly_load.shift(7)
    daily["load_spike_pct"] = ((weekly_load / prev_weekly.replace(0, np.nan) - 1) * 100).round(1)

    daily["acwr_zone"] = pd.cut(
        daily["acwr"],
        bins=[0, 0.8, 1.3, 1.5, 99],
        labels=["sous-charge", "optimal", "attention", "risque"],
    )

    return daily


def parse_gear(di_connect_dir: Path) -> pd.DataFrame:
    """
    Parse gear.json and return a DataFrame mapping each activity_id to its shoe.

    Columns: activity_id, gear_name, gear_retired, gear_max_km.
    """
    fitness_dir = Path(di_connect_dir) / "DI-Connect-Fitness"
    gear_path = next(fitness_dir.glob("*_gear.json"), None)
    if not gear_path:
        return pd.DataFrame()

    with open(gear_path, encoding="utf-8") as f:
        raw = json.load(f)

    data = raw[0] if isinstance(raw, list) else raw

    gear_info = {}
    for g in data.get("gearDTOS", []):
        gear_info[g["gearPk"]] = {
            "gear_name": g.get("customMakeModel") or g.get("displayName") or "Unknown",
            "gear_retired": g.get("gearStatusName") == "retired",
            "gear_max_km": round(g["maximumMeters"] / 1000, 1) if g.get("maximumMeters") else None,
        }

    rows = []
    for gear_pk_str, activities in data.get("gearActivityDTOs", {}).items():
        info = gear_info.get(int(gear_pk_str), {})
        for act in activities:
            rows.append({"activity_id": act["activityId"], **info})

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("activity_id").reset_index(drop=True)


def parse_coach_pauses(di_connect_dir: Path) -> pd.DataFrame:
    """
    Parse Garmin_Coach_Pause_History.json and return training pause intervals.

    Columns: pause_start (UTC datetime), pause_end (UTC datetime or NaT), pause_reason.
    """
    pauses_path = Path(di_connect_dir) / "DI-ATP" / "Garmin_Coach_Pause_History.json"
    if not pauses_path.exists():
        return pd.DataFrame()

    with open(pauses_path, encoding="utf-8") as f:
        records = json.load(f)

    rows = [
        {
            "pause_start": parse_timestamp(r.get("pauseStartDate")),
            "pause_end": parse_timestamp(r.get("pauseEndDate")),
            "pause_reason": r.get("pauseReason"),
        }
        for r in records
    ]
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import sys
    ROOT = Path(__file__).resolve().parents[2]
    filepath = sys.argv[1] if len(sys.argv) > 1 else str(
        ROOT / "data/raw/DI_CONNECT/DI-Connect-Fitness/christel_d@live.fr_0_summarizedActivities.json"
    )

    df = load_garmin_export(filepath)
    print(f"\nDataFrame : {df.shape[0]} lignes × {df.shape[1]} colonnes")
    print(f"Période   : {df['athlete_date'].min().date()} → {df['athlete_date'].max().date()}")
    print(f"\nRépartition :\n{df['sport_type'].value_counts().to_string()}")

    running = df[df["sport_type"] == "RUNNING"].copy()
    print(f"\n─── Running ({len(running)} séances) ───")
    print(f"Distance totale   : {running['distance_m'].sum()/1000:.0f} km")
    print(f"D+ total          : {running['elev_gain_m'].sum():.0f} m")
    print(f"FC moy            : {running['avg_hr_bpm'].mean():.0f} bpm")
    print(f"Allure moy        : {running['avg_pace_s_km'].mean()/60:.1f} min/km")
    print(f"Body battery Δ    : {running['body_battery_delta'].mean():.1f} pts/séance")
    print(f"VO2max moyen      : {running['vo2max'].mean():.1f}")

    load_df = compute_training_load(df, sport_types=("RUNNING",))
    print(f"\n─── ATL/CTL/ACWR — 14 derniers jours ───")
    print(load_df[["athlete_date","daily_tss","atl_7d","ctl_42d","tsb","acwr","acwr_zone"]].tail(14).to_string(index=False))

    out_dir = ROOT / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "activities_normalized.csv", index=False)
    load_df.to_csv(out_dir / "training_load_features.csv", index=False)
    print(f"\n✓ Exporté : {out_dir}/activities_normalized.csv  |  {out_dir}/training_load_features.csv")
