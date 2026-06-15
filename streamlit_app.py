import io
import os
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Garmin Guard", layout="wide")

# ---------------------------------------------------------------------------
# Data loading — always via API (ENV=local reads DuckDB, ENV=prod reads BigQuery)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_activities() -> pd.DataFrame:
    r = requests.get(f"{API_URL}/activities")
    r.raise_for_status()
    df = pd.DataFrame(r.json()["data"])
    df["athlete_date"] = pd.to_datetime(df["athlete_date"])
    return df


@st.cache_data(ttl=300)
def load_training_load() -> pd.DataFrame:
    r = requests.get(f"{API_URL}/training-load")
    r.raise_for_status()
    df = pd.DataFrame(r.json()["data"])
    df["athlete_date"] = pd.to_datetime(df["athlete_date"])
    return df


@st.cache_data(ttl=300)
def load_wellness() -> pd.DataFrame:
    r = requests.get(f"{API_URL}/wellness")
    r.raise_for_status()
    df = pd.DataFrame(r.json()["data"])
    df["athlete_date"] = pd.to_datetime(df["athlete_date"])
    return df


acts = load_activities()
load = load_training_load()
well = load_wellness()

# ---------------------------------------------------------------------------
# Sidebar — shared filters
# ---------------------------------------------------------------------------

st.sidebar.title("Garmin Guard")
_env = "local" if "localhost" in API_URL else "prod"
st.sidebar.caption(f"Mode : **{_env}** · `{API_URL}`")

date_min = min(acts["athlete_date"].min(), load["athlete_date"].min(), well["athlete_date"].min()).date()
date_max = max(acts["athlete_date"].max(), load["athlete_date"].max(), well["athlete_date"].max()).date()
default_start = max(date_min, date_max - timedelta(days=30))

start_date, end_date = st.sidebar.date_input(
    "Date range",
    value=(default_start, date_max),
    min_value=date_min,
    max_value=date_max,
)

sport_options = sorted(acts["sport_type"].dropna().unique())
selected_sports = st.sidebar.multiselect("Sport types", sport_options, default="RUNNING")

# Apply date filter
acts_f = acts[
    (acts["athlete_date"].dt.date >= start_date) &
    (acts["athlete_date"].dt.date <= end_date) &
    (acts["sport_type"].isin(selected_sports))
]
load_f = load[
    (load["athlete_date"].dt.date >= start_date) &
    (load["athlete_date"].dt.date <= end_date)
]
well_f = well[
    (well["athlete_date"].dt.date >= start_date) &
    (well["athlete_date"].dt.date <= end_date)
]

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3, tab4 = st.tabs(["Training Load", "Activities", "Wellness", "Plan d'entraînement"])


# ===========================================================================
# TAB 1 — Training Load
# ===========================================================================

