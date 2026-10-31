"""Rebuild the warehouse from data/raw in one command."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import DB_PATH, EXPECTED_COUNTS, RAW_DIR
from pipeline.load import load_ai4i, load_azure, load_cmapss_fd001, with_ids
from pipeline.seed_ops import assign_machine_ops, parts_frame, technicians_frame
from pipeline.validate import require_valid
from pipeline.warehouse import connect, insert_df, reset_schema, write_clock


def build_database(
    raw_dir: Path | None = None,
    db_path: Path | None = None,
    *,
    strict_counts: bool = True,
    load_benchmarks: bool = True,
) -> dict[str, int]:
    raw_dir = Path(raw_dir) if raw_dir is not None else RAW_DIR
    db_path = Path(db_path) if db_path is not None else DB_PATH

    frames = load_azure(raw_dir)
    require_valid(frames)
    frames = with_ids(frames)
    frames["machines"] = assign_machine_ops(frames["machines"])

    if db_path.exists():
        db_path.unlink()
    con = connect(db_path)
    try:
        reset_schema(con)
        insert_df(
            con,
            "machines",
            frames["machines"],
            ["machine_id", "model", "age_years", "line", "production_impact"],
        )
        insert_df(con, "technicians", technicians_frame(), ["technician_id", "name", "skill", "shift", "simulated"])
        insert_df(
            con,
            "parts",
            parts_frame(),
            ["part_id", "component", "on_hand", "reorder_point", "lead_time_days", "simulated"],
        )
        insert_df(
            con,
            "sensor_readings",
            frames["telemetry"],
            ["machine_id", "ts", "volt", "rotate", "pressure", "vibration"],
        )
        insert_df(con, "faults", frames["faults"], ["fault_id", "machine_id", "ts", "error_code"])
        insert_df(con, "failures", frames["failures"], ["failure_id", "machine_id", "ts", "component"])
        maint = frames["maintenance"].copy()
        maint["technician_id"] = None
        insert_df(
            con,
            "maintenance_events",
            maint,
            ["event_id", "machine_id", "ts", "component", "type", "technician_id"],
        )
        if load_benchmarks:
            _load_benchmarks(con, raw_dir)
        # Training replaces this with the November demo morning.
        write_clock(
            con,
            pd.Timestamp("2015-11-16 06:00:00"),
            "Placeholder clock. make train moves it to the demo morning.",
        )
        counts = {
            table: int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in (
                "machines",
                "sensor_readings",
                "faults",
                "failures",
                "maintenance_events",
                "parts",
                "technicians",
            )
        }
    finally:
        con.close()

    if strict_counts:
        for table, expected in EXPECTED_COUNTS.items():
            actual = counts[table]
            if actual != expected:
                raise RuntimeError(f"{table} has {actual} rows, expected {expected}")
    return counts


def _load_benchmarks(con, raw_dir: Path) -> None:
    ai4i = load_ai4i(raw_dir)
    insert_df(
        con,
        "bench_ai4i",
        ai4i,
        [
            "udi",
            "product_id",
            "type",
            "air_temp_k",
            "process_temp_k",
            "rpm",
            "torque_nm",
            "tool_wear_min",
            "machine_failure",
            "twf",
            "hdf",
            "pwf",
            "osf",
            "rnf",
        ],
    )
    cycles, rul = load_cmapss_fd001(raw_dir)
    insert_df(
        con,
        "bench_cmapss_fd001",
        cycles,
        ["unit", "cycle", "op1", "op2", "op3"] + [f"s{i}" for i in range(1, 22)] + ["split"],
    )
    insert_df(con, "bench_cmapss_rul", rul, ["unit", "rul"])


def main() -> None:
    print(f"Building {DB_PATH}")
    counts = build_database()
    for table, n in counts.items():
        print(f"  {table:22s} {n:8d}")
    print("Warehouse ready.")


if __name__ == "__main__":
    main()
