"""24-hour failure risk on the Azure predictive-maintenance sample.

Fit: January through July 2015.
August: calibrate probabilities and choose the red/amber cutoffs.
Test: 1 September through 30 December 06:00. Those rows are not used to fit anything.
"""

from __future__ import annotations

import time

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

from config import (
    AZURE_MODEL_PATH,
    DB_PATH,
    FIT_END,
    LABEL_CUTOFF,
    RANDOM_STATE,
    TEST_START,
)
from models.features import COMPONENTS, azure_feature_frame, feature_columns
from models.metrics_util import best_f1_threshold, classification_at_threshold, threshold_for_recall
from models.plots import AMBER, NAVY, apply_style, save
from pipeline.warehouse import connect


def design_matrix(frame: pd.DataFrame, columns: list[str], medians: pd.Series | None = None):
    matrix = frame.loc[:, columns].apply(pd.to_numeric, errors="coerce")
    matrix = matrix.replace([np.inf, -np.inf], np.nan)
    if medians is None:
        medians = matrix.median(numeric_only=True)
    return matrix.fillna(medians).astype(float), medians


def predict_calibrated(bundle: dict, matrix: pd.DataFrame) -> np.ndarray:
    raw = bundle["model"].predict_proba(matrix)[:, 1]
    calibrated = bundle["calibrator"].transform(raw)
    return np.clip(np.asarray(calibrated, dtype=float), 0.0, 1.0)


def predict_component(bundle: dict, matrix: pd.DataFrame) -> np.ndarray:
    labels = np.asarray(bundle["component_labels"])
    index = np.asarray(bundle["component_model"].predict(matrix)).astype(int)
    return labels[index]


def load_bundle() -> dict:
    if not AZURE_MODEL_PATH.exists():
        raise FileNotFoundError(f"Missing {AZURE_MODEL_PATH}. Run make train.")
    return joblib.load(AZURE_MODEL_PATH)


def _read_source():
    con = connect(DB_PATH, read_only=True)
    try:
        telemetry = con.execute(
            "SELECT machine_id, ts, volt, rotate, pressure, vibration FROM sensor_readings"
        ).fetchdf()
        errors = con.execute("SELECT machine_id, ts, error_code FROM faults").fetchdf()
        maintenance = con.execute("SELECT machine_id, ts, component FROM maintenance_events").fetchdf()
        failures = con.execute("SELECT machine_id, ts, component FROM failures").fetchdf()
        machines = con.execute(
            "SELECT machine_id, model, age_years, line, production_impact FROM machines"
        ).fetchdf()
        parts = con.execute("SELECT component, on_hand, reorder_point, lead_time_days FROM parts").fetchdf()
    finally:
        con.close()
    for frame in (telemetry, errors, maintenance, failures):
        frame["ts"] = pd.to_datetime(frame["ts"])
    return telemetry, errors, maintenance, failures, machines, parts


def _fit_xgb(X, y) -> XGBClassifier:
    y = np.asarray(y).astype(int)
    pos = max(int(y.sum()), 1)
    neg = max(int((y == 0).sum()), 1)
    model = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        scale_pos_weight=neg / pos,
        objective="binary:logistic",
        eval_metric="aucpr",
        tree_method="hist",
        random_state=RANDOM_STATE,
        n_jobs=4,
    )
    model.fit(X, y)
    return model


def _fit_logistic(X, y):
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(class_weight="balanced", max_iter=500, solver="lbfgs", tol=1e-3),
    )
    model.fit(X, y)
    return model


def _calibrate(raw_val, y_val, raw_other):
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(np.asarray(raw_val, dtype=float), np.asarray(y_val, dtype=float))
    val = np.clip(calibrator.transform(raw_val), 0, 1)
    other = np.clip(calibrator.transform(raw_other), 0, 1)
    return calibrator, val, other


def _pr_curve(y_true, proba, path_name: str, title: str) -> None:
    precision, recall, _ = precision_recall_curve(y_true, proba)
    apply_style()
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    ax.plot(recall, precision, color=NAVY, linewidth=2, label="Model")
    prevalence = float(np.mean(y_true))
    ax.axhline(prevalence, color=AMBER, linestyle="--", linewidth=1, label=f"Prevalence {prevalence:.1%}")
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title(title)
    ax.legend(frameon=False)
    save(fig, path_name)


