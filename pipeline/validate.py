"""Checks that run before anything is written to the warehouse."""

from __future__ import annotations

import pandas as pd

from config import EVENT_MAX, EVENT_MIN, MAINT_MAX, MAINT_MIN, TELEMETRY_MAX, TELEMETRY_MIN


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def _null_key(frame: pd.DataFrame, columns: list[str], name: str, errors: list[str]) -> None:
    for column in columns:
        if column not in frame.columns:
            errors.append(f"{name} is missing column {column}")
            continue
        n = int(frame[column].isna().sum())
        if n:
            errors.append(f"{name}.{column} has {n} nulls")


def _in_range(frame: pd.DataFrame, column: str, name: str, start, end, errors: list[str]) -> None:
    if column not in frame.columns or frame.empty:
        return
    ts = pd.to_datetime(frame[column])
    too_early = int((ts < start).sum())
    too_late = int((ts > end).sum())
    if too_early or too_late:
        errors.append(
            f"{name}.{column} has {too_early} timestamps before {start} "
            f"and {too_late} after {end}"
        )


def _unknown_machines(frame: pd.DataFrame, machines: pd.DataFrame, name: str, errors: list[str]) -> None:
    if "machine_id" not in frame.columns or frame.empty:
        return
    known = set(machines["machine_id"].dropna().tolist())
    unknown = sorted(set(frame["machine_id"].dropna().tolist()) - known)
    if unknown:
        preview = ", ".join(str(m) for m in unknown[:8])
        errors.append(f"{name} has machine_id values missing from machines: {preview}")


def validate_azure(frames: dict[str, pd.DataFrame]) -> list[str]:
    """Return a list of problems. An empty list means the frames can be loaded.

    Telemetry must be a regular hourly grid. That is what lets a 24-row rolling
    window mean 24 hours. Maintenance is allowed to start in June 2014 because
    the source file does.
    """
    errors: list[str] = []
    machines = frames["machines"]
    telemetry = frames["telemetry"]
    faults = frames["faults"]
    failures = frames["failures"]
    maintenance = frames["maintenance"]

    _null_key(machines, ["machine_id", "model", "age_years"], "machines", errors)
    _null_key(telemetry, ["machine_id", "ts", "volt", "rotate", "pressure", "vibration"], "telemetry", errors)
    _null_key(faults, ["machine_id", "ts", "error_code"], "faults", errors)
    _null_key(failures, ["machine_id", "ts", "component"], "failures", errors)
    _null_key(maintenance, ["machine_id", "ts", "component"], "maintenance", errors)

    if not machines.empty and machines["machine_id"].duplicated().any():
        errors.append("machines.machine_id has duplicates")

    if not telemetry.empty:
        dup = telemetry.duplicated(["machine_id", "ts"]).sum()
        if dup:
            errors.append(f"telemetry has {int(dup)} duplicate (machine_id, ts) rows")

    if not faults.empty and faults.duplicated(["machine_id", "ts", "error_code"]).any():
        errors.append("faults has duplicate (machine_id, ts, error_code) rows")

    _in_range(telemetry, "ts", "telemetry", TELEMETRY_MIN, TELEMETRY_MAX, errors)
    _in_range(faults, "ts", "faults", EVENT_MIN, EVENT_MAX, errors)
    _in_range(failures, "ts", "failures", EVENT_MIN, EVENT_MAX, errors)
    _in_range(maintenance, "ts", "maintenance", MAINT_MIN, MAINT_MAX, errors)

    for name in ("telemetry", "faults", "failures", "maintenance"):
        _unknown_machines(frames[name], machines, name, errors)

    if not telemetry.empty and "machine_id" in telemetry.columns and "ts" in telemetry.columns:
        ordered = telemetry.sort_values(["machine_id", "ts"])
        diffs = ordered.groupby("machine_id")["ts"].diff().dropna()
        bad = diffs != pd.Timedelta(hours=1)
        # A machine with a handful of rows is still checked: any gap must be one hour.
        if not diffs.empty and bool(bad.any()):
            errors.append(f"telemetry has {int(bad.sum())} gaps that are not 1 hour")

    return errors


def require_valid(frames: dict[str, pd.DataFrame]) -> None:
    errors = validate_azure(frames)
    if errors:
        raise ValidationError(errors)
