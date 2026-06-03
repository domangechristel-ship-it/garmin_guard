"""
load_duckdb.py
--------------
Load the three processed CSVs into a local DuckDB file.
Run this after garmin_update to refresh the local database.

Usage:
    python src/ingestion/load_duckdb.py
"""

import duckdb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
DB_PATH = ROOT / "data" / "garmin_guard.duckdb"


def main() -> None:
    tmp_path = DB_PATH.with_suffix(".tmp.duckdb")
    tmp_path.unlink(missing_ok=True)

    con = duckdb.connect(str(tmp_path))

    tables = {
        "activities":     PROCESSED / "activities_normalized.csv",
        "training_load":  PROCESSED / "training_load_features.csv",
        "wellness":       PROCESSED / "wellness_normalized.csv",
    }

    for table, csv_path in tables.items():
        con.execute(
            f"CREATE OR REPLACE TABLE {table} AS "
            f"SELECT * FROM read_csv_auto('{csv_path}')"
        )
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"✓ {table:<15} {count} rows")

    con.close()
    # Atomic replace — any reader holding the old file keeps their handle valid
    tmp_path.replace(DB_PATH)
    print(f"\nDuckDB saved → {DB_PATH}")


if __name__ == "__main__":
    main()