with tab1:
    st.header("Training Load")

    last = load_f.dropna(subset=["atl_7d"]).iloc[-1] if not load_f.empty else None

    if last is not None:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("ATL (Acute)", f"{last['atl_7d']:.1f}")
        c2.metric("CTL (Chronic)", f"{last['ctl_42d']:.1f}")
        tsb_val = last["tsb"]
        c3.metric("TSB", f"{tsb_val:+.1f}", delta=f"{'fresh' if tsb_val >= 0 else 'fatigued'}")
        acwr_zone = last["acwr_zone"] if pd.notna(last["acwr_zone"]) else "—"
        c4.metric("ACWR Zone", acwr_zone, delta=f"{last['acwr']:.2f}")

    # ACWR chart
    fig_acwr = go.Figure()
    fig_acwr.add_hrect(y0=0, y1=0.8, fillcolor="lightblue", opacity=0.15, line_width=0, annotation_text="sous-charge", annotation_position="top left")
    fig_acwr.add_hrect(y0=0.8, y1=1.3, fillcolor="lightgreen", opacity=0.15, line_width=0, annotation_text="optimal", annotation_position="top left")
    fig_acwr.add_hrect(y0=1.3, y1=1.5, fillcolor="yellow", opacity=0.15, line_width=0, annotation_text="attention", annotation_position="top left")
    fig_acwr.add_hrect(y0=1.5, y1=5, fillcolor="red", opacity=0.12, line_width=0, annotation_text="risque", annotation_position="top left")
    fig_acwr.add_trace(go.Scatter(
        x=load_f["athlete_date"], y=load_f["acwr"],
        name="ACWR", line=dict(color="#333333", width=2),
    ))
    fig_acwr.update_layout(
        title="ACWR — ratio charge aiguë / chronique",
        xaxis_title=None, yaxis_title="ACWR",
        yaxis=dict(range=[0, min(load_f["acwr"].max() * 1.2, 4)]),
        margin=dict(t=60, b=20), height=280,
        showlegend=False,
    )
    st.plotly_chart(fig_acwr, width="stretch")

    # ATL / CTL chart
    fig_atl = go.Figure()
    fig_atl.add_trace(go.Scatter(
        x=load_f["athlete_date"], y=load_f["ctl_42d"],
        name="CTL (42j)", line=dict(color="#4C9BE8", width=2),
    ))
    fig_atl.add_trace(go.Scatter(
        x=load_f["athlete_date"], y=load_f["atl_7d"],
        name="ATL (7j)", line=dict(color="#F4873F", width=2),
    ))
    fig_atl.update_layout(
        title="Charge chronique (CTL) vs charge aiguë (ATL)",
        xaxis_title=None, yaxis_title="TSS",
        legend=dict(orientation="h", y=1.1),
        margin=dict(t=60, b=20),
        height=300,
    )
    st.plotly_chart(fig_atl, width="stretch")

    # TSB chart
    colors_tsb = ["#2ECC71" if v >= 0 else "#E74C3C" for v in load_f["tsb"]]
    fig_tsb = go.Figure(go.Bar(
        x=load_f["athlete_date"], y=load_f["tsb"],
        marker_color=colors_tsb, name="TSB",
    ))
    fig_tsb.add_hline(y=0, line_dash="dot", line_color="grey")
    fig_tsb.update_layout(
        title="TSB — fraîcheur (vert) / fatigue (rouge)",
        xaxis_title=None, yaxis_title="TSB",
        margin=dict(t=60, b=20), height=250,
    )
    st.plotly_chart(fig_tsb, width="stretch")



# ===========================================================================
# TAB 2 — Activities
# ===========================================================================

with tab2:
    st.header("Activities")

    c1, c2, c3, c4 = st.columns(4)
    total_km = acts_f["distance_m"].sum() / 1000
    total_sessions = len(acts_f)
    avg_hr = acts_f["avg_hr_bpm"].mean()
    total_elev = acts_f["elev_gain_m"].sum()
    c1.metric("Total km", f"{total_km:.0f} km")
    c2.metric("Sessions", total_sessions)
    c3.metric("Avg HR", f"{avg_hr:.0f} bpm" if pd.notna(avg_hr) else "—")
    c4.metric("Total D+", f"{total_elev:.0f} m")

    # Weekly distance chart (RUNNING + CYCLING only)
    dist_sports = acts_f[acts_f["sport_type"].isin(["RUNNING", "CYCLING"])].copy()
    if not dist_sports.empty:
        dist_sports["week"] = dist_sports["athlete_date"].dt.to_period("W").dt.start_time
        weekly = dist_sports.groupby(["week", "sport_type"])["distance_m"].sum().reset_index()
        weekly["distance_km"] = weekly["distance_m"] / 1000

        fig_weekly = go.Figure()
        colors = {"RUNNING": "#F4873F", "CYCLING": "#4C9BE8"}
        for sport in weekly["sport_type"].unique():
            d = weekly[weekly["sport_type"] == sport]
            fig_weekly.add_trace(go.Bar(
                x=d["week"], y=d["distance_km"],
                name=sport, marker_color=colors.get(sport, "#aaa"),
            ))
        fig_weekly.update_layout(
            barmode="stack",
            title="Volume hebdomadaire (km)",
            xaxis_title=None, yaxis_title="km",
            legend=dict(orientation="h", y=1.1),
            margin=dict(t=60, b=20), height=300,
        )
        st.plotly_chart(fig_weekly, width="stretch")

    # Activity table
    display_cols = {
        "athlete_date": "Date",
        "name": "Name",
        "sport_type": "Sport",
        "distance_km": "Dist (km)",
        "duration_min": "Dur (min)",
        "avg_hr_bpm": "Avg HR",
        "pace_min_km": "Pace (min/km)",
        "elev_gain_m": "D+ (m)",
        "calories": "Kcal",
    }
    tbl = acts_f.copy()
    tbl["distance_km"] = (tbl["distance_m"] / 1000).round(2)
    tbl["duration_min"] = (tbl["duration_s"] / 60).round(1)
    tbl["pace_min_km"] = (tbl["avg_pace_s_km"] / 60).round(2)
    available_cols = {k: v for k, v in display_cols.items() if k in tbl.columns}
    tbl = tbl[list(available_cols.keys())].rename(columns=available_cols)
    tbl["Date"] = tbl["Date"].dt.date
    st.dataframe(
        tbl.sort_values("Date", ascending=False).reset_index(drop=True),
        width="stretch",
        height=400,
    )


