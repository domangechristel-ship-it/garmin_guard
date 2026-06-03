import os

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

date_min = acts["athlete_date"].min().date()
date_max = acts["athlete_date"].max().date()

start_date, end_date = st.sidebar.date_input(
    "Date range",
    value=(date_min, date_max),
    min_value=date_min,
    max_value=date_max,
)

sport_options = sorted(acts["sport_type"].dropna().unique())
selected_sports = st.sidebar.multiselect("Sport types", sport_options, default=sport_options)

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

tab1, tab2, tab3 = st.tabs(["Training Load", "Activities", "Wellness"])


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

    # Weight trend (local only — not in BigQuery)
    weight_df = well_f.dropna(subset=["weight_kg"]) if "weight_kg" in well_f.columns else pd.DataFrame()
    if not weight_df.empty:
        fig_weight = go.Figure()
        fig_weight.add_trace(go.Scatter(
            x=weight_df["athlete_date"], y=weight_df["weight_kg"],
            mode="lines+markers", name="Poids",
            line=dict(color="#E67E22", width=1.5),
            marker=dict(size=3),
        ))
        fig_weight = add_cycle_bands(fig_weight, well_f)
        fig_weight.update_layout(
            title="Poids (kg) avec phases du cycle",
            xaxis_title=None, yaxis_title="kg",
            margin=dict(t=60, b=20), height=260,
            showlegend=False,
        )
        st.plotly_chart(fig_weight, width="stretch")

    # Cycle phase legend
    st.caption("Phases du cycle : 🔴 menstruation · 🟢 folliculaire · 🟡 ovulation · 🔵 lutéale · 🟣 enceinte")
