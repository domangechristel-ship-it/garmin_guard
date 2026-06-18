from __future__ import annotations

from datetime import date, timedelta

from .models import CyclePhase, SessionType


class CycleModel:
    LOAD_MODIFIERS: dict[CyclePhase, float] = {
        CyclePhase.MENSTRUAL: 0.80,
        CyclePhase.FOLLICULAR: 1.10,
        CyclePhase.OVULATION: 1.00,
        CyclePhase.LUTEAL_EARLY: 0.90,
        CyclePhase.LUTEAL_LATE: 0.75,
    }

    RECOMMENDED_SESSIONS: dict[CyclePhase, list[SessionType]] = {
        CyclePhase.MENSTRUAL: [SessionType.RECOVERY, SessionType.SHORT_RUN],
        CyclePhase.FOLLICULAR: [SessionType.INTERVAL, SessionType.TEMPO, SessionType.LONG_RUN],
        CyclePhase.OVULATION: [SessionType.LONG_RUN, SessionType.INTERVAL],
        CyclePhase.LUTEAL_EARLY: [SessionType.TEMPO, SessionType.SHORT_RUN],
        CyclePhase.LUTEAL_LATE: [SessionType.RECOVERY, SessionType.SHORT_RUN],
    }

    def __init__(
        self,
        last_period_start: date,
        cycle_length_days: int = 28,
        period_length_days: int = 5,
    ) -> None:
        self.last_period_start = last_period_start
        self.cycle_length = cycle_length_days
        self.period_length = period_length_days

    def phase_for_date(self, d: date) -> CyclePhase:
        cycle_day = (d - self.last_period_start).days % self.cycle_length + 1
        if cycle_day <= self.period_length:
            return CyclePhase.MENSTRUAL
        if cycle_day <= 12:
            return CyclePhase.FOLLICULAR
        if cycle_day <= 16:
            return CyclePhase.OVULATION
        if cycle_day <= self.cycle_length - 5:
            return CyclePhase.LUTEAL_EARLY
        return CyclePhase.LUTEAL_LATE

    def week_modifier(self, week_start: date) -> float:
        modifiers = [
            self.LOAD_MODIFIERS[self.phase_for_date(week_start + timedelta(days=i))]
            for i in range(7)
        ]
        return round(sum(modifiers) / 7, 4)