# ===========================================================================
# TAB 3 — Wellness
# ===========================================================================

with tab3:
    st.header("Wellness")

    PHASE_COLORS = {
        "menstruation": "rgba(231,76,60,0.15)",
        "follicular": "rgba(46,204,113,0.12)",
        "ovulation": "rgba(241,196,15,0.15)",
        "luteal": "rgba(52,152,219,0.12)",
        "pregnant": "rgba(155,89,182,0.15)",
    }

    def add_cycle_bands(fig: go.Figure, df: pd.DataFrame) -> go.Figure:
        """Add vertical cycle-phase bands to a figure."""
        if "cycle_phase" not in df.columns:
            return fig
        phase_df = df.dropna(subset=["cycle_phase"]).copy()
        if phase_df.empty:
            return fig
        phase_df = phase_df.sort_values("athlete_date")
        phase_df["prev"] = phase_df["cycle_phase"].shift()
        boundaries = phase_df[
            (phase_df["cycle_phase"] != phase_df["prev"]) | (phase_df.index == phase_df.index[0])
        ].copy()
        boundaries["end_date"] = boundaries["athlete_date"].shift(-1).fillna(phase_df["athlete_date"].iloc[-1])
        for _, row in boundaries.iterrows():
            color = PHASE_COLORS.get(row["cycle_phase"], "rgba(200,200,200,0.1)")
            fig.add_vrect(
                x0=row["athlete_date"], x1=row["end_date"],
                fillcolor=color, line_width=0, layer="below",
            )
        return fig

    # Sleep score
    sleep_df = well_f.dropna(subset=["sleep_score"])
    if not sleep_df.empty:
        rolling = sleep_df.set_index("athlete_date")["sleep_score"].rolling(7, min_periods=3).mean().reset_index()
        fig_sleep = go.Figure()
        fig_sleep.add_trace(go.Scatter(
            x=sleep_df["athlete_date"], y=sleep_df["sleep_score"],
            mode="markers", name="Score", marker=dict(color="#4C9BE8", size=4, opacity=0.5),
        ))
        fig_sleep.add_trace(go.Scatter(
            x=rolling["athlete_date"], y=rolling["sleep_score"],
            mode="lines", name="Moy 7j", line=dict(color="#2980B9", width=2),
        ))
        fig_sleep = add_cycle_bands(fig_sleep, well_f)
        fig_sleep.update_layout(
            title="Score de sommeil (avec phases du cycle)",
            xaxis_title=None, yaxis_title="Score",
            yaxis=dict(range=[0, 100]),
            legend=dict(orientation="h", y=1.1),
            margin=dict(t=60, b=20), height=280,
        )
        st.plotly_chart(fig_sleep, width="stretch")

    # Cycle phase legend
    st.caption("Phases du cycle : 🔴 menstruation · 🟢 folliculaire · 🟡 ovulation · 🔵 lutéale · 🟣 enceinte")

    # Sleep durations stacked area (local only — not in BigQuery)
    _dur_cols = ["deep_sleep_s", "light_sleep_s", "rem_sleep_s"]
    sleep_dur = well_f.dropna(subset=_dur_cols) if all(c in well_f.columns for c in _dur_cols) else pd.DataFrame()
    if not sleep_dur.empty:
        fig_dur = go.Figure()
        layers = [
            ("Profond", "deep_sleep_s", "#1A3A6C"),
            ("REM", "rem_sleep_s", "#8E44AD"),
            ("Léger", "light_sleep_s", "#85C1E9"),
            ("Éveillé", "awake_s", "#BDC3C7"),
        ]
        for label, col, color in layers:
            fig_dur.add_trace(go.Scatter(
                x=sleep_dur["athlete_date"],
                y=(sleep_dur[col] / 3600).round(2),
                name=label, mode="lines",
                stackgroup="one",
                line=dict(width=0), fillcolor=color,
            ))
        fig_dur.update_layout(
            title="Durées de sommeil (heures)",
            xaxis_title=None, yaxis_title="h",
            legend=dict(orientation="h", y=1.1),
            margin=dict(t=60, b=20), height=280,
        )
        st.plotly_chart(fig_dur, width="stretch")

    # # Weight trend (local only — not in BigQuery)
    # weight_df = well_f.dropna(subset=["weight_kg"]) if "weight_kg" in well_f.columns else pd.DataFrame()
    # if not weight_df.empty:
    #     fig_weight = go.Figure()
    #     fig_weight.add_trace(go.Scatter(
    #         x=weight_df["athlete_date"], y=weight_df["weight_kg"],
    #         mode="lines+markers", name="Poids",
    #         line=dict(color="#E67E22", width=1.5),
    #         marker=dict(size=3),
    #     ))
    #     fig_weight = add_cycle_bands(fig_weight, well_f)
    #     fig_weight.update_layout(
    #         title="Poids (kg) avec phases du cycle",
    #         xaxis_title=None, yaxis_title="kg",
    #         margin=dict(t=60, b=20), height=260,
    #         showlegend=False,
    #     )
    #     st.plotly_chart(fig_weight, width="stretch")


