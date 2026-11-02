"""DuckDB connection helpers."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from config import DB_PATH, ROOT

SCHEMA_PATH = ROOT / "db" / "schema.sql"

DROP_VIEWS = (
    "fix_first",
    "sensor_readings_live",
    "faults_live",
    "failures_live",
    "maintenance_live",
    "inventory",
)
DROP_TABLES = (
    "current_scores",
    "predictions",
    "work_orders",
    "plant_clock",
    "sensor_readings",
    "faults",
    "failures",
    "maintenance_events",
    "parts",
    "technicians",
    "shifts",
    "machines",
    "bench_ai4i",
    "bench_cmapss_fd001",
    "bench_cmapss_rul",
)


def connect(db_path: Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def reset_schema(con: duckdb.DuckDBPyConnection) -> None:
    for view in DROP_VIEWS:
        con.execute(f"DROP VIEW IF EXISTS {view}")
    for table in DROP_TABLES:
        con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(SCHEMA_PATH.read_text())


def insert_df(con: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame, columns: list[str]) -> None:
    payload = frame.loc[:, columns].copy()
    con.register("_incoming", payload)
    quoted = ", ".join(columns)
    con.execute(f"INSERT INTO {table} ({quoted}) SELECT {quoted} FROM _incoming")
    con.unregister("_incoming")


def read_clock(con: duckdb.DuckDBPyConnection) -> pd.Timestamp:
    row = con.execute("SELECT as_of FROM plant_clock WHERE id = 1").fetchone()
    if row is None:
        raise RuntimeError("plant_clock is empty. Run make pipeline.")
    return pd.Timestamp(row[0])


def write_clock(con: duckdb.DuckDBPyConnection, as_of: pd.Timestamp, note: str) -> None:
    con.execute("DELETE FROM plant_clock WHERE id = 1")
    con.execute(
        "INSERT INTO plant_clock (id, as_of, note) VALUES (1, ?, ?)",
        [pd.Timestamp(as_of).to_pydatetime(), note],
    )
