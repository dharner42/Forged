"""AI4I 2020 failure classifier. The headline metric is F1, not accuracy."""

from __future__ import annotations

from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from config import AI4I_MODEL_PATH, RANDOM_STATE
from models.plots import AMBER, NAVY, apply_style, save
from pipeline.load import load_ai4i

FEATURES = [
    "air_temp_k",
    "process_temp_k",
    "rpm",
    "torque_nm",
    "tool_wear_min",
    "power",
    "temp_diff",
    "type_M",
    "type_H",
]
# RNF is defined by the dataset author as a random failure with no causal trace.
MODES = ("twf", "hdf", "pwf", "osf")


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["power"] = out["torque_nm"] * out["rpm"]
    out["temp_diff"] = out["process_temp_k"] - out["air_temp_k"]
    dummies = pd.get_dummies(out["type"], prefix="type")
    for column in ("type_L", "type_M", "type_H"):
        if column not in dummies.columns:
            dummies[column] = 0
    # Type L is the reference level.
    out["type_M"] = dummies["type_M"].astype(float).to_numpy()
    out["type_H"] = dummies["type_H"].astype(float).to_numpy()
    return out


def _fit_pair(X_train, y_train, X_test, y_test) -> dict:
    y_train = np.asarray(y_train).astype(int)
    y_test = np.asarray(y_test).astype(int)
    baseline = make_pipeline(
        StandardScaler(),
        LogisticRegression(class_weight="balanced", max_iter=400, solver="lbfgs"),
    )
    baseline.fit(X_train, y_train)
    pos = max(int(y_train.sum()), 1)
    neg = int((y_train == 0).sum())
    model = XGBClassifier(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        scale_pos_weight=neg / pos,
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        random_state=RANDOM_STATE,
        n_jobs=2,
    )
    model.fit(X_train, y_train)
    baseline_pred = baseline.predict(X_test)
    model_pred = model.predict(X_test)
    majority_accuracy = float((y_test == 0).mean())
    return {
        "logistic_f1": float(f1_score(y_test, baseline_pred, zero_division=0)),
        "xgboost_f1": float(f1_score(y_test, model_pred, zero_division=0)),
        "support_positive_test": int(y_test.sum()),
        "support_positive_train": int(y_train.sum()),
        "majority_class_accuracy": majority_accuracy,
        "model": model,
        "baseline": baseline,
    }


def train_ai4i(raw_dir: Path | None = None) -> dict:
    from config import RAW_DIR

    raw_dir = Path(raw_dir) if raw_dir is not None else RAW_DIR
    prepared = _prepare(load_ai4i(raw_dir))
    X = prepared[FEATURES]
    y = prepared["machine_failure"].astype(int)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=RANDOM_STATE, stratify=y
    )
    main = _fit_pair(X_train, y_train, X_test, y_test)
    modes = {}
    for mode in MODES:
        target = prepared[mode].astype(int)
        if target.sum() < 8 or (target == 0).sum() < 8:
            modes[mode] = {"skipped": True}
            continue
        Xt, Xv, yt, yv = train_test_split(
            X, target, test_size=0.25, random_state=RANDOM_STATE, stratify=target
        )
        fitted = _fit_pair(Xt, yt, Xv, yv)
        modes[mode] = {key: fitted[key] for key in fitted if key not in {"model", "baseline"}}

    AI4I_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": main["model"], "baseline": main["baseline"], "features": FEATURES},
        AI4I_MODEL_PATH,
    )
    _plot(main, modes)
    prevalence = float(y.mean())
    return {
        "rows": int(len(prepared)),
        "prevalence": prevalence,
        "null_accuracy": float(1 - prevalence),
        "logistic_f1": main["logistic_f1"],
        "xgboost_f1": main["xgboost_f1"],
        "test_positives": main["support_positive_test"],
        "modes": modes,
        "features": FEATURES,
        "rnf_rows": int(prepared["rnf"].sum()),
        "mode_counts": {mode: int(prepared[mode].sum()) for mode in MODES},
    }


def _plot(main: dict, modes: dict) -> None:
    apply_style()
    labels = ["Any failure"] + [mode.upper() for mode in MODES if "xgboost_f1" in modes.get(mode, {})]
    xgb = [main["xgboost_f1"]] + [modes[mode]["xgboost_f1"] for mode in MODES if "xgboost_f1" in modes.get(mode, {})]
    base = [main["logistic_f1"]] + [modes[mode]["logistic_f1"] for mode in MODES if "logistic_f1" in modes.get(mode, {})]
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    xpos = np.arange(len(labels))
    ax.bar(xpos - 0.18, base, width=0.36, label="Logistic regression", color=AMBER)
    ax.bar(xpos + 0.18, xgb, width=0.36, label="XGBoost", color=NAVY)
    ax.set_xticks(xpos, labels)
    ax.set_ylim(0, 1)
    ax.set_ylabel("F1 on the held-out 25%")
    ax.set_title("AI4I failure detection")
    ax.legend(frameon=False)
    save(fig, "ai4i_f1.png")
