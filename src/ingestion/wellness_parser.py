"""
wellness_parser.py
------------------
Parse Garmin wellness exports (sleep, menstrual cycle, biometrics, fitness age,
HRV) into a single daily DataFrame keyed on athlete_date.

Usage:
    python src/ingestion/wellness_parser.py data/raw/wellness/
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Sleep
# ---------------------------------------------------------------------------

CONFIRMED_TYPES = {"AUTO_CONFIRMED_FINAL", "ENHANCED_CONFIRMED_FINAL"}


def _parse_sleep_file(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    rows = []
    for r in records:
        cal = r.get("calendarDate")
        if not cal:
            continue
        scores = r.get("sleepScores") or {}
        rows.append({
            "athlete_date": pd.to_datetime(cal),
            "sleep_score": scores.get("overallScore"),
            "deep_sleep_s": r.get("deepSleepSeconds"),
            "light_sleep_s": r.get("lightSleepSeconds"),
            "rem_sleep_s": r.get("remSleepSeconds"),
            "awake_s": r.get("awakeSleepSeconds"),
            "avg_respiration": r.get("averageRespiration"),
            "avg_sleep_stress": r.get("avgSleepStress"),
            "sleep_confirmed": r.get("sleepWindowConfirmationType") in CONFIRMED_TYPES,
        })
    return rows


def parse_sleep(wellness_dir: Path) -> pd.DataFrame:
    """Load all sleepData JSON files and return one row per calendar date."""
    rows = []
    for f in sorted(wellness_dir.glob("*_sleepData.json")):
        rows.extend(_parse_sleep_file(f))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).drop_duplicates(subset=["athlete_date"]).sort_values("athlete_date")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Menstrual cycle
# ---------------------------------------------------------------------------

def _cycle_phase(cycle_day: int, period_len: int, fertile_start: int, fertile_len: int) -> str:
    """Return the menstrual phase label for a given day within a cycle."""
    if cycle_day <= period_len:
        return "menstruation"
    if cycle_day < fertile_start:
        return "follicular"
    if cycle_day <= fertile_start + fertile_len:
        return "ovulation"
    return "luteal"


def parse_menstrual(wellness_dir: Path) -> pd.DataFrame:
    """
    Expand MenstrualCycles.json into one row per day with cycle_day, cycle_phase,
    in_fertile_window, and period_active columns.
    """
    cycles_path = next(wellness_dir.glob("*_MenstrualCycles.json"), None)
    if not cycles_path:
        return pd.DataFrame()

    with open(cycles_path, encoding="utf-8") as f:
        cycles = json.load(f)

    rows = []
    for c in cycles:
        start = date.fromisoformat(c["startDate"])
        cycle_len = c.get("actualCycleLength") or c.get("predictedCycleLength") or 28
        period_len = c.get("actualPeriodLength") or c.get("predictedPeriodLength") or 5
        fertile_start = c.get("fertileWindowStart") or 0
        fertile_len = c.get("fertileWindowLength") or 0
        is_pregnant = c.get("cycleType") == "PREGNANT"

        for day_offset in range(int(cycle_len)):
            d = start + timedelta(days=day_offset)
            cycle_day = day_offset + 1

            if is_pregnant:
                phase = "pregnant"
                in_fertile = False
                in_period = False
            else:
                phase = _cycle_phase(cycle_day, period_len, fertile_start, fertile_len)
                in_fertile = fertile_start > 0 and fertile_start <= cycle_day <= fertile_start + fertile_len
                in_period = cycle_day <= period_len

            rows.append({
                "athlete_date": pd.Timestamp(d),
                "cycle_day": cycle_day,
                "cycle_phase": phase,
                "in_fertile_window": in_fertile,
                "period_active": in_period,
            })

    if not rows:
        return pd.DataFrame()

    df = (
        pd.DataFrame(rows)
        .drop_duplicates(subset=["athlete_date"])
        .sort_values("athlete_date")
        .reset_index(drop=True)
    )
    return df


# ---------------------------------------------------------------------------
# Biometrics
# ---------------------------------------------------------------------------

def parse_biometrics(wellness_dir: Path) -> pd.DataFrame:
    """
    Extract daily weight_kg and vo2max_biometric from userBioMetrics.json.
    Snapshots are versioned — keep the last known value per day via forward-fill.
    """
    bio_path = next(wellness_dir.glob("*_userBioMetrics.json"), None)
    if not bio_path:
        return pd.DataFrame()

    with open(bio_path, encoding="utf-8") as f:
        records = json.load(f)

    rows = []
    for r in records:
        meta = r.get("metaData") or {}
        cal_raw = meta.get("calendarDate") or ""
        cal = cal_raw[:10] if cal_raw else None
        if not cal:
            continue

        weight_raw = r.get("weight")
        weight_kg = round(weight_raw["weight"] / 1000, 2) if isinstance(weight_raw, dict) and weight_raw.get("weight") else None
        vo2max = r.get("vo2MaxRunning") or r.get("vo2MaxCycling")

        if weight_kg is not None or vo2max is not None:
            rows.append({
                "athlete_date": pd.to_datetime(cal),
                "weight_kg": weight_kg,
                "vo2max_biometric": vo2max,
            })

    if not rows:
        return pd.DataFrame()

    df = (
        pd.DataFrame(rows)
        .sort_values("athlete_date")
        .groupby("athlete_date")
        .last()
        .reset_index()
    )
    # Forward-fill so every day has the last known measurement
    date_range = pd.date_range(df["athlete_date"].min(), df["athlete_date"].max(), freq="D")
    df = (
        pd.DataFrame({"athlete_date": date_range})
        .merge(df, on="athlete_date", how="left")
        .ffill()
    )
    return df


# ---------------------------------------------------------------------------
# Fitness age
# ---------------------------------------------------------------------------

def parse_fitness_age(wellness_dir: Path) -> pd.DataFrame:
    """Extract daily rhr_bpm, bio_age, and bmi from fitnessAgeData.json."""
    path = next(wellness_dir.glob("*_fitnessAgeData.json"), None)
    if not path:
        return pd.DataFrame()

    with open(path, encoding="utf-8") as f:
        records = json.load(f)

    rows = []
    for r in records:
        ts = r.get("asOfDateGmt") or r.get("createTimestamp") or ""
        cal = ts[:10] if ts else None
        if not cal:
            continue
        rows.append({
            "athlete_date": pd.to_datetime(cal),
            "rhr_bpm": r.get("rhr"),
            "bio_age": r.get("currentBioAge"),
            "bmi": r.get("bmi"),
        })

    if not rows:
        return pd.DataFrame()

    df = (
        pd.DataFrame(rows)
        .drop_duplicates(subset=["athlete_date"])
        .sort_values("athlete_date")
        .reset_index(drop=True)
    )
    return df


# ---------------------------------------------------------------------------
# HRV / Wellness activities
# ---------------------------------------------------------------------------

def parse_hrv(wellness_dir: Path) -> pd.DataFrame:
    """Extract daily hrv_rmssd and hrv_sdrr from wellnessActivities.json."""
    path = next(wellness_dir.glob("*_wellnessActivities.json"), None)
    if not path:
        return pd.DataFrame()

    with open(path, encoding="utf-8") as f:
        records = json.load(f)

    if isinstance(records, dict):
        records = [records]

    rows = []
    for r in records:
        cal = r.get("calendarDate")
        if not cal:
            continue
        summary = {s["summaryType"]: s for s in (r.get("summaryTypeDataList") or [])}
        hrv_rmssd = (summary.get("RMSSD_HRV") or {}).get("avgValue")
        hrv_sdrr = (summary.get("SDRR_HRV") or {}).get("avgValue")
        if hrv_rmssd is not None or hrv_sdrr is not None:
            rows.append({
                "athlete_date": pd.to_datetime(cal),
                "hrv_rmssd": hrv_rmssd,
                "hrv_sdrr": hrv_sdrr,
            })

    if not rows:
        return pd.DataFrame()

    df = (
        pd.DataFrame(rows)
        .drop_duplicates(subset=["athlete_date"])
        .sort_values("athlete_date")
        .reset_index(drop=True)
    )
    return df


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

def load_wellness(wellness_dir: str | Path, output_path: str | Path | None = None) -> pd.DataFrame:
    """
    Parse all Garmin wellness sources and return a merged daily DataFrame.

    Joins sleep, menstrual cycle, biometrics, fitness age, and HRV data on
    athlete_date. Saves to output_path if provided.
    """
    wellness_dir = Path(wellness_dir)

    sleep_df = parse_sleep(wellness_dir)
    menstrual_df = parse_menstrual(wellness_dir)
    bio_df = parse_biometrics(wellness_dir)
    fitness_df = parse_fitness_age(wellness_dir)
    hrv_df = parse_hrv(wellness_dir)

    # Build full date range from all sources
    all_dates = pd.concat([
        df["athlete_date"] for df in [sleep_df, menstrual_df, bio_df, fitness_df, hrv_df]
        if not df.empty
    ])
    date_range = pd.date_range(all_dates.min(), all_dates.max(), freq="D")
    base = pd.DataFrame({"athlete_date": date_range})

    for df in [sleep_df, menstrual_df, bio_df, fitness_df, hrv_df]:
        if not df.empty:
            base = base.merge(df, on="athlete_date", how="left")

    base = base.sort_values("athlete_date").reset_index(drop=True)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        base.to_csv(output_path, index=False)
        print(f"✓ wellness_normalized.csv — {len(base)} jours × {len(base.columns)} colonnes")

    return base


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    wellness_dir = sys.argv[1] if len(sys.argv) > 1 else "data/raw/wellness"
    out = Path(wellness_dir).parent.parent / "processed" / "wellness_normalized.csv"

    df = load_wellness(wellness_dir, output_path=out)

    print(f"\nPériode  : {df['athlete_date'].min().date()} → {df['athlete_date'].max().date()}")
    print(f"Colonnes : {list(df.columns)}\n")

    for col in ["sleep_score", "cycle_phase", "weight_kg", "rhr_bpm", "hrv_rmssd"]:
        if col in df.columns:
            non_null = df[col].notna().sum()
            print(f"  {col:<22} {non_null} jours renseignés")
