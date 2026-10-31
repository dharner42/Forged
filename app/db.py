"""Read and write the warehouse for the dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from app.bootstrap import install

install(Path(__file__))

from config import DB_PATH, METRICS_PATH  # noqa: E402
from models.shift_plan import shift_name  # noqa: E402
from pipeline.seed_ops import pick_technician  # noqa: E402
from pipeline.warehouse import connect, read_clock  # noqa: E402


def connection():
    if not DB_PATH.exists():
        return None
    if "forge_con" not in st.session_state:
        st.session_state["forge_con"] = connect(DB_PATH)
    return st.session_state["forge_con"]


def metrics() -> dict | None:
    if not METRICS_PATH.exists():
        return None
    return json.loads(METRICS_PATH.read_text())


def plant_clock(con) -> pd.Timestamp:
    return read_clock(con)


def fleet(con) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            cs.machine_id,
            m.model,
            m.age_years,
            m.line,
            m.production_impact,
            cs.ts,
            cs.p_fail_24h,
            cs.predicted_component,
            cs.parts_factor,
            cs.priority_score,
            cs.queue_score,
            cs.band,
            cs.top_reason,
            cs.serviced_within_24h,
            cs.contrib_json,
            p.on_hand,
            p.reorder_point,
            p.lead_time_days,
            w.work_order_id,
            w.technician_id,
            t.name AS technician_name,
            t.shift AS technician_shift
        FROM current_scores cs
        JOIN machines m ON m.machine_id = cs.machine_id
        LEFT JOIN parts p ON p.component = cs.predicted_component
        LEFT JOIN work_orders w
            ON w.machine_id = cs.machine_id AND w.status = 'open'
        LEFT JOIN technicians t ON t.technician_id = w.technician_id
        ORDER BY cs.queue_score DESC, cs.p_fail_24h DESC, cs.machine_id
        """
    ).fetchdf()


def morning_history(con, as_of: pd.Timestamp) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            ts,
            avg(p_fail_24h) AS mean_p,
            sum(CASE WHEN band = 'red' THEN 1 ELSE 0 END) AS reds,
            sum(CASE WHEN band = 'amber' THEN 1 ELSE 0 END) AS ambers,
            sum(CASE WHEN band = 'green' THEN 1 ELSE 0 END) AS greens
        FROM predictions
        WHERE ts <= ?
        GROUP BY ts
        ORDER BY ts
        """,
        [as_of.to_pydatetime()],
    ).fetchdf()


def sensor_history(con, machine_id: int, as_of: pd.Timestamp, days: int = 14) -> pd.DataFrame:
    start = as_of - pd.Timedelta(days=days)
    return con.execute(
        """
        SELECT ts, volt, rotate, pressure, vibration
        FROM sensor_readings
        WHERE machine_id = ? AND ts <= ? AND ts >= ?
        ORDER BY ts
        """,
        [machine_id, as_of.to_pydatetime(), start.to_pydatetime()],
    ).fetchdf()


def machine_events(con, machine_id: int, as_of: pd.Timestamp) -> dict[str, pd.DataFrame]:
    stamp = as_of.to_pydatetime()
    faults = con.execute(
        """
        SELECT ts, error_code FROM faults
        WHERE machine_id = ? AND ts <= ?
        ORDER BY ts DESC LIMIT 12
        """,
        [machine_id, stamp],
    ).fetchdf()
    maintenance = con.execute(
        """
        SELECT ts, component, type, technician_id
        FROM maintenance_events
        WHERE machine_id = ? AND ts <= ?
        ORDER BY ts DESC LIMIT 12
        """,
        [machine_id, stamp],
    ).fetchdf()
    failures = con.execute(
        """
        SELECT ts, component FROM failures
        WHERE machine_id = ? AND ts <= ?
        ORDER BY ts DESC LIMIT 8
        """,
        [machine_id, stamp],
    ).fetchdf()
    return {"faults": faults, "maintenance": maintenance, "failures": failures}


def parts_table(con) -> pd.DataFrame:
    return con.execute(
        """
        SELECT part_id, component, on_hand, reorder_point, lead_time_days, simulated
        FROM parts ORDER BY part_id
        """
    ).fetchdf()


def technicians(con) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            t.technician_id,
            t.name,
            t.skill,
            t.shift,
            t.simulated,
            count(w.work_order_id) AS open_work_orders
        FROM technicians t
        LEFT JOIN work_orders w
            ON w.technician_id = t.technician_id AND w.status = 'open'
        GROUP BY t.technician_id, t.name, t.skill, t.shift, t.simulated
        ORDER BY t.technician_id
        """
    ).fetchdf()


