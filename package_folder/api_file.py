import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, Query, Request

# Make src/ importable when running from repo root
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from training_plan.generator import TrainingPlanGenerator
from training_plan.models import TrainingPlanRequest

ENV = os.getenv("ENV", "local")
ROOT = Path(__file__).resolve().parents[1]
GCP_PROJECT = os.getenv("GCP_PROJECT", "garmin-guard")
BQ_DATASET = f"{GCP_PROJECT}.garmin_guard"
DB_PATH = ROOT / "data" / "garmin_guard.duckdb"


def _tbl(name: str) -> str:
    """Return the fully-qualified table reference for the active backend."""
    return f"`{BQ_DATASET}.{name}`" if ENV == "prod" else name


def _to_records(df: pd.DataFrame) -> list:
    """Serialize a DataFrame to JSON-safe records (NaN → null, dates → ISO)."""
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _where(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    sport_type: list[str] | None = None,
) -> str:
    clauses = ["1=1"]
    if start_date:
        clauses.append(f"athlete_date >= '{start_date}'")
    if end_date:
        clauses.append(f"athlete_date <= '{end_date}'")
    if sport_type:
        types_list = ", ".join(f"'{t}'" for t in sport_type)
        clauses.append(f"sport_type IN ({types_list})")
    return "WHERE " + " AND ".join(clauses)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if ENV == "local":
        import duckdb
        con = duckdb.connect(str(DB_PATH), read_only=True)
        app.state.query = lambda sql: con.execute(sql).df()
        yield
        con.close()
    else:
        from google.cloud import bigquery
        client = bigquery.Client(project=GCP_PROJECT)
        app.state.query = lambda sql: client.query(sql).to_dataframe()
        yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "env": ENV}


@app.get("/activities")
def get_activities(
    request: Request,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    sport_type: list[str] = Query(default=[]),
):
    sql = f"SELECT * FROM {_tbl('activities')} {_where(start_date, end_date, sport_type)} ORDER BY athlete_date"
    df = request.app.state.query(sql)
    return {"data": _to_records(df), "count": len(df)}


@app.get("/training-load")
def get_training_load(
    request: Request,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    sql = f"SELECT * FROM {_tbl('training_load')} {_where(start_date, end_date)} ORDER BY athlete_date"
    df = request.app.state.query(sql)
    return {"data": _to_records(df), "count": len(df)}


@app.get("/wellness")
def get_wellness(
    request: Request,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    tbl = "wellness" if ENV == "local" else "wellness_public"
    sql = f"SELECT * FROM {_tbl(tbl)} {_where(start_date, end_date)} ORDER BY athlete_date"
    df = request.app.state.query(sql)
    return {"data": _to_records(df), "count": len(df)}


@app.get("/planned-workouts")
def get_planned_workouts(
    request: Request,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    clauses = ["1=1"]
    if start_date:
        clauses.append(f"scheduled_date >= '{start_date}'")
    if end_date:
        clauses.append(f"scheduled_date <= '{end_date}'")
    where = "WHERE " + " AND ".join(clauses)
    sql = f"SELECT * FROM {_tbl('planned_workouts')} {where} ORDER BY scheduled_date"
    try:
        df = request.app.state.query(sql)
    except Exception:
        df = __import__("pandas").DataFrame()
    return {"data": _to_records(df), "count": len(df)}


@app.post("/training-plan")
def post_training_plan(request: Request, body: TrainingPlanRequest):
    sql = f"SELECT atl_7d, ctl_42d FROM {_tbl('training_load')} ORDER BY athlete_date DESC LIMIT 1"
    row = request.app.state.query(sql).iloc[0]
    ctl_start = float(row["ctl_42d"])
    atl_start = float(row["atl_7d"])
    plan = TrainingPlanGenerator().generate(body, ctl_start, atl_start)
    return plan.model_dump(mode="json")
