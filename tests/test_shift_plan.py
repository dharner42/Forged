"""The shift plan uses the simulated roster. It does not change the priority score."""

import pandas as pd

from models.shift_plan import plan_shift, shift_name
from pipeline.seed_ops import technicians_frame


def _fleet():
    return pd.DataFrame(
        [
            {
                "machine_id": 19,
                "band": "red",
                "predicted_component": "comp4",
                "queue_score": 7.5,
                "on_hand": 0,
                "reorder_point": 2,
                "lead_time_days": 21,
                "work_order_id": None,
                "technician_id": None,
            },
            {
                "machine_id": 61,
                "band": "red",
                "predicted_component": "comp2",
                "queue_score": 7.5,
                "on_hand": 1,
                "reorder_point": 4,
                "lead_time_days": 14,
                "work_order_id": None,
                "technician_id": None,
            },
            {
                "machine_id": 77,
                "band": "red",
                "predicted_component": "comp1",
                "queue_score": 2.0,
                "on_hand": 8,
                "reorder_point": 3,
                "lead_time_days": 5,
                "work_order_id": None,
                "technician_id": None,
            },
            {
                "machine_id": 4,
                "band": "green",
                "predicted_component": "comp1",
                "queue_score": 0.0,
                "on_hand": 8,
                "reorder_point": 3,
                "lead_time_days": 5,
                "work_order_id": None,
                "technician_id": None,
            },
        ]
    )


def test_demo_morning_does_not_start_the_top_machine():
    assert shift_name("2015-11-23 06:00") == "day"
    plan = plan_shift(_fleet(), technicians_frame(), "2015-11-23 06:00")
    assert list(plan.work_now["machine_id"]) == [61, 77]
    assert list(plan.work_now["technician_name"]) == ["E. Shah", "A. Rivera"]
    assert list(plan.blocked["machine_id"]) == [19]
    note = plan.note_for(19)
    assert "out of stock" in note
    assert "day shift" in note
    assert "21-day" in note
    assert plan.note_for(4) is None


def test_a_second_job_for_the_same_skill_waits():
    fleet = _fleet()
    extra = fleet.iloc[[2]].copy()
    extra["machine_id"] = 78
    extra["queue_score"] = 1.5
    plan = plan_shift(pd.concat([fleet, extra], ignore_index=True), technicians_frame(), "2015-11-23 06:00")
    assert 78 in set(plan.deferred["machine_id"])
    assert "already booked" in plan.note_for(78)


def test_shift_boundaries():
    assert shift_name("2015-11-23 05:00") == "night"
    assert shift_name("2015-11-23 14:00") == "swing"
    assert shift_name("2015-11-23 22:00") == "night"
    night = plan_shift(_fleet(), technicians_frame(), "2015-11-23 23:00")
    assert list(night.on_duty["name"]) == ["D. Petrov"]