# ===========================================================================
# TAB 4 — Plan d'entraînement
# ===========================================================================

_PHASE_ICONS = {
    "MENSTRUAL": "🔴",
    "FOLLICULAR": "🟢",
    "OVULATION": "🟡",
    "LUTEAL_EARLY": "🔵",
    "LUTEAL_LATE": "🟠",
}

_PHASE_LABELS = {
    "MENSTRUAL": "Menstruation — réduire l'intensité, privilégier la récupération",
    "FOLLICULAR": "Folliculaire — énergie haute, idéal pour les séances dures",
    "OVULATION": "Ovulation — pic de performance, séances longues et intenses",
    "LUTEAL_EARLY": "Lutéale précoce — maintenir le rythme, surveiller la fatigue",
    "LUTEAL_LATE": "Lutéale tardive — réduire la charge, séances douces",
}

_SESSION_LABELS = {
    "RECOVERY": "Récup",
    "SHORT_RUN": "Court",
    "TEMPO": "Tempo",
    "INTERVAL": "Interval",
    "LONG_RUN": "Long",
}

_DAY_NAMES = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]


def _plan_to_calendar(weeks: list[dict]) -> pd.DataFrame:
    rows = []
    for w in weeks:
        sessions_by_day = {s["date"]: s for s in w["sessions"]}
        row = {"Semaine": f"S{w['week_number']} ({w['block_type'][:3]})"}
        week_start = pd.to_datetime(w["week_start"]).date()
        for i, day_label in enumerate(_DAY_NAMES):
            d = week_start + timedelta(days=i)
            s = sessions_by_day.get(str(d))
            if s:
                icon = _PHASE_ICONS.get(s.get("cycle_phase") or "", "")
                label = _SESSION_LABELS.get(s["session_type"], s["session_type"])
                row[day_label] = f"{label} {s['duration_min']}min {icon}".strip()
            else:
                row[day_label] = "—"
        rows.append(row)
    return pd.DataFrame(rows)


def _plan_to_csv(plan: dict) -> bytes:
    rows = []
    for w in plan["weeks"]:
        for s in w["sessions"]:
            rows.append({
                "semaine": w["week_number"],
                "bloc": w["block_type"],
                "date": s["date"],
                "type_seance": s["session_type"],
                "duree_min": s["duration_min"],
                "tss_cible": s["tss_target"],
                "phase_cycle": s.get("cycle_phase") or "",
                "acwr_projete": w.get("acwr_projected") or "",
            })
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode()


_PHASE_COLORS = {
    "MENSTRUAL":    "#F44336",
    "FOLLICULAR":   "#4CAF50",
    "OVULATION":    "#FFC107",
    "LUTEAL_EARLY": "#2196F3",
    "LUTEAL_LATE":  "#FF9800",
}
_PHASE_LEGEND = {
    "MENSTRUAL":    "🔴 Menstruation",
    "FOLLICULAR":   "🟢 Folliculaire",
    "OVULATION":    "🟡 Ovulation",
    "LUTEAL_EARLY": "🔵 Lutéale précoce",
    "LUTEAL_LATE":  "🟠 Lutéale tardive",
}


def _cycle_phase(d: date, last_period: date, cycle_len: int, period_len: int) -> str:
    """Return cycle phase name for date d."""
    day = (d - last_period).days % cycle_len + 1
    ovulation = cycle_len // 2
    if day <= period_len:     return "MENSTRUAL"
    if day <= ovulation - 2:  return "FOLLICULAR"
    if day <= ovulation + 1:  return "OVULATION"
    if day <= ovulation + 6:  return "LUTEAL_EARLY"
    return "LUTEAL_LATE"


