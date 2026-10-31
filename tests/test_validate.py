"""Validation must pass a small honest extract and fail a broken one."""

import pandas as pd

from pipeline.validate import validate_azure


def _good() -> dict[str, pd.DataFrame]:
    start = pd.Timestamp("2015-01-01 06:00:00")
    hours = pd.date_range(start, periods=6, freq="h")
    telemetry = pd.DataFrame(
        {
            "machine_id": [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2],
            "ts": list(hours) + list(hours),
            "volt": 170.0,
            "rotate": 450.0,
            "pressure": 100.0,
            "vibration": 40.0,
        }
    )
    return {
        "machines": pd.DataFrame({"machine_id": [1, 2], "model": ["model1", "model3"], "age_years": [4, 12]}),
        "telemetry": telemetry,
        "faults": pd.DataFrame({"machine_id": [1], "ts": [hours[2]], "error_code": ["error1"]}),
        "failures": pd.DataFrame({"machine_id": [1], "ts": [hours[5]], "component": ["comp2"]}),
        "maintenance": pd.DataFrame(
            {"machine_id": [1, 2], "ts": [pd.Timestamp("2014-06-01 06:00:00")] * 2, "component": ["comp1", "comp1"]}
        ),
    }


def test_good_frames_pass():
    assert validate_azure(_good()) == []


def test_duplicate_telemetry_fails():
    frames = _good()
    frames["telemetry"] = pd.concat([frames["telemetry"], frames["telemetry"].iloc[[0]]], ignore_index=True)
    errors = validate_azure(frames)
    assert any("duplicate" in error for error in errors)


def test_unknown_machine_fails():
    frames = _good()
    frames["failures"] = pd.DataFrame(
        {"machine_id": [99], "ts": [pd.Timestamp("2015-01-02 06:00:00")], "component": ["comp1"]}
    )
    errors = validate_azure(frames)
    assert any("missing from machines" in error for error in errors)


def test_null_timestamp_fails():
    frames = _good()
    frames["telemetry"].loc[0, "ts"] = pd.NaT
    errors = validate_azure(frames)
    assert any("null" in error for error in errors)


def test_timestamp_before_maintenance_log_fails():
    frames = _good()
    frames["maintenance"].loc[0, "ts"] = pd.Timestamp("2014-05-01 06:00:00")
    errors = validate_azure(frames)
    assert any("maintenance.ts" in error for error in errors)


def test_telemetry_gap_fails():
    frames = _good()
    frames["telemetry"].loc[frames["telemetry"]["machine_id"].eq(1).idxmax() if False else 2, "ts"] = pd.Timestamp(
        "2015-01-01 12:00:00"
    )
    # idx of the third row of machine 1 is 2 in the constructed frame.
    errors = validate_azure(frames)
    assert any("gaps" in error for error in errors)
