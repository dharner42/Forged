"""Read the raw files into the column names the warehouse uses."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

CMAPSS_COLUMNS = (
    ["unit", "cycle", "op1", "op2", "op3"] + [f"s{i}" for i in range(1, 22)]
)


def _azure_dir(raw_dir: Path) -> Path:
    azure = raw_dir / "azure"
    return azure if azure.exists() else raw_dir


def load_azure(raw_dir: Path) -> dict[str, pd.DataFrame]:
    folder = _azure_dir(raw_dir)
    telemetry = pd.read_csv(folder / "PdM_telemetry.csv")
    telemetry = telemetry.rename(columns={"datetime": "ts", "machineID": "machine_id"})
    telemetry["ts"] = pd.to_datetime(telemetry["ts"])

    faults = pd.read_csv(folder / "PdM_errors.csv")
    faults = faults.rename(columns={"datetime": "ts", "machineID": "machine_id", "errorID": "error_code"})
    faults["ts"] = pd.to_datetime(faults["ts"])
    faults["error_code"] = faults["error_code"].astype(str).str.strip()

    maintenance = pd.read_csv(folder / "PdM_maint.csv")
    maintenance = maintenance.rename(columns={"datetime": "ts", "machineID": "machine_id", "comp": "component"})
    maintenance["ts"] = pd.to_datetime(maintenance["ts"])
    maintenance["component"] = maintenance["component"].astype(str).str.strip()

    failures = pd.read_csv(folder / "PdM_failures.csv")
    failures = failures.rename(columns={"datetime": "ts", "machineID": "machine_id", "failure": "component"})
    failures["ts"] = pd.to_datetime(failures["ts"])
    failures["component"] = failures["component"].astype(str).str.strip()

    machines = pd.read_csv(folder / "PdM_machines.csv")
    machines = machines.rename(columns={"machineID": "machine_id", "age": "age_years"})
    machines["model"] = machines["model"].astype(str).str.strip()

    for frame in (telemetry, faults, failures, maintenance, machines):
        frame["machine_id"] = frame["machine_id"].astype(int)

    return {
        "telemetry": telemetry,
        "faults": faults,
        "failures": failures,
        "maintenance": maintenance,
        "machines": machines,
    }


def with_ids(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Add surrogate keys. Historical maintenance has no technician and is marked scheduled."""
    faults = frames["faults"].sort_values(["ts", "machine_id", "error_code"]).reset_index(drop=True)
    faults.insert(0, "fault_id", faults.index + 1)

    failures = frames["failures"].sort_values(["ts", "machine_id", "component"]).reset_index(drop=True)
    failures.insert(0, "failure_id", failures.index + 1)

    maintenance = frames["maintenance"].sort_values(["ts", "machine_id", "component"]).reset_index(drop=True)
    maintenance.insert(0, "event_id", maintenance.index + 1)
    maintenance["type"] = "scheduled"
    maintenance["technician_id"] = pd.Series([pd.NA] * len(maintenance), dtype="Int64")

    out = dict(frames)
    out["faults"] = faults
    out["failures"] = failures
    out["maintenance"] = maintenance
    return out


def load_ai4i(raw_dir: Path) -> pd.DataFrame:
    path = raw_dir / "ai4i" / "ai4i2020.csv"
    frame = pd.read_csv(path)
    frame = frame.rename(
        columns={
            "UDI": "udi",
            "Product ID": "product_id",
            "Type": "type",
            "Air temperature [K]": "air_temp_k",
            "Process temperature [K]": "process_temp_k",
            "Rotational speed [rpm]": "rpm",
            "Torque [Nm]": "torque_nm",
            "Tool wear [min]": "tool_wear_min",
            "Machine failure": "machine_failure",
            "TWF": "twf",
            "HDF": "hdf",
            "PWF": "pwf",
            "OSF": "osf",
            "RNF": "rnf",
        }
    )
    return frame


def load_cmapss_fd001(raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    folder = raw_dir / "cmapss"
    train = pd.read_csv(folder / "train_FD001.txt", sep=r"\s+", header=None, names=CMAPSS_COLUMNS)
    test = pd.read_csv(folder / "test_FD001.txt", sep=r"\s+", header=None, names=CMAPSS_COLUMNS)
    train["split"] = "train"
    test["split"] = "test"
    cycles = pd.concat([train, test], ignore_index=True)
    rul = pd.read_csv(folder / "RUL_FD001.txt", header=None, names=["rul"])
    rul.insert(0, "unit", rul.index + 1)
    return cycles, rul
