"""Hand-built hourly series for rolling windows, labels, and train/serve parity."""

import numpy as np
import pandas as pd

from models.features import (
    PHRASES,
    add_cycle_rolling,
    add_failure_labels,
    azure_feature_frame,
    feature_columns,
    snapshot_features,
)


def _hourly(n=48, machine_id=1, start="2015-01-01 00:00:00"):
    ts = pd.date_range(start, periods=n, freq="h")
    return pd.DataFrame(
        {
            "machine_id": machine_id,
            "ts": ts,
            "volt": np.arange(1, n + 1, dtype=float),
            "rotate": np.arange(1, n + 1, dtype=float) * 10,
            "pressure": np.full(n, 100.0),
            "vibration": np.linspace(30, 50, n),
        }
    )


def _machines():
    return pd.DataFrame({"machine_id": [1], "model": ["model2"], "age_years": [7]})


def test_feature_names_are_explained():
    for column in feature_columns():
        assert column in PHRASES


def test_rolling_mean_on_a_known_window():
    telemetry = _hourly(6)
    maintenance = pd.DataFrame(columns=["machine_id", "ts", "component"])
    errors = pd.DataFrame(columns=["machine_id", "ts", "error_code"])
    frame = azure_feature_frame(telemetry, errors, maintenance, _machines())
    # Last row volt is 6. Trailing 6 values are 1..6 but min_periods is 6, so the
    # full window is used: mean = 3.5.
    last = frame.iloc[-1]
    assert last["volt_mean_24h"] == 3.5
    assert last["pressure_std_24h"] == 0


def test_error_count_and_hours_since():
    telemetry = _hourly(10)
    errors = pd.DataFrame(
        {
            "machine_id": [1, 1, 1],
            "ts": pd.to_datetime(["2015-01-01 07:00:00", "2015-01-01 08:00:00", "2015-01-01 08:00:00"]),
            "error_code": ["error1", "error1", "error3"],
        }
    )
    maintenance = pd.DataFrame(
        {
            "machine_id": [1],
            "ts": [pd.Timestamp("2015-01-01 02:00:00")],
            "component": ["comp2"],
        }
    )
    frame = azure_feature_frame(telemetry, errors, maintenance, _machines())
    at_eight = frame.loc[frame["ts"].eq(pd.Timestamp("2015-01-01 08:00:00"))].iloc[0]
    assert at_eight["error1_count_24h"] == 2
    assert at_eight["error3_count_24h"] == 1
    assert at_eight["hours_since_comp2"] == 6


def test_label_is_the_next_24_hours_only():
    telemetry = _hourly(30)
    failures = pd.DataFrame({"machine_id": [1], "ts": [pd.Timestamp("2015-01-01 20:00:00")], "component": ["comp4"]})
    labeled = add_failure_labels(telemetry, failures, horizon_hours=24)
    by_ts = labeled.set_index("ts")["y_fail_24h"]
    # 20:00 minus 24 hours is 20:00 the previous day, which is hour 0 of this series? 
    # start 2015-01-01 00:00, failure at 2015-01-01 20:00. Delta at 00:00 is 20 hours.
    assert by_ts.loc[pd.Timestamp("2015-01-01 00:00:00")] == 1
    assert by_ts.loc[pd.Timestamp("2015-01-01 20:00:00")] == 0
    earlier = add_failure_labels(telemetry, failures, horizon_hours=10)
    assert earlier.set_index("ts").loc[pd.Timestamp("2015-01-01 00:00:00"), "y_fail_24h"] == 0
    assert earlier.set_index("ts").loc[pd.Timestamp("2015-01-01 10:00:00"), "y_fail_24h"] == 1


def test_snapshot_matches_full_history_on_the_last_hour():
    telemetry = _hourly(48)
    errors = pd.DataFrame(
        {"machine_id": [1], "ts": [pd.Timestamp("2015-01-02 10:00:00")], "error_code": ["error5"]}
    )
    maintenance = pd.DataFrame(
        {"machine_id": [1, 1], "ts": [pd.Timestamp("2014-12-01 06:00:00"), pd.Timestamp("2015-01-02 00:00:00")], "component": ["comp1", "comp4"]}
    )
    machines = _machines()
    full = azure_feature_frame(telemetry, errors, maintenance, machines)
    as_of = telemetry["ts"].iloc[-1]
    snap = snapshot_features(telemetry, errors, maintenance, machines, as_of)
    columns = feature_columns()
    full_last = full.iloc[-1]
    snap_last = snap.iloc[0]
    for column in columns:
        assert np.isclose(float(snap_last[column]), float(full_last[column]), rtol=1e-9, atol=1e-8), column


def test_int32_keys_from_a_warehouse_still_join():
    telemetry = _hourly(12)
    telemetry["machine_id"] = telemetry["machine_id"].astype("int32")
    errors = pd.DataFrame(
        {
            "machine_id": pd.Series([1], dtype="int32"),
            "ts": [pd.Timestamp("2015-01-01 04:00:00")],
            "error_code": ["error2"],
        }
    )
    maintenance = pd.DataFrame(
        {
            "machine_id": pd.Series([1], dtype="int32"),
            "ts": [pd.Timestamp("2015-01-01 01:00:00")],
            "component": ["comp1"],
        }
    )
    failures = pd.DataFrame(
        {
            "machine_id": pd.Series([1], dtype="int32"),
            "ts": [pd.Timestamp("2015-01-01 10:00:00")],
            "component": ["comp3"],
        }
    )
    machines = _machines()
    machines["machine_id"] = machines["machine_id"].astype("int32")
    frame = azure_feature_frame(telemetry, errors, maintenance, machines, failures=failures)
    at_four = frame.loc[frame["ts"].eq(pd.Timestamp("2015-01-01 04:00:00"))].iloc[0]
    assert at_four["error2_count_24h"] == 1
    assert at_four["hours_since_comp1"] == 3
    assert int(at_four["y_fail_24h"]) == 1


def test_cycle_rolling_mean():
    frame = pd.DataFrame({"unit": [1, 1, 1, 1], "cycle": [1, 2, 3, 4], "s2": [2.0, 4.0, 6.0, 8.0]})
    rolled = add_cycle_rolling(frame, ["s2"], windows=(2,))
    assert rolled["s2_mean_2"].tolist() == [2.0, 3.0, 5.0, 7.0]
    assert rolled["s2_std_2"].iloc[0] == 0