def _project_acwr(last_atl: float, last_ctl: float, planned_tss: dict[str, float], days: int = 60) -> tuple[list, list]:
    """Project ATL/CTL/ACWR forward from today using planned daily TSS values."""
    alpha_atl = 2 / (7 + 1)
    alpha_ctl = 2 / (42 + 1)
    today = date.today()
    dates, acwr_vals = [], []
    atl, ctl = last_atl, last_ctl
    for i in range(1, days + 1):
        d = today + timedelta(days=i)
        tss = planned_tss.get(str(d), 0.0)
        atl = atl * (1 - alpha_atl) + tss * alpha_atl
        ctl = ctl * (1 - alpha_ctl) + tss * alpha_ctl
        dates.append(d)
        acwr_vals.append(round(atl / ctl, 3) if ctl > 0 else 0.0)
    return dates, acwr_vals


with tab4:
    st.header("Training plan")

    # -----------------------------------------------------------------------
    # ACWR Dashboard — always visible, no form submit required
    # -----------------------------------------------------------------------
    st.subheader("ACWR — Réel (30 derniers jours) & Projeté (60 prochains jours)")

    _today = date.today()
    _hist_start = _today - timedelta(days=30)
    _proj_end = _today + timedelta(days=60)

    with st.spinner("Chargement de l'ACWR…"):
        try:
            _r_load = requests.get(
                f"{API_URL}/training-load",
                params={"start_date": str(_hist_start), "end_date": str(_today)},
                timeout=10,
            )
            _r_load.raise_for_status()
            _load_records = _r_load.json().get("data", [])
        except Exception as _e:
            _load_records = []
            st.warning(f"Impossible de charger l'historique de charge : {_e}")

        try:
            _r_planned = requests.get(
                f"{API_URL}/planned-workouts",
                params={"start_date": str(_today + timedelta(days=1)), "end_date": str(_proj_end)},
                timeout=10,
            )
            _r_planned.raise_for_status()
            _planned_records = _r_planned.json().get("data", [])
        except Exception:
            _planned_records = []

    # Cycle overlay toggle — parameters auto-derived from synced wellness data
    _show_cycle = st.checkbox("Afficher les phases du cycle menstruel")
    _cycle_last_period: date | None = None
    _cycle_length = 28
    _cycle_period_len = 5

    if _show_cycle:
        _well_cycle = well.dropna(subset=["cycle_day"]).sort_values("athlete_date")
        if _well_cycle.empty:
            st.info(
                "Aucune donnée de cycle trouvée dans Garmin Connect. "
                "Synchronisez vos données (`sync_garmin_connect.py`) pour afficher les phases.",
                icon="ℹ️",
            )
            _show_cycle = False
        else:
            _last_crow = _well_cycle.iloc[-1]
            _last_cd = int(_last_crow["cycle_day"])
            _last_cdate = pd.Timestamp(_last_crow["athlete_date"]).date()
            _cycle_last_period = _last_cdate - timedelta(days=_last_cd - 1)

            # Cycle length: average gap between consecutive day-1 dates
            _day1_dates = _well_cycle[_well_cycle["cycle_day"] == 1]["athlete_date"].sort_values()
            if len(_day1_dates) >= 2:
                _gaps = [
                    (pd.Timestamp(b).date() - pd.Timestamp(a).date()).days
                    for a, b in zip(_day1_dates.iloc[:-1], _day1_dates.iloc[1:])
                ]
                _cycle_length = int(round(sum(_gaps) / len(_gaps)))

            # Period length: count days active since last period start
            if "period_active" in _well_cycle.columns:
                _prows = _well_cycle[
                    (_well_cycle["athlete_date"] >= pd.Timestamp(_cycle_last_period)) &
                    (_well_cycle["period_active"].fillna(False).astype(bool))
                ]
                if not _prows.empty:
                    _cycle_period_len = len(_prows)

            st.caption(
                f"Cycle détecté depuis Garmin : dernières règles le **{_cycle_last_period}**, "
                f"cycle de **{_cycle_length} j**, règles de **{_cycle_period_len} j**."
            )

    # Actual ACWR from training_load
    _actual_df = pd.DataFrame(_load_records) if _load_records else pd.DataFrame()
    _actual_dates: list = []
    _actual_acwr: list = []
    _last_atl = 0.0
    _last_ctl = 0.0
    if not _actual_df.empty and "acwr" in _actual_df.columns:
        _actual_df["athlete_date"] = pd.to_datetime(_actual_df["athlete_date"]).dt.date
        _actual_dates = _actual_df["athlete_date"].tolist()
        _actual_acwr = _actual_df["acwr"].tolist()
        _last_atl = float(_actual_df["atl_7d"].iloc[-1] or 0)
        _last_ctl = float(_actual_df["ctl_42d"].iloc[-1] or 0)

    # Planned TSS dict  {date_str: tss}
    _planned_tss: dict[str, float] = {
        str(item["scheduled_date"])[:10]: float(item["tss_estimated"] or 0)
        for item in _planned_records
        if item.get("tss_estimated") is not None
    }

    # Project forward
    _proj_dates, _proj_acwr = _project_acwr(_last_atl, _last_ctl, _planned_tss, days=60)

    # Build figure
    _fig_acwr_dash = go.Figure()
    _fig_acwr_dash.add_hrect(y0=0, y1=0.8, fillcolor="lightblue", opacity=0.15, line_width=0,
                              annotation_text="sous-charge", annotation_position="top left")
    _fig_acwr_dash.add_hrect(y0=0.8, y1=1.3, fillcolor="lightgreen", opacity=0.15, line_width=0,
                              annotation_text="optimal", annotation_position="top left")
    _fig_acwr_dash.add_hrect(y0=1.3, y1=1.5, fillcolor="yellow", opacity=0.15, line_width=0,
                              annotation_text="attention", annotation_position="top left")
    _fig_acwr_dash.add_hrect(y0=1.5, y1=5, fillcolor="red", opacity=0.12, line_width=0,
                              annotation_text="risque", annotation_position="top left")

    # Actual line (solid blue)
    if _actual_dates:
        _fig_acwr_dash.add_trace(go.Scatter(
            x=_actual_dates, y=_actual_acwr,
            name="ACWR réel", line=dict(color="#1565C0", width=2),
            mode="lines+markers", marker=dict(size=4),
        ))

    # Projected line (dashed orange) — join from last actual point
    _join_dates = ([_actual_dates[-1]] + _proj_dates) if _actual_dates else _proj_dates
    _join_acwr = ([_actual_acwr[-1]] + _proj_acwr) if _actual_acwr else _proj_acwr
    _fig_acwr_dash.add_trace(go.Scatter(
        x=_join_dates, y=_join_acwr,
        name="ACWR projeté", line=dict(color="#E65100", width=2, dash="dash"),
        mode="lines",
    ))

    # Markers on days with a planned workout
    if _planned_records:
        _planned_date_to_acwr = dict(zip(_proj_dates, _proj_acwr))
        _mk_dates = []
        _mk_acwr = []
        _mk_labels = []
        for _item in _planned_records:
            _d = date.fromisoformat(str(_item["scheduled_date"])[:10])
            if _d in _planned_date_to_acwr:
                _mk_dates.append(_d)
                _mk_acwr.append(_planned_date_to_acwr[_d])
                _mk_labels.append(_item.get("workout_name") or _item.get("sport_type") or "Séance")
        if _mk_dates:
            _fig_acwr_dash.add_trace(go.Scatter(
                x=_mk_dates, y=_mk_acwr,
                name="Séance planifiée",
                mode="markers",
                marker=dict(symbol="diamond", size=10, color="#E65100", line=dict(color="white", width=1)),
                text=_mk_labels,
                hovertemplate="%{text}<br>ACWR: %{y:.2f}<extra></extra>",
            ))

    # Cycle phase bands
    if _show_cycle and _cycle_last_period:
        _all_chart_dates = list(_actual_dates) + list(_proj_dates)
        if _all_chart_dates:
            _ph_start = _all_chart_dates[0]
            _cur_ph = _cycle_phase(_ph_start, _cycle_last_period, _cycle_length, _cycle_period_len)
            for _cd in _all_chart_dates[1:]:
                _ph = _cycle_phase(_cd, _cycle_last_period, _cycle_length, _cycle_period_len)
                if _ph != _cur_ph:
                    _fig_acwr_dash.add_vrect(
                        x0=str(_ph_start), x1=str(_cd),
                        fillcolor=_PHASE_COLORS[_cur_ph], opacity=0.10, line_width=0, layer="below",
                    )
                    _ph_start, _cur_ph = _cd, _ph
            _fig_acwr_dash.add_vrect(
                x0=str(_ph_start), x1=str(_all_chart_dates[-1]),
                fillcolor=_PHASE_COLORS[_cur_ph], opacity=0.10, line_width=0, layer="below",
            )

    # Today vertical line
    _fig_acwr_dash.add_shape(
        type="line",
        x0=str(_today), x1=str(_today),
        y0=0, y1=1, yref="paper",
        line=dict(color="gray", width=1, dash="dot"),
    )
    _fig_acwr_dash.add_annotation(
        x=str(_today), y=1, yref="paper",
        text="Aujourd'hui", showarrow=False,
        xanchor="right", yanchor="bottom", font=dict(color="gray", size=11),
    )

    _fig_acwr_dash.update_layout(
        xaxis_title=None, yaxis_title="ACWR",
        yaxis=dict(range=[0, max(1.8, max(_proj_acwr, default=0) + 0.2)]),
        legend=dict(orientation="h", y=1.12),
        margin=dict(t=30, b=20), height=320,
    )

    st.plotly_chart(_fig_acwr_dash, use_container_width=True)

    if _show_cycle and _cycle_last_period:
        st.caption("  ·  ".join(_PHASE_LEGEND.values()))

    if not _planned_records:
        st.info(
            "Aucune séance planifiée trouvée dans Garmin Connect. "
            "La projection suppose zéro charge sur les 60 prochains jours. "
            "Lancez une synchronisation (`sync_garmin_connect.py`) pour importer vos séances planifiées.",
            icon="ℹ️",
        )
    else:
        st.caption(f"{len(_planned_records)} séance(s) planifiée(s) importée(s) depuis Garmin Connect.")

    # st.divider()

    # col_params, col_results = st.columns([1, 2], gap="large")

    # with col_params:
    #     st.subheader("Course objectif")
    #     race_date_input = st.date_input(
    #         "Date de la course",
    #         value=date.today() + timedelta(weeks=16),
    #         min_value=date.today() + timedelta(days=7),
    #     )
    #     race_distance = st.number_input("Distance (km)", min_value=1.0, max_value=200.0, value=42.0, step=0.5)
    #     race_elevation = st.number_input("Dénivelé positif (m)", min_value=0, max_value=10000, value=0, step=100)
    #     race_priority = st.selectbox("Priorité", ["A", "B", "C"], index=0)

    #     st.subheader("Fréquence")
    #     sessions_per_week = st.slider("Séances par semaine", min_value=3, max_value=4, value=3)
    #     rest_days_input = st.multiselect(
    #         "Jours de repos",
    #         options=list(range(7)),
    #         default=[1, 3],
    #         format_func=lambda x: _DAY_NAMES[x],
    #     )
    #     long_day_input = st.selectbox(
    #         "Jour trail long",
    #         options=[d for d in range(7) if d not in rest_days_input],
    #         index=0,
    #         format_func=lambda x: _DAY_NAMES[x],
    #     )

    #     cycle_aware = False
    #     last_period_start = None
    #     cycle_length = None
    #     period_length = None

    #     with st.expander("Cycle menstruel (optionnel)"):
    #         cycle_aware = st.toggle("Activer la prise en compte du cycle")
    #         if cycle_aware:
    #             st.info(
    #                 "Ces données restent locales et ne sont jamais envoyées à une API externe.",
    #                 icon="🔒",
    #             )
    #             cycle_length = st.number_input("Durée du cycle (jours)", min_value=21, max_value=40, value=28)
    #             period_length = st.number_input("Durée des règles (jours)", min_value=2, max_value=10, value=5)
    #             last_period_start = st.date_input(
    #                 "Début des dernières règles",
    #                 value=date.today() - timedelta(days=14),
    #                 max_value=date.today(),
    #             )

    #     generate = st.button("Générer mon plan", type="primary", use_container_width=True)

    # with col_results:
    #     if generate:
    #         payload = {
    #             "race_date": str(race_date_input),
    #             "race_distance_km": race_distance,
    #             "race_elevation_m": race_elevation,
    #             "race_priority": race_priority,
    #             "sessions_per_week": sessions_per_week,
    #             "rest_days": rest_days_input,
    #             "preferred_long_day": long_day_input,
    #         }
    #         if cycle_aware and last_period_start:
    #             payload["last_period_start"] = str(last_period_start)
    #             payload["cycle_length_days"] = cycle_length
    #             payload["period_length_days"] = period_length

    #         with st.spinner("Génération du plan…"):
    #             try:
    #                 resp = requests.post(f"{API_URL}/training-plan", json=payload, timeout=30)
    #                 resp.raise_for_status()
    #                 plan = resp.json()
    #             except Exception as e:
    #                 st.error(f"Erreur lors de la génération : {e}")
    #                 st.stop()

    #         # Warnings
    #         for w in plan.get("warnings", []):
    #             st.warning(w)

    #         # Summary metrics
    #         total_sessions = sum(len(w["sessions"]) for w in plan["weeks"])
    #         m1, m2, m3 = st.columns(3)
    #         m1.metric("Semaines", plan["total_weeks"])
    #         m2.metric("CTL actuel → projeté", f"{plan['ctl_start']} → {plan['ctl_projected']}")
    #         m3.metric("Séances totales", total_sessions)

    #         st.divider()

    #         # Weekly calendar
    #         st.subheader("Calendrier hebdomadaire")
    #         calendar_df = _plan_to_calendar(plan["weeks"])
    #         st.dataframe(calendar_df.set_index("Semaine"), use_container_width=True)

    #         st.divider()

    #         # ACWR projection chart
    #         st.subheader("ACWR projeté")
    #         weeks_data = plan["weeks"]
    #         week_labels = [f"S{w['week_number']}" for w in weeks_data]
    #         acwr_values = [w.get("acwr_projected") for w in weeks_data]

    #         fig_plan_acwr = go.Figure()
    #         fig_plan_acwr.add_hrect(
    #             y0=0, y1=0.8, fillcolor="lightblue", opacity=0.15, line_width=0,
    #             annotation_text="sous-charge", annotation_position="top left",
    #         )
    #         fig_plan_acwr.add_hrect(
    #             y0=0.8, y1=1.3, fillcolor="lightgreen", opacity=0.15, line_width=0,
    #             annotation_text="optimal", annotation_position="top left",
    #         )
    #         fig_plan_acwr.add_hrect(
    #             y0=1.3, y1=1.5, fillcolor="yellow", opacity=0.15, line_width=0,
    #             annotation_text="attention", annotation_position="top left",
    #         )
    #         fig_plan_acwr.add_hrect(
    #             y0=1.5, y1=5, fillcolor="red", opacity=0.12, line_width=0,
    #             annotation_text="risque", annotation_position="top left",
    #         )
    #         fig_plan_acwr.add_trace(go.Scatter(
    #             x=week_labels, y=acwr_values,
    #             name="ACWR projeté", line=dict(color="#333333", width=2),
    #             mode="lines+markers", marker=dict(size=6),
    #         ))
    #         fig_plan_acwr.update_layout(
    #             xaxis_title=None, yaxis_title="ACWR",
    #             yaxis=dict(range=[0, 1.6]),
    #             margin=dict(t=20, b=20), height=260,
    #             showlegend=False,
    #         )
    #         st.plotly_chart(fig_plan_acwr, use_container_width=True)

    #         # Cycle impact chart (only when cycle_aware)
    #         if plan.get("cycle_aware"):
    #             st.subheader("Impact du cycle menstruel sur la charge")
    #             raw_loads = [w["target_load"] / w["load_modifier"] if w["load_modifier"] else w["target_load"] for w in weeks_data]
    #             cycle_loads = [w["target_load"] for w in weeks_data]

    #             fig_cycle = go.Figure()
    #             fig_cycle.add_trace(go.Bar(
    #                 x=week_labels, y=raw_loads,
    #                 name="Sans modulation cycle", marker_color="#B0C4DE", opacity=0.7,
    #             ))
    #             fig_cycle.add_trace(go.Bar(
    #                 x=week_labels, y=cycle_loads,
    #                 name="Avec modulation cycle", marker_color="#E67E22",
    #             ))
    #             fig_cycle.update_layout(
    #                 barmode="overlay",
    #                 xaxis_title=None, yaxis_title="TSS hebdo",
    #                 legend=dict(orientation="h", y=1.1),
    #                 margin=dict(t=20, b=20), height=260,
    #             )
    #             st.plotly_chart(fig_cycle, use_container_width=True)

    #             # Phase legend
    #             st.subheader("Légende des phases")
    #             for phase, icon in _PHASE_ICONS.items():
    #                 st.caption(f"{icon} **{phase}** — {_PHASE_LABELS[phase]}")

    #         st.divider()

    #         # CSV export
    #         csv_bytes = _plan_to_csv(plan)
    #         st.download_button(
    #             label="Exporter le plan (CSV)",
    #             data=csv_bytes,
    #             file_name=f"plan_entrainement_{race_date_input}.csv",
    #             mime="text/csv",
    #             use_container_width=True,
    #         )