def train_azure() -> dict:
    started = time.perf_counter()
    print("Azure: reading warehouse and building features...")
    telemetry, errors, maintenance, failures, machines, parts = _read_source()
    frame = azure_feature_frame(telemetry, errors, maintenance, machines, failures=failures)
    frame = frame[frame["ts"] <= LABEL_CUTOFF].copy()
    columns = feature_columns()
    print(f"  feature rows {len(frame):,} in {time.perf_counter() - started:.1f}s")

    fit_mask = frame["ts"] < FIT_END
    val_mask = (frame["ts"] >= FIT_END) & (frame["ts"] < TEST_START)
    test_mask = frame["ts"] >= TEST_START
    y_fit = frame.loc[fit_mask, "y_fail_24h"].astype(int)
    y_val = frame.loc[val_mask, "y_fail_24h"].astype(int)
    y_test = frame.loc[test_mask, "y_fail_24h"].astype(int)
    X_fit, medians = design_matrix(frame.loc[fit_mask], columns)
    X_val, _ = design_matrix(frame.loc[val_mask], columns, medians)
    X_test, _ = design_matrix(frame.loc[test_mask], columns, medians)
    print(
        f"  fit {len(X_fit):,} ({int(y_fit.sum()):,} positives), "
        f"August {len(X_val):,}, test {len(X_test):,} ({int(y_test.sum()):,} positives)"
    )

    print("Azure: fitting XGBoost and logistic regression...")
    xgb_model = _fit_xgb(X_fit, y_fit)
    logistic = _fit_logistic(X_fit, y_fit)
    xgb_cal, xgb_val, xgb_test = _calibrate(
        xgb_model.predict_proba(X_val)[:, 1], y_val, xgb_model.predict_proba(X_test)[:, 1]
    )
    log_cal, log_val, log_test = _calibrate(
        logistic.predict_proba(X_val)[:, 1], y_val, logistic.predict_proba(X_test)[:, 1]
    )
    xgb_red = best_f1_threshold(y_val, xgb_val)
    log_red = best_f1_threshold(y_val, log_val)
    amber = threshold_for_recall(y_val, xgb_val, 0.50)
    if amber >= xgb_red:
        amber = xgb_red * 0.5

    xgb_metrics = classification_at_threshold(y_test, xgb_test, xgb_red)
    log_metrics = classification_at_threshold(y_test, log_test, log_red)
    xgb_metrics["pr_auc_raw"] = float(average_precision_score(y_test, xgb_model.predict_proba(X_test)[:, 1]))
    log_metrics["pr_auc_raw"] = float(average_precision_score(y_test, logistic.predict_proba(X_test)[:, 1]))
    _pr_curve(y_test, xgb_test, "azure_pr_curve.png", "24-hour failure risk, September–December")
    print(
        f"  XGB F1 {xgb_metrics['f1']:.3f}  PR-AUC {xgb_metrics['pr_auc']:.3f}  "
        f"red>={xgb_red:.3f} amber>={amber:.3f}"
    )

    print("Azure: component model on the failure rows...")
    comp_train = frame.loc[fit_mask & frame["y_fail_24h"].eq(1)].dropna(subset=["next_component"]).copy()
    comp_test = frame.loc[test_mask & frame["y_fail_24h"].eq(1)].dropna(subset=["next_component"]).copy()
    comp_model = XGBClassifier(
        n_estimators=120,
        max_depth=3,
        learning_rate=0.1,
        objective="multi:softprob",
        tree_method="hist",
        random_state=RANDOM_STATE,
        n_jobs=4,
    )
    label_to_index = {name: index for index, name in enumerate(COMPONENTS)}
    X_comp, _ = design_matrix(comp_train, columns, medians)
    y_comp = comp_train["next_component"].astype(str).map(label_to_index).astype(int)
    comp_model.fit(X_comp, y_comp, sample_weight=compute_sample_weight("balanced", y_comp))
    X_comp_test, _ = design_matrix(comp_test, columns, medians)
    comp_pred = np.asarray(COMPONENTS)[comp_model.predict(X_comp_test).astype(int)]
    from sklearn.metrics import f1_score

    component_f1 = float(
        f1_score(comp_test["next_component"].astype(str), comp_pred, average="macro", zero_division=0)
    )

    bundle = {
        "model": xgb_model,
        "calibrator": xgb_cal,
        "baseline": logistic,
        "baseline_calibrator": log_cal,
        "component_model": comp_model,
        "features": columns,
        "medians": medians.to_dict(),
        "threshold": float(xgb_red),
        "amber_threshold": float(amber),
        "components": COMPONENTS,
        "component_labels": list(COMPONENTS),
    }
    AZURE_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, AZURE_MODEL_PATH)

    quantiles = {
        "p50": float(np.quantile(xgb_test, 0.50)),
        "p90": float(np.quantile(xgb_test, 0.90)),
        "p95": float(np.quantile(xgb_test, 0.95)),
        "p99": float(np.quantile(xgb_test, 0.99)),
    }
    return {
        "xgboost": xgb_metrics,
        "logistic": log_metrics,
        "component_macro_f1": component_f1,
        "component_test_rows": int(len(comp_test)),
        "quantiles": quantiles,
        "red_at": float(xgb_red),
        "amber_at": float(amber),
        "fit_end": str(FIT_END),
        "test_start": str(TEST_START),
        "label_cutoff": str(LABEL_CUTOFF),
        "frame": frame,
        "machines": machines,
        "parts": parts,
        "failures": failures,
        "bundle": bundle,
    }