def open_work_orders(con, as_of: pd.Timestamp) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            w.work_order_id,
            w.machine_id,
            w.component,
            w.priority_score,
            w.opened_ts,
            w.reason,
            t.name AS technician_name,
            t.skill,
            m.line
        FROM work_orders w
        JOIN technicians t ON t.technician_id = w.technician_id
        JOIN machines m ON m.machine_id = w.machine_id
        WHERE w.status = 'open' AND w.opened_ts <= ?
        ORDER BY w.priority_score DESC
        """,
        [as_of.to_pydatetime()],
    ).fetchdf()


def create_work_order(con, machine_id: int) -> str:
    clock = plant_clock(con)
    existing = con.execute(
        """
        SELECT work_order_id FROM work_orders
        WHERE machine_id = ? AND status = 'open' AND opened_ts <= ?
        """,
        [int(machine_id), clock.to_pydatetime()],
    ).fetchone()
    if existing:
        return f"Work order {existing[0]} is already open for machine {machine_id}."
    row = con.execute(
        """
        SELECT predicted_component, priority_score, top_reason
        FROM current_scores WHERE machine_id = ?
        """,
        [int(machine_id)],
    ).fetchone()
    if row is None:
        return "That machine has no score at the current plant clock."
    component, priority, reason = row
    techs = con.execute("SELECT technician_id, name, skill, shift, simulated FROM technicians").fetchdf()
    counts = con.execute(
        "SELECT technician_id, count(*) AS n FROM work_orders WHERE status = 'open' GROUP BY 1"
    ).fetchdf()
    open_counts = {int(item.technician_id): int(item.n) for item in counts.itertuples(index=False)}
    tech_id = pick_technician(techs, open_counts, str(component))
    tech_name = techs.loc[techs.technician_id.eq(tech_id), "name"].iloc[0]
    skill = techs.loc[techs.technician_id.eq(tech_id), "skill"].iloc[0]
    tech_shift = techs.loc[techs.technician_id.eq(tech_id), "shift"].iloc[0]
    current_shift = shift_name(clock)
    if tech_shift == current_shift:
        shift_note = f" {tech_name} is on the {current_shift} shift."
    else:
        shift_note = f" {tech_name} works the {tech_shift} shift, not {current_shift}."
    next_id = int(con.execute("SELECT coalesce(max(work_order_id), 0) + 1 FROM work_orders").fetchone()[0])
    con.execute(
        """
        INSERT INTO work_orders (
            work_order_id, machine_id, component, status, priority_score,
            opened_ts, closed_ts, technician_id, reason
        ) VALUES (?, ?, ?, 'open', ?, ?, NULL, ?, ?)
        """,
        [next_id, int(machine_id), str(component), float(priority), clock.to_pydatetime(), tech_id, reason],
    )
    return (
        f"Opened work order {next_id} for machine {machine_id}, {component}, "
        f"assigned to {tech_name} ({skill}).{shift_note} The roster is SIMULATED."
    )


def mark_repaired(con, work_order_id: int) -> str:
    clock = plant_clock(con)
    row = con.execute(
        """
        SELECT machine_id, component, status, technician_id
        FROM work_orders WHERE work_order_id = ?
        """,
        [int(work_order_id)],
    ).fetchone()
    if row is None:
        return "Work order not found."
    machine_id, component, status, tech_id = row
    if status != "open":
        return f"Work order {work_order_id} is already {status}."
    event_id = int(con.execute("SELECT coalesce(max(event_id), 0) + 1 FROM maintenance_events").fetchone()[0])
    stock = con.execute("SELECT on_hand FROM parts WHERE component = ?", [component]).fetchone()
    con.execute("BEGIN")
    try:
        con.execute(
            "UPDATE work_orders SET status = 'closed', closed_ts = ? WHERE work_order_id = ?",
            [clock.to_pydatetime(), int(work_order_id)],
        )
        con.execute(
            """
            INSERT INTO maintenance_events (event_id, machine_id, ts, component, type, technician_id)
            VALUES (?, ?, ?, ?, 'unscheduled', ?)
            """,
            [event_id, int(machine_id), clock.to_pydatetime(), component, int(tech_id) if tech_id is not None else None],
        )
        if stock is None:
            stock_note = "No part row matched this component."
        elif int(stock[0]) > 0:
            con.execute("UPDATE parts SET on_hand = on_hand - 1 WHERE component = ?", [component])
            stock_note = f"{component} stock is now {int(stock[0]) - 1} (SIMULATED)."
        else:
            stock_note = f"{component} was already at 0, so stock did not change (SIMULATED)."
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    from models.score import score_current

    score_current(clock, con=con, note="Rescored after a repair logged at the plant clock.")
    return (
        f"Closed work order {work_order_id}. Logged an unscheduled {component} replacement "
        f"at the plant clock. {stock_note} The queue was rescored, and a machine serviced "
        f"in the last 24 hours moves down."
    )


def move_clock(con, as_of: pd.Timestamp) -> None:
    from models.score import score_current

    score_current(as_of, con=con, note="Plant clock moved from the dashboard.")
