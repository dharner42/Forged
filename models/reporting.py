"""Write results/metrics.json and results/results.md from a training run."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config import METRICS_PATH
from models.costs import savings_from_hit_rates, savings_section


def _plain(value):
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (np.floating, float)):
        return float(value)
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (pd.Timestamp,)):
        return str(value)
    return value


def _pct(value: float) -> str:
    return f"{value:.1%}"


def _num(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def write_results(rul: dict, ai4i: dict, azure: dict, backtest: dict) -> None:
    backtest = dict(backtest)
    backtest.setdefault("savings", savings_from_hit_rates(backtest))
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "azure": {key: value for key, value in azure.items() if key not in {"frame", "machines", "parts", "failures", "bundle"}},
        "rul": rul,
        "ai4i": ai4i,
        "backtest": backtest,
        "bands": {"red_at": azure["red_at"], "amber_at": azure["amber_at"]},
        "demo_as_of": backtest.get("demo_as_of"),
    }
    payload = _plain(payload)
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(payload, indent=2))
    (METRICS_PATH.parent / "results.md").write_text(_markdown(payload))


def _markdown(payload: dict) -> str:
    azure = payload["azure"]
    xgb = azure["xgboost"]
    logistic = azure["logistic"]
    rul_lines = [
        "| Model | Features | CV RMSE | RMSE vs official RUL | RMSE vs RUL capped at 125 |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in payload["rul"]["comparison"]:
        cv = "—" if row["cv_rmse"] is None else _num(row["cv_rmse"], 2)
        rul_lines.append(
            f"| {row['model']} | {row['features']} | {cv} | {_num(row['rmse_official'], 2)} | {_num(row['rmse_piecewise'], 2)} |"
        )
    mode_lines = [
        "| Failure mode | Test positives | Logistic F1 | XGBoost F1 |",
        "| --- | ---: | ---: | ---: |",
        f"| Any failure | {xgb and payload['ai4i']['test_positives']} | {_num(payload['ai4i']['logistic_f1'], 3)} | {_num(payload['ai4i']['xgboost_f1'], 3)} |",
    ]
    for mode, stats in payload["ai4i"]["modes"].items():
        if "xgboost_f1" not in stats:
            continue
        mode_lines.append(
            f"| {mode.upper()} | {stats['support_positive_test']} | {_num(stats['logistic_f1'], 3)} | {_num(stats['xgboost_f1'], 3)} |"
        )
    winner = payload["rul"]["winner"]
    winner_label = {"xgboost": "XGBoost", "random_forest": "Random forest"}[winner]
    winner_row = next(row for row in payload["rul"]["comparison"] if row["model"] == winner_label)
    back = payload["backtest"]
    return f"""# Model results

Generated {payload['generated_at']} by `python -m models.train`. These numbers are copied into the README. If you retrain, this file is the source of truth.

## 24-hour failure risk (the model the dashboard runs)

Question: at this machine-hour, does a component failure happen in the next 24 hours?

- Fit on January–July 2015. August is used only to calibrate probabilities (isotonic regression) and to pick the decision threshold. September 1 through December 30 at 06:00 is the test period.
- Class imbalance is large. Prevalence on the test rows is {_pct(xgb['prevalence'])}. A classifier that never predicts a failure would be about {_pct(1 - xgb['prevalence'])} accurate and would have an F1 of 0.
- `scale_pos_weight` is used while fitting so the trees see the rare failures. The probability the dashboard multiplies into the priority formula is the calibrated one.

| Model | Precision | Recall | F1 | PR-AUC | Threshold |
| --- | ---: | ---: | ---: | ---: | ---: |
| Logistic regression (baseline) | {_num(logistic['precision'])} | {_num(logistic['recall'])} | {_num(logistic['f1'])} | {_num(logistic['pr_auc'])} | {_num(logistic['threshold'])} |
| XGBoost | {_num(xgb['precision'])} | {_num(xgb['recall'])} | {_num(xgb['f1'])} | {_num(xgb['pr_auc'])} | {_num(xgb['threshold'])} |

