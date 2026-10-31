"""Feature engineering shared by training and the dashboard.

Azure telemetry in this dataset is a complete hourly grid, so a rolling window of
24 rows is a rolling window of 24 hours. The snapshot used at the plant clock
calls the same functions on the recent rows only. Tests check that the last row
matches the full-history row.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import FAILURE_HORIZON_HOURS

SENSOR_COLS = ["volt", "rotate", "pressure", "vibration"]
ERROR_CODES = [f"error{i}" for i in range(1, 6)]
COMPONENTS = [f"comp{i}" for i in range(1, 5)]
MODEL_LEVELS = ["model1", "model2", "model3", "model4"]
WINDOW = 24
MIN_PERIODS = 6
CENSOR_ORIGIN = pd.Timestamp("2014-06-01 06:00:00")

PHRASES = {
    "volt_mean_24h": "24-hour average voltage",
    "volt_std_24h": "24-hour voltage variability",
    "rotate_mean_24h": "24-hour average rotation",
    "rotate_std_24h": "24-hour rotation variability",
    "pressure_mean_24h": "24-hour average pressure",
    "pressure_std_24h": "24-hour pressure variability",
    "vibration_mean_24h": "24-hour average vibration",
    "vibration_std_24h": "24-hour vibration variability",
    "error1_count_24h": "error1 count in the last 24 hours",
    "error2_count_24h": "error2 count in the last 24 hours",
    "error3_count_24h": "error3 count in the last 24 hours",
    "error4_count_24h": "error4 count in the last 24 hours",
    "error5_count_24h": "error5 count in the last 24 hours",
    "hours_since_comp1": "hours since comp1 was replaced",
    "hours_since_comp2": "hours since comp2 was replaced",
    "hours_since_comp3": "hours since comp3 was replaced",
    "hours_since_comp4": "hours since comp4 was replaced",
    "age_years": "machine age in years",
    "is_model2": "model is model2 rather than model1",
    "is_model3": "model is model3 rather than model1",
    "is_model4": "model is model4 rather than model1",
}


def feature_columns() -> list[str]:
    columns: list[str] = []
    for sensor in SENSOR_COLS:
        columns.append(f"{sensor}_mean_24h")
        columns.append(f"{sensor}_std_24h")
    columns.extend(f"{code}_count_24h" for code in ERROR_CODES)
    columns.extend(f"hours_since_{component}" for component in COMPONENTS)
    columns.append("age_years")
    columns.extend(f"is_{level}" for level in MODEL_LEVELS if level != "model1")
    return columns


def add_sensor_rolling(df: pd.DataFrame, window: int = WINDOW, min_periods: int = MIN_PERIODS) -> pd.DataFrame:
    """Add mean and std over the trailing `window` rows. Caller must sort by machine, time."""
    out = df.copy()
    grouped = out.groupby("machine_id", sort=False)
    for sensor in SENSOR_COLS:
        means = grouped[sensor].rolling(window, min_periods=min_periods).mean().reset_index(level=0, drop=True)
        stds = grouped[sensor].rolling(window, min_periods=min_periods).std().reset_index(level=0, drop=True)
        out[f"{sensor}_mean_24h"] = means.to_numpy()
        out[f"{sensor}_std_24h"] = stds.to_numpy()
        out[f"{sensor}_mean_24h"] = out[f"{sensor}_mean_24h"].fillna(out[sensor])
        out[f"{sensor}_std_24h"] = out[f"{sensor}_std_24h"].fillna(0.0)
    return out


def _align_keys(df: pd.DataFrame) -> pd.DataFrame:
    """DuckDB returns INTEGER as int32 and timestamps as microsecond resolution.

    merge_asof refuses to join those to pandas int64 / nanosecond timestamps.
    """
    if df is None:
        return df
    out = df.copy()
    if "machine_id" in out.columns:
        out["machine_id"] = out["machine_id"].astype("int64")
    for column in ("ts", "event_ts", "fail_ts"):
        if column in out.columns:
            out[column] = pd.to_datetime(out[column])
    return out


def add_error_counts(df: pd.DataFrame, errors: pd.DataFrame, window: int = WINDOW) -> pd.DataFrame:
    out = _align_keys(df).sort_values(["machine_id", "ts"]).reset_index(drop=True)
    errors = _align_keys(errors) if errors is not None else errors
    if errors is None or errors.empty:
        for code in ERROR_CODES:
            out[f"{code}_count_24h"] = 0.0
        return out
    err = errors.copy()
    err["hit"] = 1
    pivot = (
        err.pivot_table(index=["machine_id", "ts"], columns="error_code", values="hit", aggfunc="sum", fill_value=0)
        .reset_index()
    )
    for code in ERROR_CODES:
        if code not in pivot.columns:
            pivot[code] = 0
    before = len(out)
    out = out.merge(pivot[["machine_id", "ts", *ERROR_CODES]], on=["machine_id", "ts"], how="left")
    if len(out) != before:
        raise RuntimeError("error merge duplicated telemetry rows")
    for code in ERROR_CODES:
        out[code] = out[code].fillna(0.0)
    grouped = out.groupby("machine_id", sort=False)
    for code in ERROR_CODES:
        rolled = grouped[code].rolling(window, min_periods=1).sum().reset_index(level=0, drop=True)
        out[f"{code}_count_24h"] = rolled.to_numpy()
    return out.drop(columns=list(ERROR_CODES))


def add_hours_since(df: pd.DataFrame, maintenance: pd.DataFrame) -> pd.DataFrame:
    """Hours since the latest replacement of each component at or before the row."""
    out = _align_keys(df)
    base = out[["machine_id", "ts"]].copy()
    base["_row"] = np.arange(len(base))
    maint = _align_keys(maintenance) if maintenance is not None else pd.DataFrame(columns=["machine_id", "ts", "component"])
    for component in COMPONENTS:
        events = maint.loc[maint["component"] == component, ["machine_id", "ts"]].rename(columns={"ts": "event_ts"})
        events = events.sort_values("event_ts").drop_duplicates(["machine_id", "event_ts"], keep="last")
        left = base.sort_values("ts")
        if events.empty:
            hours = (left["ts"] - CENSOR_ORIGIN).dt.total_seconds() / 3600
            left = left.copy()
            left["hours"] = hours.to_numpy()
        else:
            merged = pd.merge_asof(
                left,
                events,
                left_on="ts",
                right_on="event_ts",
                by="machine_id",
                direction="backward",
            )
            hours = (merged["ts"] - merged["event_ts"]).dt.total_seconds() / 3600
            missing = hours.isna()
            if bool(missing.any()):
                censored = (merged["ts"] - CENSOR_ORIGIN).dt.total_seconds() / 3600
                hours = hours.mask(missing, censored)
            merged = merged.copy()
            merged["hours"] = hours
            left = merged
        left = left.sort_values("_row")
        out[f"hours_since_{component}"] = left["hours"].to_numpy()
    return out


def add_model_dummies(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    dummies = pd.get_dummies(out["model"], prefix="is")
    for level in MODEL_LEVELS:
        column = f"is_{level}"
        if column not in dummies.columns:
            dummies[column] = 0
    # model1 is the reference level so a linear model is identifiable.
    for level in MODEL_LEVELS:
        if level == "model1":
            continue
        out[f"is_{level}"] = dummies[f"is_{level}"].astype(float).to_numpy()
    return out


def add_failure_labels(df: pd.DataFrame, failures: pd.DataFrame, horizon_hours: int = FAILURE_HORIZON_HOURS) -> pd.DataFrame:
    """Label 1 when a failure happens after this hour and within the horizon.

    A failure at exactly this timestamp is not a future failure. If two components
    fail at the same timestamp, the label stays 1 and the component is the first
    in alphabetical order.
    """
    out = _align_keys(df)
    base = out[["machine_id", "ts"]].copy()
    base["_row"] = np.arange(len(base))
    left = base.sort_values("ts")
    failures = _align_keys(failures) if failures is not None else failures
    if failures is None or failures.empty:
        out["y_fail_24h"] = 0
        out["next_component"] = pd.NA
        return out
    fail = (
        failures.sort_values(["machine_id", "ts", "component"])
        .drop_duplicates(["machine_id", "ts"], keep="first")
        .rename(columns={"ts": "fail_ts"})
    )
    right = fail[["machine_id", "fail_ts", "component"]].sort_values("fail_ts")
    merged = pd.merge_asof(
        left,
        right,
        left_on="ts",
        right_on="fail_ts",
        by="machine_id",
        direction="forward",
        allow_exact_matches=False,
    )
    delta = (merged["fail_ts"] - merged["ts"]).dt.total_seconds() / 3600
    positive = ((delta > 0) & (delta <= horizon_hours)).fillna(False)
    merged = merged.copy()
    merged["y_fail_24h"] = positive.astype(int).to_numpy()
    merged["next_component"] = np.where(merged["y_fail_24h"].eq(1), merged["component"], pd.NA)
    merged = merged.sort_values("_row")
    out["y_fail_24h"] = merged["y_fail_24h"].to_numpy()
    out["next_component"] = merged["next_component"].to_numpy()
    return out


def azure_feature_frame(
    telemetry: pd.DataFrame,
    errors: pd.DataFrame,
    maintenance: pd.DataFrame,
    machines: pd.DataFrame,
    failures: pd.DataFrame | None = None,
    window: int = WINDOW,
) -> pd.DataFrame:
    telemetry = _align_keys(telemetry)
    errors = _align_keys(errors) if errors is not None else errors
    maintenance = _align_keys(maintenance) if maintenance is not None else maintenance
    machines = machines.copy()
    machines["machine_id"] = machines["machine_id"].astype("int64")
    if failures is not None:
        failures = _align_keys(failures)
    df = telemetry[["machine_id", "ts", *SENSOR_COLS]].copy()
    df = df.sort_values(["machine_id", "ts"]).reset_index(drop=True)
    df = add_sensor_rolling(df, window=window)
    df = add_error_counts(df, errors, window=window)
    df = add_hours_since(df, maintenance)
    meta = machines[["machine_id", "model", "age_years"]].drop_duplicates("machine_id")
    df = df.merge(meta, on="machine_id", how="left")
    df = add_model_dummies(df)
    if failures is not None:
        df = add_failure_labels(df, failures)
    return df


def snapshot_features(
    telemetry: pd.DataFrame,
    errors: pd.DataFrame,
    maintenance: pd.DataFrame,
    machines: pd.DataFrame,
    as_of,
    history_hours: int = 36,
) -> pd.DataFrame:
    """One row per machine at the last reading at or before `as_of`.

    Only the recent telemetry is passed in. The last row's 24-hour window is
    identical to the full-history window when the grid is hourly and at least
    24 hours are included.
    """
    as_of = pd.Timestamp(as_of)
    start = as_of - pd.Timedelta(hours=history_hours)
    tel = telemetry[(telemetry["ts"] <= as_of) & (telemetry["ts"] > start)].copy()
    err = errors[(errors["ts"] <= as_of) & (errors["ts"] > start)].copy() if errors is not None else errors
    maint = maintenance[maintenance["ts"] <= as_of].copy() if maintenance is not None else maintenance
    frame = azure_feature_frame(tel, err, maint, machines, failures=None)
    last = frame.sort_values("ts").groupby("machine_id", as_index=False).tail(1)
    return last.reset_index(drop=True)


def add_cycle_rolling(df: pd.DataFrame, columns: list[str], windows: tuple[int, ...] = (5, 10)) -> pd.DataFrame:
    """Rolling mean and std over the trailing cycles of each C-MAPSS engine."""
    out = df.sort_values(["unit", "cycle"]).reset_index(drop=True)
    grouped = out.groupby("unit", sort=False)
    for column in columns:
        for window in windows:
            means = grouped[column].rolling(window, min_periods=1).mean().reset_index(level=0, drop=True)
            stds = grouped[column].rolling(window, min_periods=2).std().reset_index(level=0, drop=True)
            out[f"{column}_mean_{window}"] = means.to_numpy()
            out[f"{column}_std_{window}"] = np.nan_to_num(stds.to_numpy(), nan=0.0)
    return out


def add_train_rul(df: pd.DataFrame, cap: int = 125) -> pd.DataFrame:
    out = df.copy()
    last_cycle = out.groupby("unit")["cycle"].transform("max")
    out["rul"] = (last_cycle - out["cycle"]).clip(upper=cap)
    return out
