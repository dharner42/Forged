"""Paths and the few constants the pipeline, models, and dashboard share."""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "warehouse.duckdb"
ARTIFACT_DIR = ROOT / "models" / "artifacts"
RESULTS_DIR = ROOT / "results"
PLOTS_DIR = RESULTS_DIR / "plots"
RUL_MODEL_PATH = ROOT / "models" / "rul_fd001.joblib"
AZURE_MODEL_PATH = ARTIFACT_DIR / "azure_fail_24h.joblib"
AI4I_MODEL_PATH = ARTIFACT_DIR / "ai4i_failure.joblib"
METRICS_PATH = RESULTS_DIR / "metrics.json"

TELEMETRY_MIN = pd.Timestamp("2015-01-01")
TELEMETRY_MAX = pd.Timestamp("2016-01-02")
MAINT_MIN = pd.Timestamp("2014-06-01")
MAINT_MAX = pd.Timestamp("2016-01-02")
EVENT_MIN = pd.Timestamp("2015-01-01")
EVENT_MAX = pd.Timestamp("2016-01-02")

# Last timestamp whose next 24 hours still fall inside the failure log.
LABEL_CUTOFF = pd.Timestamp("2015-12-30 06:00:00")
# Fit on months before August. August picks the threshold and the calibrator.
FIT_END = pd.Timestamp("2015-08-01")
TEST_START = pd.Timestamp("2015-09-01")
CLOCK_MIN = pd.Timestamp("2015-01-08 00:00:00")
CLOCK_MAX = LABEL_CUTOFF

RANDOM_STATE = 42
RUL_CAP = 125
FAILURE_HORIZON_HOURS = 24
SERVICE_WINDOW_HOURS = 24
SERVICE_SUPPRESSION = 0.15
PARTS_SHORTAGE_FACTOR = 1.5
PARTS_OK_FACTOR = 1.0

EXPECTED_COUNTS = {
    "sensor_readings": 876_100,
    "faults": 3_919,
    "maintenance_events": 3_286,
    "failures": 761,
    "machines": 100,
}
