from __future__ import annotations

import logging
from datetime import date, timedelta
from math import ceil

from .cycle import CycleModel
from .models import (
    BlockType,
    CyclePhase,
    SessionType,
    TrainingPlan,
    TrainingPlanRequest,
    TrainingSession,
    WeekPlan,
)
from .optimizer import project_acwr

log = logging.getLogger(__name__)

ACWR_LOW = 0.8
ACWR_HIGH = 1.3

# TSS ratios per session type (fraction of weekly load)
_TSS_RATIOS_3 = {
    SessionType.LONG_RUN: 0.45,
    "medium": 0.30,
    "short": 0.25,
}
_TSS_RATIOS_4 = {
    SessionType.LONG_RUN: 0.40,
    "medium1": 0.25,
    "medium2": 0.20,
    "short": 0.15,
}

# Inverse of TSS proxy: tss = duration_s * avg_hr / 3600 / 10
# → duration_min = tss * 600 / avg_hr
_AVG_HR = 140


def _duration_from_tss(tss: float) -> int:
    return max(20, round(tss * 600 / _AVG_HR))


def _build_block_types(plan_weeks: int, block_size: int) -> list[BlockType]:
    """Return a BlockType for each week, with last 2 weeks always TAPER."""
    types: list[BlockType] = []
    non_taper = plan_weeks - 2
    pos = 0
    while pos < non_taper:
        for i in range(block_size):
            if pos >= non_taper:
                break
            block_pos = i % block_size
            if block_pos < block_size - 1:
                types.append(BlockType.BUILD)
            else:
                types.append(BlockType.RECOVERY)
            pos += 1
    types.extend([BlockType.TAPER, BlockType.TAPER])
    return types


def _pick_session_types(
    block: BlockType,
    slots: int,
    preferred_long_day_slot: int,
    cycle_model: CycleModel | None,
    week_start: date,
    slot_days: list[int],
) -> list[SessionType]:
    """Return a SessionType for each slot in the week."""
    result: list[SessionType] = [SessionType.SHORT_RUN] * slots

    for i, day_offset in enumerate(slot_days):
        d = week_start + timedelta(days=day_offset)
        if day_offset == preferred_long_day_slot:
            result[i] = SessionType.LONG_RUN
            continue

        if block == BlockType.TAPER:
            result[i] = SessionType.SHORT_RUN
            continue

        if block == BlockType.RECOVERY:
            result[i] = SessionType.RECOVERY if i == 0 else SessionType.SHORT_RUN
            continue

        # BUILD — choose based on position and cycle
        if cycle_model:
            phase = cycle_model.phase_for_date(d)
            recommended = CycleModel.RECOMMENDED_SESSIONS[phase]
            non_long = [s for s in recommended if s != SessionType.LONG_RUN]
            candidate = non_long[i % len(non_long)] if non_long else SessionType.SHORT_RUN
        else:
            build_rotation = [SessionType.INTERVAL, SessionType.TEMPO, SessionType.SHORT_RUN]
            candidate = build_rotation[i % len(build_rotation)]

        # Degrade INTERVAL to SHORT_RUN if cycle phase is recovery-oriented
        if cycle_model:
            phase = cycle_model.phase_for_date(d)
            if candidate == SessionType.INTERVAL and phase in (
                CyclePhase.MENSTRUAL,
                CyclePhase.LUTEAL_LATE,
            ):
                log.info("Session ajustée phase %s: INTERVAL → SHORT_RUN (%s)", phase, d)
                candidate = SessionType.SHORT_RUN

        result[i] = candidate

    return result


