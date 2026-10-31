"""The priority formula, the service rule, and the fix-first ranking."""

import pandas as pd
import pytest

from models.features import COMPONENTS, ERROR_CODES, SENSOR_COLS
from models.priority import (
    assemble_queue,
    build_reason,
    parts_factor,
    priority_score,
    queue_score,
)
from pipeline.seed_ops import pick_technician, technicians_frame
from pipeline.warehouse import connect, reset_schema


def test_worked_example_matches_the_formula():
    # P(fail) 0.40, impact 5, part out of stock -> 0.40 x 5 x 1.5 = 3.00
    assert priority_score(0.40, 5, on_hand=0, reorder_point=2) == pytest.approx(3.0)
    # Same machine with the part in stock.
    assert priority_score(0.40, 5, on_hand=3, reorder_point=2) == pytest.approx(2.0)
    # At the reorder point is not "below" it.
    assert parts_factor(2, 2) == 1.0
    assert parts_factor(1, 4) == 1.5
    # Just serviced: queue score = 3.00 x 0.15 = 0.45
    assert queue_score(3.0, serviced_within_24h=True) == pytest.approx(0.45)
    assert queue_score(3.0, serviced_within_24h=False) == pytest.approx(3.0)


def test_reason_names_the_part_shortage_as_simulated():
    text = build_reason(
        predicted_component="comp2",
        hours_since=400 * 24,
        sensor_means={
            "volt_mean_24h": 170,
            "rotate_mean_24h": 450,
            "pressure_mean_24h": 100,
            "vibration_mean_24h": 55,
        },
        sensor_p75={
            "volt_mean_24h": 180,
            "rotate_mean_24h": 470,
            "pressure_mean_24h": 110,
            "vibration_mean_24h": 45,
        },
        error_counts={"error1": 0, "error2": 2, "error3": 0, "error4": 0, "error5": 0},
        parts_tight=True,
        serviced=False,
    )
    assert "high vibration" in text
    assert "error2 x2" in text
    assert "400 days" in text
    assert "SIMULATED" in text


def test_low_risk_does_not_read_like_an_alarm():
    text = build_reason(
        predicted_component="comp4",
        hours_since=100,
        sensor_means={"vibration_mean_24h": 80, "volt_mean_24h": 1, "rotate_mean_24h": 1, "pressure_mean_24h": 1},
        sensor_p75={"vibration_mean_24h": 40, "volt_mean_24h": 1, "rotate_mean_24h": 1, "pressure_mean_24h": 1},
        error_counts={"error1": 3, "error2": 0, "error3": 0, "error4": 0, "error5": 0},
        parts_tight=True,
        serviced=False,
        low_risk=True,
    )
    assert text.startswith("Low 24-hour failure risk")
    assert "SIMULATED" in text
    assert "high vibration" not in text


def test_recent_service_is_prefixed():
    text = build_reason(
        predicted_component="comp1",
        hours_since=3,
        sensor_means={f"{s}_mean_24h": 1 for s in SENSOR_COLS},
        sensor_p75={f"{s}_mean_24h": 10 for s in SENSOR_COLS},
        error_counts={code: 0 for code in ERROR_CODES},
        parts_tight=False,
        serviced=True,
    )
    assert text.startswith("Serviced in the last 24 hours")
    assert "SIMULATED" not in text


def _queue_row(machine_id, p_fail, impact, on_hand, hours):
    row = {
        "machine_id": machine_id,
        "ts": pd.Timestamp("2015-11-16 06:00:00"),
        "p_fail_24h": p_fail,
        "predicted_component": "comp4",
        "production_impact": impact,
        "on_hand": on_hand,
        "reorder_point": 2,
    }
    for sensor in SENSOR_COLS:
        row[f"{sensor}_mean_24h"] = 10.0
    for code in ERROR_CODES:
        row[f"{code}_count_24h"] = 0.0
    for component in COMPONENTS:
        row[f"hours_since_{component}"] = hours
    return row


def test_impact_and_parts_can_outrank_a_higher_probability():
    frame = pd.DataFrame(
        [
            _queue_row(1, p_fail=0.50, impact=1, on_hand=6, hours=500),
            _queue_row(2, p_fail=0.20, impact=5, on_hand=0, hours=500),
        ]
    )
    ranked = assemble_queue(frame, red_at=0.4, amber_at=0.15)
    top = ranked.sort_values(["queue_score", "machine_id"], ascending=[False, True]).iloc[0]
    assert int(top.machine_id) == 2
    assert top.priority_score == pytest.approx(1.5)
    assert ranked.loc[ranked.machine_id.eq(1), "band"].iloc[0] == "red"
    assert ranked.loc[ranked.machine_id.eq(2), "band"].iloc[0] == "amber"


def test_any_recent_replacement_suppresses_the_queue_score():
    fresh = assemble_queue(pd.DataFrame([_queue_row(7, 0.4, 5, 0, hours=2)]), red_at=0.9, amber_at=0.5)
    stale = assemble_queue(pd.DataFrame([_queue_row(7, 0.4, 5, 0, hours=200)]), red_at=0.9, amber_at=0.5)
    assert fresh.iloc[0].serviced_within_24h
    assert fresh.iloc[0].queue_score == pytest.approx(stale.iloc[0].priority_score * 0.15)
    assert fresh.iloc[0].priority_score == pytest.approx(stale.iloc[0].priority_score)


def test_technician_match_prefers_skill_then_workload():
    techs = technicians_frame()
    # comp2 is the simulated hydraulics skill. Shah is the only hydraulics tech.
    assert pick_technician(techs, {}, "comp2") == 5
    # Two mechanical techs. The one with an open job loses.
    assert pick_technician(techs, {1: 2, 2: 0}, "comp1") == 2


def test_fix_first_view_returns_a_reason_and_a_rank(tmp_path):
    con = connect(tmp_path / "rank.duckdb")
    reset_schema(con)
    machines = pd.DataFrame(
        {
            "machine_id": [1, 2, 3],
            "model": ["model1", "model2", "model3"],
            "age_years": [4, 10, 18],
            "line": ["Machining", "Assembly", "Test"],
            "production_impact": [2, 5, 1],
        }
    )
    scores = pd.DataFrame(
        {
            "machine_id": [1, 2, 3],
            "ts": [pd.Timestamp("2015-11-16 06:00:00")] * 3,
            "p_fail_24h": [0.2, 0.3, 0.9],
            "predicted_component": ["comp1", "comp4", "comp2"],
            "parts_factor": [1.0, 1.5, 1.0],
            "priority_score": [0.4, 2.25, 0.9],
            "queue_score": [0.4, 2.25, 0.9],
            "band": ["amber", "red", "red"],
            "top_reason": ["age", "part out of stock (SIMULATED)", "vibration"],
            "serviced_within_24h": [False, False, False],
            "contrib_json": [None, None, None],
        }
    )
    con.register("machines_df", machines)
    con.register("scores_df", scores)
    con.execute("INSERT INTO machines SELECT * FROM machines_df")
    con.execute("INSERT INTO current_scores SELECT * FROM scores_df")
    top = con.execute("SELECT machine_id, rank, top_reason FROM fix_first ORDER BY rank LIMIT 10").fetchdf()
    con.close()
    assert top.iloc[0]["machine_id"] == 2
    assert top.iloc[0]["rank"] == 1
    assert "SIMULATED" in top.iloc[0]["top_reason"]
    assert list(top["rank"]) == [1, 2, 3]
