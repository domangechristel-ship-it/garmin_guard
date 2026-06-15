from __future__ import annotations


def project_acwr(
    weekly_tss: list[float],
    ctl_start: float,
    atl_start: float,
) -> list[tuple[float, float, float]]:
    """Project (ATL, CTL, ACWR) week by week from starting values.

    Uses the same EWM coefficients as compute_training_load():
      ATL: span=7  → alpha = 2/(7+1)  = 0.25
      CTL: span=42 → alpha = 2/(42+1) ≈ 0.04651
    """
    alpha_atl = 2 / (7 + 1)
    alpha_ctl = 2 / (42 + 1)

    atl = atl_start
    ctl = ctl_start
    results: list[tuple[float, float, float]] = []

    for tss in weekly_tss:
        daily_tss = tss / 7
        for _ in range(7):
            atl = alpha_atl * daily_tss + (1 - alpha_atl) * atl
            ctl = alpha_ctl * daily_tss + (1 - alpha_ctl) * ctl
        acwr = round(atl / ctl, 3) if ctl > 0 else 0.0
        results.append((round(atl, 2), round(ctl, 2), acwr))

    return results