class TrainingPlanGenerator:
    def generate(
        self,
        request: TrainingPlanRequest,
        ctl_start: float,
        atl_start: float,
    ) -> TrainingPlan:
        warnings: list[str] = []
        today = date.today()

        # --- Étape 1 : Cadrage temporel ---
        taper_start = request.race_date - timedelta(days=14)
        days_to_taper = (taper_start - today).days
        plan_weeks = max(1, ceil(days_to_taper / 7))

        if plan_weeks < 4:
            warnings.append(
                f"Plan trop court ({plan_weeks} semaine(s)) — progression de charge non optimale."
            )

        # --- Étape 2 : Périodisation macrocyclique ---
        block_size = 4 if plan_weeks >= 6 else 3
        block_types = _build_block_types(plan_weeks, block_size)

        # --- CycleModel ---
        cycle_model: CycleModel | None = None
        if request.last_period_start:
            cycle_model = CycleModel(
                last_period_start=request.last_period_start,
                cycle_length_days=request.cycle_length_days or 28,
                period_length_days=request.period_length_days or 5,
            )

        # --- Étape 3 : Charge hebdo cible initiale ---
        base_load = ctl_start * 7
        target_loads = _compute_target_loads(
            block_types, base_load, cycle_model, today
        )

        # --- Étape 5 : Vérification ACWR (boucle d'ajustement) ---
        target_loads = _adjust_for_acwr(
            target_loads, block_types, ctl_start, atl_start, base_load, warnings
        )

        # --- Projection ACWR finale ---
        acwr_projection = project_acwr(target_loads, ctl_start, atl_start)

        # --- Étape 4 + 6 : Distribution des séances et assemblage ---
        weeks: list[WeekPlan] = []
        for w_idx, (block, target_load) in enumerate(zip(block_types, target_loads)):
            week_start = today + timedelta(weeks=w_idx)
            # Align to Monday
            week_start = week_start - timedelta(days=week_start.weekday())
            week_end = week_start + timedelta(days=6)

            modifier = (
                cycle_model.week_modifier(week_start) if cycle_model else 1.0
            )

            # Available day offsets (0=Mon … 6=Sun), excluding rest_days
            available_days = [
                d for d in range(7) if d not in request.rest_days
            ]

            # Ensure preferred_long_day is in available_days
            if request.preferred_long_day not in available_days:
                available_days.append(request.preferred_long_day)
                available_days.sort()

            # Select slots
            sessions_count = min(request.sessions_per_week, len(available_days))
            # Place long run first, then fill from available
            long_day = request.preferred_long_day
            other_days = [d for d in available_days if d != long_day]
            slots = other_days[: sessions_count - 1] + [long_day]
            slots.sort()

            session_types = _pick_session_types(
                block, sessions_count, long_day, cycle_model, week_start, slots
            )

            # TSS ratios
            tss_by_slot = _split_tss(target_load, session_types, long_day, slots)

            sessions: list[TrainingSession] = []
            for day_offset, stype, tss in zip(slots, session_types, tss_by_slot):
                session_date = week_start + timedelta(days=day_offset)
                phase = cycle_model.phase_for_date(session_date) if cycle_model else None
                sessions.append(
                    TrainingSession(
                        date=session_date,
                        session_type=stype,
                        duration_min=_duration_from_tss(tss),
                        tss_target=round(tss, 1),
                        cycle_phase=phase,
                    )
                )

            _, ctl_proj, acwr_proj = acwr_projection[w_idx]
            weeks.append(
                WeekPlan(
                    week_number=w_idx + 1,
                    week_start=week_start,
                    week_end=week_end,
                    block_type=block,
                    sessions=sessions,
                    target_load=round(target_load, 1),
                    acwr_projected=acwr_proj,
                    load_modifier=round(modifier, 3),
                )
            )

        ctl_projected = acwr_projection[-1][1] if acwr_projection else ctl_start

        return TrainingPlan(
            race_date=request.race_date,
            race_distance_km=request.race_distance_km,
            total_weeks=plan_weeks,
            ctl_start=round(ctl_start, 2),
            ctl_projected=round(ctl_projected, 2),
            cycle_aware=cycle_model is not None,
            warnings=warnings,
            weeks=weeks,
        )


def _compute_target_loads(
    block_types: list[BlockType],
    base_load: float,
    cycle_model: CycleModel | None,
    today: date,
) -> list[float]:
    loads: list[float] = []
    block_load = base_load
    prev_block: BlockType | None = None

    for w_idx, block in enumerate(block_types):
        week_start = today + timedelta(weeks=w_idx)
        week_start = week_start - timedelta(days=week_start.weekday())

        if block == BlockType.BUILD:
            if prev_block != BlockType.BUILD:
                block_load = base_load
            else:
                block_load = min(block_load * 1.08, base_load * 1.30)
            load = block_load
        elif block == BlockType.RECOVERY:
            load = base_load * 0.80
            block_load = base_load
        else:  # TAPER
            total = len(block_types)
            if w_idx == total - 2:
                load = base_load * 0.70
            else:
                load = base_load * 0.50

        if cycle_model:
            modifier = cycle_model.week_modifier(week_start)
            load *= modifier

        loads.append(load)
        prev_block = block

    return loads


def _adjust_for_acwr(
    target_loads: list[float],
    block_types: list[BlockType],
    ctl_start: float,
    atl_start: float,
    base_load: float,
    warnings: list[str],
) -> list[float]:
    adjusted = list(target_loads)

    for w_idx in range(len(adjusted)):
        for _ in range(10):
            projection = project_acwr(adjusted, ctl_start, atl_start)
            _, _, acwr = projection[w_idx]
            if ACWR_LOW <= acwr <= ACWR_HIGH:
                break
            if acwr < ACWR_LOW:
                adjusted[w_idx] *= 1.05
            else:
                adjusted[w_idx] *= 0.95

        delta_pct = abs(adjusted[w_idx] - target_loads[w_idx]) / max(target_loads[w_idx], 1) * 100
        if delta_pct > 15:
            warnings.append(
                f"Semaine {w_idx + 1} : ajustement ACWR important ({delta_pct:.0f}% de la charge initiale)."
            )

    return adjusted


def _split_tss(
    total_tss: float,
    session_types: list[SessionType],
    long_day: int,
    slots: list[int],
) -> list[float]:
    n = len(session_types)
    long_idx = slots.index(long_day) if long_day in slots else -1

    if long_idx >= 0:
        long_tss = total_tss * 0.45
        remaining = total_tss - long_tss
        other_count = n - 1
        result = []
        other_idx = 0
        for i, stype in enumerate(session_types):
            if i == long_idx:
                result.append(long_tss)
            else:
                share = remaining / other_count if other_count > 0 else remaining
                result.append(share)
                other_idx += 1
    else:
        share = total_tss / n
        result = [share] * n

    return result
