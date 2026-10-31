"""Remaining useful life on NASA C-MAPSS FD001.

Engines are never split across train and validation. Tuning uses GroupKFold.
The official test file is scored once, after the model is chosen.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import GridSearchCV, GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from config import RANDOM_STATE, RUL_CAP, RUL_MODEL_PATH
from models.features import add_cycle_rolling, add_train_rul
from models.metrics_util import rmse
from models.plots import AMBER, NAVY, apply_style, save
from pipeline.load import CMAPSS_COLUMNS, load_cmapss_fd001

SETTING_AND_SENSOR = CMAPSS_COLUMNS[2:]


def _varying_columns(train: pd.DataFrame) -> tuple[list[str], list[str]]:
    constant = []
    varying = []
    for column in SETTING_AND_SENSOR:
        if float(train[column].std(ddof=0)) < 1e-8:
            constant.append(column)
        else:
            varying.append(column)
    return varying, constant


def _engineered(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    engineered = add_cycle_rolling(df, columns, windows=(5, 10))
    feature_cols = []
    for column in columns:
        feature_cols.append(column)
        feature_cols.append(f"{column}_mean_5")
        feature_cols.append(f"{column}_std_5")
        feature_cols.append(f"{column}_mean_10")
        feature_cols.append(f"{column}_std_10")
    return engineered, feature_cols


def _last_cycle(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["unit", "cycle"]).groupby("unit", as_index=False).tail(1).sort_values("unit")


def _score_pair(y_true, pred) -> dict:
    pred = np.asarray(pred, dtype=float)
    y_true = np.asarray(y_true, dtype=float)
    nonneg = np.clip(pred, 0, None)
    capped_pred = np.clip(pred, 0, RUL_CAP)
    capped_truth = np.minimum(y_true, RUL_CAP)
    return {
        "rmse_official": rmse(y_true, nonneg),
        "rmse_piecewise": rmse(capped_truth, capped_pred),
    }


def _fit_grid(estimator, grid, X, y, groups):
    search = GridSearchCV(
        estimator,
        grid,
        scoring="neg_root_mean_squared_error",
        cv=GroupKFold(n_splits=3),
        n_jobs=2,
        refit=True,
    )
    search.fit(X, y, groups=groups)
    return search


def train_rul(raw_dir: Path | None = None) -> dict:
    from config import RAW_DIR

    raw_dir = Path(raw_dir) if raw_dir is not None else RAW_DIR
    cycles, rul_file = load_cmapss_fd001(raw_dir)
    train = cycles[cycles["split"] == "train"].copy()
    test = cycles[cycles["split"] == "test"].copy()
    varying, constant = _varying_columns(train)
    train = add_train_rul(train, cap=RUL_CAP)
    train_eng, rich_cols = _engineered(train, varying)
    test_eng, _ = _engineered(test, varying)

    y = train_eng["rul"].to_numpy()
    groups = train_eng["unit"].to_numpy()
    X_raw = train_eng[varying]
    X_rich = train_eng[rich_cols]

    linear_raw = make_pipeline(StandardScaler(), LinearRegression())
    linear_raw.fit(X_raw, y)
    linear_rich = make_pipeline(StandardScaler(), LinearRegression())
    linear_rich.fit(X_rich, y)

    forest_search = _fit_grid(
        RandomForestRegressor(n_estimators=80, n_jobs=1, random_state=RANDOM_STATE),
        {"max_depth": [12, 20], "min_samples_leaf": [1, 3]},
        X_rich,
        y,
        groups,
    )
    xgb_search = _fit_grid(
        XGBRegressor(
            objective="reg:squarederror",
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.8,
            tree_method="hist",
            random_state=RANDOM_STATE,
            n_jobs=1,
        ),
        {"max_depth": [3, 5], "n_estimators": [150, 300]},
        X_rich,
        y,
        groups,
    )

    candidates = {
        "random_forest": forest_search,
        "xgboost": xgb_search,
    }
    winner_name = min(candidates, key=lambda name: -candidates[name].best_score_)
    winner = candidates[winner_name].best_estimator_

    test_last = _last_cycle(test_eng)
    official = rul_file.sort_values("unit")["rul"].to_numpy()
    if list(test_last["unit"]) != list(range(1, 101)):
        raise RuntimeError("FD001 test units are not 1..100; the RUL file alignment would be wrong.")
    if len(official) != 100:
        raise RuntimeError(f"RUL_FD001.txt has {len(official)} rows, expected 100.")

    def official_pred(model, columns):
        return model.predict(test_last[columns])

    rows = []
    for name, model, columns, cv in (
        ("Linear regression", linear_raw, varying, None),
        ("Linear regression", linear_rich, rich_cols, None),
        ("Random forest", forest_search.best_estimator_, rich_cols, float(-forest_search.best_score_)),
        ("XGBoost", xgb_search.best_estimator_, rich_cols, float(-xgb_search.best_score_)),
    ):
        scored = _score_pair(official, official_pred(model, columns))
        rows.append(
            {
                "model": name,
                "features": "raw sensors" if columns == varying else "raw + rolling 5/10",
                "cv_rmse": cv,
                **scored,
            }
        )

    saved = {
        "model": winner,
        "model_name": winner_name,
        "features": rich_cols,
        "varying_columns": varying,
        "constant_columns": constant,
        "rul_cap": RUL_CAP,
        "params": candidates[winner_name].best_params_,
    }
    RUL_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(saved, RUL_MODEL_PATH)

    pred = np.clip(winner.predict(test_last[rich_cols]), 0, None)
    _plot_pred(official, pred)
    _plot_importance(winner, rich_cols)
    buckets = _error_buckets(official, pred)
    _plot_buckets(buckets)

    return {
        "constant_columns": constant,
        "varying_columns": varying,
        "winner": winner_name,
        "winner_params": candidates[winner_name].best_params_,
        "comparison": rows,
        "error_buckets": buckets,
        "n_train_rows": int(len(train_eng)),
        "n_train_engines": int(train["unit"].nunique()),
        "n_test_engines": 100,
        "life_cycles": {
            "min": int(train.groupby("unit")["cycle"].max().min()),
            "median": float(train.groupby("unit")["cycle"].max().median()),
            "max": int(train.groupby("unit")["cycle"].max().max()),
        },
        "wrong_where": _wrong_where(buckets),
    }


def _error_buckets(y_true, pred) -> list[dict]:
    y_true = np.asarray(y_true, dtype=float)
    pred = np.asarray(pred, dtype=float)
    spans = [(0, 30, "0–30 cycles left"), (31, 80, "31–80"), (81, 125, "81–125"), (126, 10000, "more than 125")]
    rows = []
    for low, high, label in spans:
        mask = (y_true >= low) & (y_true <= high)
        if not mask.any():
            continue
        rows.append(
            {
                "bucket": label,
                "engines": int(mask.sum()),
                "rmse": rmse(y_true[mask], pred[mask]),
            }
        )
    return rows


def _wrong_where(buckets: list[dict]) -> str:
    by_name = {row["bucket"]: row["rmse"] for row in buckets}
    near = by_name.get("0–30 cycles left")
    far = by_name.get("more than 125")
    if near is None or far is None:
        return "See the error table. There were not enough engines in every life bucket to compare."
    if far > near:
        return (
            f"Error is larger when the official remaining life is still long "
            f"({far:.1f} RMSE beyond 125 cycles versus {near:.1f} when fewer than 30 cycles remain). "
            "Training labels were capped at 125, so the model is not allowed to predict a long healthy life, "
            "and engines that fail much later pile up near that cap. It is most useful close to failure, "
            "which is also when a maintenance lead would act."
        )
    return (
        f"Error near failure is {near:.1f} RMSE and error beyond 125 cycles is {far:.1f}. "
        "The cap at 125 did not dominate this run the way it often does on FD001."
    )


def _plot_pred(y_true, pred) -> None:
    apply_style()
    fig, ax = plt.subplots(figsize=(6.4, 5.2))
    ax.scatter(y_true, pred, s=28, color=NAVY, alpha=0.85, zorder=3)
    limit = max(float(np.max(y_true)), float(np.max(pred)), RUL_CAP) + 10
    ax.plot([0, limit], [0, limit], color="#9aa7b0", linewidth=1)
    ax.axvline(RUL_CAP, color=AMBER, linewidth=1, linestyle="--")
    ax.set_xlabel("Official remaining cycles (RUL_FD001)")
    ax.set_ylabel("Predicted remaining cycles")
    ax.set_title("FD001 test engines, last observed cycle")
    save(fig, "rul_pred_vs_actual.png")


def _plot_importance(model, columns: list[str]) -> None:
    if not hasattr(model, "feature_importances_"):
        return
    order = np.argsort(model.feature_importances_)[-12:]
    apply_style()
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    ax.barh(np.array(columns)[order], model.feature_importances_[order], color=NAVY)
    ax.set_xlabel("Importance")
    ax.set_title("What the remaining-life model uses")
    save(fig, "rul_feature_importance.png")


def _plot_buckets(buckets: list[dict]) -> None:
    apply_style()
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    ax.bar([row["bucket"] for row in buckets], [row["rmse"] for row in buckets], color=NAVY)
    ax.set_ylabel("RMSE (cycles)")
    ax.set_title("Where remaining-life error sits")
    save(fig, "rul_error_by_life.png")
