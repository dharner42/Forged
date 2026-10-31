"""Shared scoring helpers."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
)


def rmse(y_true, y_pred) -> float:
    err = np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float)
    return float(np.sqrt(np.mean(err**2)))


def best_f1_threshold(y_true, proba) -> float:
    precision, recall, thresholds = precision_recall_curve(y_true, proba)
    if len(thresholds) == 0:
        return 0.5
    f1 = 2 * precision[:-1] * recall[:-1] / np.clip(precision[:-1] + recall[:-1], 1e-12, None)
    f1 = np.nan_to_num(f1, nan=0.0)
    return float(thresholds[int(np.argmax(f1))])


def threshold_for_recall(y_true, proba, target_recall: float) -> float:
    _precision, recall, thresholds = precision_recall_curve(y_true, proba)
    if len(thresholds) == 0:
        return 0.5
    eligible = recall[:-1] >= target_recall
    if not eligible.any():
        return float(np.min(thresholds))
    return float(np.max(thresholds[eligible]))


def classification_at_threshold(y_true, proba, threshold: float) -> dict:
    y_true = np.asarray(y_true).astype(int)
    proba = np.asarray(proba, dtype=float)
    predicted = (proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, predicted, labels=[0, 1]).ravel()
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, zero_division=0)),
        "f1": float(f1_score(y_true, predicted, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, proba)) if y_true.sum() else 0.0,
        "rows": int(len(y_true)),
        "positives": int(y_true.sum()),
        "prevalence": float(y_true.mean()) if len(y_true) else 0.0,
        "predicted_positive_rate": float(predicted.mean()) if len(predicted) else 0.0,
        "mean_predicted": float(proba.mean()) if len(proba) else 0.0,
        "tp": int(tp),
        "fp": int(fp),
        "fn": int(fn),
        "tn": int(tn),
    }
