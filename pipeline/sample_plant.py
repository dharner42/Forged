"""A 12-machine plant the dashboard can open without downloading the datasets.

Scores are authored from the priority formula so the queue, the shift plan, and
the parts page have something honest to show. They are not the Azure model.
The note on the plant clock starts with SAMPLE so the app can tell.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from config import DB_PATH, SERVICE_SUPPRESSION
from models.priority import parts_factor, priority_score
from ontology.model import assert_warehouse_matches_ontology
from pipeline.seed_ops import LINES, parts_frame, shifts_frame, technicians_frame
from pipeline.warehouse import connect, insert_df, reset_schema, write_clock

SAMPLE_PREFIX = "SAMPLE"
SAMPLE_CLOCK = pd.Timestamp("2015-11-23 06:00:00")
SAMPLE_HISTORY_DAYS = 14

# machine_id, model, age, impact, P(fail), component, reason
_SPECS = (
    (1, "model1", 4, 2, 0.05, "comp1", "Low 24-hour failure risk."),
    (2, "model2", 7, 3, 0.08, "comp1", "Low 24-hour failure risk."),
    (3, "model3", 11, 1, 0.04, "comp3", "Low 24-hour failure risk."),
    (
        4,
        "model3",
        14,
        5,
        1.00,
        "comp4",
        "high vibration; recent error5 x1; comp4 last replaced 60 days ago; "
        "comp4 part is out of stock or below reorder point (SIMULATED)",
    ),
    (5, "model4", 18, 2, 0.06, "comp2", "Low 24-hour failure risk."),
    (
        6,
        "model2",
        9,
        4,
        1.00,
        "comp2",
        "recent error2 x1; comp2 last replaced 60 days ago; "
        "comp2 part is out of stock or below reorder point (SIMULATED)",
    ),
    (7, "model4", 16, 3, 0.80, "comp1", "comp1 last replaced 60 days ago"),
    (8, "model1", 5, 1, 0.03, "comp3", "Low 24-hour failure risk."),
    (9, "model1", 8, 2, 1.00, "comp3", "comp3 last replaced 60 days ago"),
    (
        10,
        "model2",
        10,
        4,
        0.12,
        "comp4",
        "Low 24-hour failure risk. comp4 part is out of stock or below its reorder point (SIMULATED). "
        "That changes the parts factor, not the failure probability.",
    ),
    (11, "model3", 6, 2, 0.07, "comp1", "Low 24-hour failure risk."),
    (
        12,
        "model4",
        20,
        5,
        0.09,
        "comp2",
        "Low 24-hour failure risk. comp2 part is out of stock or below its reorder point (SIMULATED). "
        "That changes the parts factor, not the failure probability.",
    ),
)


def is_sample_note(note) -> bool:
    return bool(note) and str(note).startswith(SAMPLE_PREFIX)


def sample_note(detail: str) -> str:
    return f"{SAMPLE_PREFIX}: {detail}"


def sample_history_start() -> pd.Timestamp:
    return SAMPLE_CLOCK - pd.Timedelta(days=SAMPLE_HISTORY_DAYS)


def _band(p_fail: float) -> str:
    if p_fail >= 1.0:
        return "red"
    if p_fail >= 0.5:
        return "amber"
    return "green"


def _stock() -> dict[str, tuple[float, float]]:
    frame = parts_frame()
    return {
        str(row.component): (float(row.on_hand), float(row.reorder_point))
        for row in frame.itertuples(index=False)
    }


def score_specs(scale: float = 1.0) -> pd.DataFrame:
    """Priority scores for the 12 machines. ``scale`` shrinks probability on earlier mornings."""
    stock = _stock()
    rows = []
    for machine_id, model, age, impact, p_fail, component, reason in _SPECS:
        on_hand, reorder = stock[component]
        p_value = min(1.0, float(p_fail) * float(scale))
        factor = parts_factor(on_hand, reorder)
        rows.append(
            {
                "machine_id": machine_id,
                "model": model,
                "age_years": age,
                "line": LINES[(machine_id - 1) % len(LINES)],
                "production_impact": impact,
                "p_fail_24h": p_value,
                "predicted_component": component,
                "parts_factor": factor,
                "priority_score": priority_score(p_value, impact, on_hand, reorder),
                "queue_score": priority_score(p_value, impact, on_hand, reorder),
                "band": _band(p_value),
                "top_reason": reason,
                "serviced_within_24h": False,
                "contrib_json": None,
            }
        )
    return pd.DataFrame(rows)


def build_sample_plant(db_path: Path | None = None) -> Path:
    path = Path(db_path) if db_path is not None else DB_PATH
    if path.exists():
        path.unlink()
    scored = score_specs(1.0)
    con = connect(path)
    try:
        reset_schema(con)
        machines = scored[["machine_id", "model", "age_years", "line", "production_impact"]]
        insert_df(con, "machines", machines, ["machine_id", "model", "age_years", "line", "production_impact"])
        insert_df(con, "shifts", shifts_frame(), ["shift_id", "name", "start_hour", "end_hour", "simulated"])
        insert_df(con, "technicians", technicians_frame(), ["technician_id", "name", "skill", "shift", "simulated"])
        insert_df(
            con,
            "parts",
            parts_frame(),
            ["part_id", "component", "on_hand", "reorder_point", "lead_time_days", "simulated"],
        )
        _insert_telemetry(con, scored["machine_id"].tolist())
        _insert_events(con)
        current = scored.copy()
        current["ts"] = SAMPLE_CLOCK
        insert_df(
            con,
            "current_scores",
            current,
            [
                "machine_id",
                "ts",
                "p_fail_24h",
                "predicted_component",
                "parts_factor",
                "priority_score",
                "queue_score",
                "band",
                "top_reason",
                "serviced_within_24h",
                "contrib_json",
            ],
        )
        _insert_mornings(con)
        write_clock(
            con,
            SAMPLE_CLOCK,
            sample_note(
                "12-machine plant with authored scores. Not the Azure 2015 warehouse. "
                "Machine 4 is the worked example: probability 1, impact 5, comp4 out of stock, priority 7.50."
            ),
        )
        assert_warehouse_matches_ontology(con)
    finally:
        con.close()
    return path


def ensure_demo_warehouse(db_path: Path | None = None) -> Path:
    """Create the sample plant only when the warehouse file is missing."""
    path = Path(db_path) if db_path is not None else DB_PATH
    if path.exists():
        return path
    return build_sample_plant(path)


def move_sample_clock(con, as_of) -> None:
    """Move the clock and load the latest stored morning at or before it.

    The Azure model is not loaded. Repair suppression does not survive a clock
    move, because the stored mornings were scored before any repair you logged.
    """
    as_of = pd.Timestamp(as_of)
    row = con.execute("SELECT max(ts) FROM predictions WHERE ts <= ?", [as_of.to_pydatetime()]).fetchone()
    if row is not None and row[0] is not None:
        morning = pd.Timestamp(row[0])
        frame = con.execute(
            """
            SELECT machine_id, p_fail_24h, predicted_component, parts_factor,
                   priority_score, queue_score, band, top_reason
            FROM predictions WHERE ts = ?
            """,
            [morning.to_pydatetime()],
        ).fetchdf()
        frame["ts"] = as_of
        frame["serviced_within_24h"] = False
        frame["contrib_json"] = None
        con.execute("DELETE FROM current_scores")
        insert_df(
            con,
            "current_scores",
            frame,
            [
                "machine_id",
                "ts",
                "p_fail_24h",
                "predicted_component",
                "parts_factor",
                "priority_score",
                "queue_score",
                "band",
                "top_reason",
                "serviced_within_24h",
                "contrib_json",
            ],
        )
        detail = f"Scores are the stored morning of {morning:%Y-%m-%d %H:%M}. The Azure model is not rerun."
    else:
        detail = "No stored morning at or before this hour. Scores were left as they were."
    write_clock(con, as_of, sample_note(detail))


def suppress_after_repair(con, machine_id: int) -> None:
    """Apply the 24-hour shop rule without rescoring the Azure model."""
    row = con.execute(
        "SELECT priority_score, top_reason FROM current_scores WHERE machine_id = ?",
        [int(machine_id)],
    ).fetchone()
    if row is None:
        return
    priority = float(row[0])
    reason = str(row[1])
    if not reason.startswith("Serviced in the last 24 hours"):
        reason = "Serviced in the last 24 hours, so the queue score is reduced. " + reason
    con.execute(
        """
        UPDATE current_scores
        SET queue_score = ?, serviced_within_24h = TRUE, top_reason = ?
        WHERE machine_id = ?
        """,
        [priority * SERVICE_SUPPRESSION, reason, int(machine_id)],
    )


def _insert_telemetry(con, machine_ids: list[int]) -> None:
    rng = np.random.default_rng(42)
    hours = pd.date_range(sample_history_start(), SAMPLE_CLOCK, freq="h")
    rows = []
    for machine_id in machine_ids:
        vibration_base = 62.0 if int(machine_id) == 4 else 40.0
        for ts in hours:
            rows.append(
                {
                    "machine_id": int(machine_id),
                    "ts": ts,
                    "volt": 170.0 + float(rng.normal(0, 2)),
                    "rotate": 450.0 + float(rng.normal(0, 5)),
                    "pressure": 100.0 + float(rng.normal(0, 1.5)),
                    "vibration": vibration_base + float(rng.normal(0, 1.2)),
                }
            )
    insert_df(
        con,
        "sensor_readings",
        pd.DataFrame(rows),
        ["machine_id", "ts", "volt", "rotate", "pressure", "vibration"],
    )


def _insert_events(con) -> None:
    faults = pd.DataFrame(
        [
            {"fault_id": 1, "machine_id": 4, "ts": SAMPLE_CLOCK - pd.Timedelta(hours=5), "error_code": "error5"},
            {"fault_id": 2, "machine_id": 6, "ts": SAMPLE_CLOCK - pd.Timedelta(hours=8), "error_code": "error2"},
            {"fault_id": 3, "machine_id": 9, "ts": SAMPLE_CLOCK - pd.Timedelta(hours=20), "error_code": "error3"},
        ]
    )
    insert_df(con, "faults", faults, ["fault_id", "machine_id", "ts", "error_code"])
    failures = pd.DataFrame(
        [
            {"failure_id": 1, "machine_id": 4, "ts": SAMPLE_CLOCK - pd.Timedelta(days=40), "component": "comp4"},
            {"failure_id": 2, "machine_id": 1, "ts": SAMPLE_CLOCK - pd.Timedelta(days=20), "component": "comp1"},
            {"failure_id": 3, "machine_id": 6, "ts": SAMPLE_CLOCK - pd.Timedelta(days=12), "component": "comp2"},
        ]
    )
    insert_df(con, "failures", failures, ["failure_id", "machine_id", "ts", "component"])
    replaced = SAMPLE_CLOCK - pd.Timedelta(days=60)
    events = []
    event_id = 1
    for machine_id, *_rest in _SPECS:
        for component in ("comp1", "comp2", "comp3", "comp4"):
            events.append(
                {
                    "event_id": event_id,
                    "machine_id": machine_id,
                    "ts": replaced,
                    "component": component,
                    "type": "scheduled",
                    "technician_id": None,
                }
            )
            event_id += 1
    insert_df(
        con,
        "maintenance_events",
        pd.DataFrame(events),
        ["event_id", "machine_id", "ts", "component", "type", "technician_id"],
    )


def _insert_mornings(con) -> None:
    mornings = pd.date_range(sample_history_start(), SAMPLE_CLOCK, freq="D")
    frames = []
    last = len(mornings) - 1
    for index, morning in enumerate(mornings):
        scale = 0.35 + 0.65 * (index / last if last else 1.0)
        day = score_specs(scale)
        day["ts"] = pd.Timestamp(morning)
        frames.append(day)
    all_days = pd.concat(frames, ignore_index=True)
    insert_df(
        con,
        "predictions",
        all_days,
        [
            "machine_id",
            "ts",
            "p_fail_24h",
            "predicted_component",
            "parts_factor",
            "priority_score",
            "queue_score",
            "band",
            "top_reason",
        ],
    )