XGBoost confusion matrix on the test hours: {xgb['tp']} true positives, {xgb['fp']} false positives, {xgb['fn']} false negatives, {xgb['tn']} true negatives.

The mean calibrated probability on those hours is {_num(xgb['mean_predicted'])}, next to a failure rate of {_num(xgb['prevalence'])}. In aggregate the probabilities match the base rate. Machine by machine they pile up near 0 and near 1 (test median {_num(azure['quantiles']['p50'])}, 99th percentile {_num(azure['quantiles']['p99'])}), because this simulator leaves a loud fingerprint and isotonic calibration then pushes scores to the ends. Do not quote the 0.99 as what a real plant will get. The logistic regression is the floor that transfers: it is already strong, and the trees pick up the rest of a nearly rule-shaped failure process.

PR-AUC on the uncalibrated scores is {_num(xgb['pr_auc_raw'])} for XGBoost and {_num(logistic['pr_auc_raw'])} for logistic regression. Calibration is monotone, so ranking quality barely moves. The table above is the calibrated score the product uses.

Red band: calibrated probability at or above {_num(azure['red_at'])} (the August threshold that maximized F1). Amber: at or above {_num(azure['amber_at'])} and below red. Green: below amber. Test-set probability quantiles: median {_num(azure['quantiles']['p50'])}, 90th {_num(azure['quantiles']['p90'])}, 95th {_num(azure['quantiles']['p95'])}, 99th {_num(azure['quantiles']['p99'])}.

When a failure is coming, a second model guesses the component. Macro F1 on test hours that do fail within 24 hours: {_num(azure['component_macro_f1'])} ({azure['component_test_rows']} rows). On this file that score is essentially perfect, which means the simulator's component rule is recoverable from the same features. Treat it as a property of the dataset. The guess still only picks which simulated part to check.

## Remaining useful life (C-MAPSS FD001)

100 training engines, {payload['rul']['n_train_rows']} cycles. Labels are remaining cycles, capped at 125. Constant columns dropped before modeling: {', '.join(payload['rul']['constant_columns'])}.

An engine is never in both sides of a split. Random forest and XGBoost are tuned with GroupKFold (3 folds) on the training engines. The winner is the better cross-validated model, not the better test score. The official test file is scored once.

{chr(10).join(rul_lines)}

Saved model: **{winner}** with parameters `{payload['rul']['winner_params']}`. Its official-file RMSE is {_num(winner_row['rmse_official'], 2)} cycles. RMSE against remaining life capped at 125 is {_num(winner_row['rmse_piecewise'], 2)} cycles. The second number matches the training target. The first number is what `RUL_FD001.txt` actually contains, including engines with more than 125 cycles left.

{payload['rul']['wrong_where']}

## AI4I 2020 failure type

10,000 synthetic milling-process rows. {_pct(payload['ai4i']['prevalence'])} have any machine failure, so a model that always says "no failure" is {_pct(payload['ai4i']['null_accuracy'])} accurate. The split is stratified 75/25, seed 42. Features: type (L is the reference), air temperature, process temperature, rpm, torque, tool wear, power (torque × rpm), and temperature difference.

{chr(10).join(mode_lines)}

RNF has {payload['ai4i']['rnf_rows']} rows. The dataset defines it as a random failure with no causal signal, so it is stored and not used as a target. Mode counts in the full file: {', '.join(f"{name.upper()} {count}" for name, count in payload['ai4i']['mode_counts'].items())}.

## Does the morning list beat "fix the old machines"?

{back['sentence']}

The ranking in that sentence is the published formula, priority = probability × impact × parts factor. It does not use the 24-hour "just serviced" queue adjustment. Parts and impact are simulated, so this is a test of the weighting scheme on the synthetic plant, not of a real storeroom.

## What the priority list is worth, in the planning rates

{savings_section(back['savings'])}

Demo plant clock: {payload['demo_as_of']}. That morning is the November Monday whose priority scores are most spread out, and at least one machine is out of the green band when such a Monday exists. It was not chosen by looking at which machine failed later.
"""
