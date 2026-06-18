from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel


class SessionType(str, Enum):
    RECOVERY = "RECOVERY"
    SHORT_RUN = "SHORT_RUN"
    TEMPO = "TEMPO"
    INTERVAL = "INTERVAL"
    LONG_RUN = "LONG_RUN"


class CyclePhase(str, Enum):
    MENSTRUAL = "MENSTRUAL"
    FOLLICULAR = "FOLLICULAR"
    OVULATION = "OVULATION"
    LUTEAL_EARLY = "LUTEAL_EARLY"
    LUTEAL_LATE = "LUTEAL_LATE"


class BlockType(str, Enum):
    BUILD = "BUILD"
    RECOVERY = "RECOVERY"
    TAPER = "TAPER"


class TrainingSession(BaseModel):
    date: date
    session_type: SessionType
    duration_min: int
    tss_target: float
    cycle_phase: CyclePhase | None = None
    note: str = ""


class WeekPlan(BaseModel):
    week_number: int
    week_start: date
    week_end: date
    block_type: BlockType
    sessions: list[TrainingSession]
    target_load: float
    acwr_projected: float | None = None
    load_modifier: float = 1.0


class TrainingPlanRequest(BaseModel):
    race_date: date
    race_distance_km: float
    race_elevation_m: float = 0.0
    race_priority: str = "A"
    sessions_per_week: int = 3
    rest_days: list[int] = [1, 3]
    preferred_long_day: int = 6
    cycle_length_days: int | None = None
    period_length_days: int | None = None
    last_period_start: date | None = None


class TrainingPlan(BaseModel):
    race_date: date
    race_distance_km: float
    total_weeks: int
    ctl_start: float
    ctl_projected: float
    cycle_aware: bool
    warnings: list[str]
    weeks: list[WeekPlan]
