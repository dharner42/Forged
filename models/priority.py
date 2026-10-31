"""Priority = P(fail in 24h) x production impact x parts factor.

The queue then applies a shop rule the formula does not: a machine serviced in
the last 24 hours is multiplied by SERVICE_SUPPRESSION so it drops down the list.
The September–December backtest ranks by the formula alone.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import (
    PARTS_OK_FACTOR,
    PARTS_SHORTAGE_FACTOR,
    SERVICE_SUPPRESSION,
    SERVICE_WINDOW_HOURS,
)
from models.features import COMPONENTS, ERROR_CODES, SENSOR_COLS

SENSOR_LABELS = {
    "volt_mean_24h": "voltage",
    "rotate_mean_24h": "rotation",
    "pressure_mean_24h": "pressure",
    "vibration_mean_24h": "vibration",
}


def parts_factor(on_hand: float, reorder_point: float) -> float:
    """1.5 when the part is out of stock or below its reorder point, else 1."""
    if pd.isna(on_hand) or pd.isna(reorder_point):
        return PARTS_SHORTAGE_FACTOR
    if on_hand == 0 or on_hand < reorder_point:
        return PARTS_SHORTAGE_FACTOR
    return PARTS_OK_FACTOR


def priority_score(p_fail: float, impact: float, on_hand: float, reorder_point: float) -> float:
    return float(p_fail) * float(impact) * parts_factor(on_hand, reorder_point)


def queue_score(priority: float, serviced_within_24h: bool) -> float:
    if serviced_within_24h:
        return float(priority) * SERVICE_SUPPRESSION
    return float(priority)


def band_for(p_fail: float, red_at: float, amber_at: float) -> str:
    if p_fail >= red_at:
        return "red"
    if p_fail >= amber_at:
        return "amber"
    return "green"


def _age_phrase(component: str, hours: float) -> str:
    if hours < 48:
        return f"{component} last replaced {hours:.0f} hours ago"
    return f"{component} last replaced {hours / 24:.0f} days ago"


def build_reason(
    *,
    predicted_component: str,
    hours_since: float,
    sensor_means: dict[str, float],
    sensor_p75: dict[str, float],
    error_counts: dict[str, float],
    parts_tight: bool,
    serviced: bool,
    low_risk: bool = False,
) -> str:
    if low_risk:
        stock = ""
        if parts_tight:
            stock = (
                f" {predicted_component} part is out of stock or below its reorder point (SIMULATED). "
                "That changes the parts factor, not the failure probability."
            )
        prefix = "Serviced in the last 24 hours. " if serviced else ""
        return prefix + "Low 24-hour failure risk." + stock
    bits: list[str] = []
    best_label = None
    best_ratio = 1.0
    for column, label in SENSOR_LABELS.items():
        p75 = float(sensor_p75.get(column, np.nan))
        value = float(sensor_means.get(column, np.nan))
        if np.isnan(p75) or np.isnan(value) or p75 <= 0:
            continue
        if value >= p75 and value / p75 >= best_ratio:
            best_ratio = value / p75
            best_label = label
    if best_label:
        bits.append(f"high {best_label}")

    ranked_errors = sorted(error_counts.items(), key=lambda item: item[1], reverse=True)
    error_bits = [f"{code} x{int(count)}" for code, count in ranked_errors if count >= 1][:2]
    if error_bits:
        bits.append("recent " + ", ".join(error_bits))

    bits.append(_age_phrase(predicted_component, float(hours_since)))
    if parts_tight:
        bits.append(f"{predicted_component} part is out of stock or below reorder point (SIMULATED)")
    reason = "; ".join(bits)
    if serviced:
        reason = "Serviced in the last 24 hours, so the queue score is reduced. " + reason
    return reason


def _p75_by_time(frame: pd.DataFrame) -> dict[pd.Timestamp, dict[str, float]]:
    columns = [f"{sensor}_mean_24h" for sensor in SENSOR_COLS]
    tables: dict[pd.Timestamp, dict[str, float]] = {}
    for ts, group in frame.groupby("ts"):
        tables[pd.Timestamp(ts)] = {column: float(group[column].quantile(0.75)) for column in columns}
    return tables


def assemble_queue(frame: pd.DataFrame, red_at: float, amber_at: float) -> pd.DataFrame:
    """Add parts factor, both scores, band, and the reason string.

    `frame` needs the model outputs plus impact, stock, sensor means, error counts,
    and hours_since_comp1..4. Service suppression fires when any component was
    replaced within the window, not only the predicted one.
    """
    out = frame.copy()
    p75_lookup = _p75_by_time(out)
    factors = []
    priorities = []
    queues = []
    bands = []
    reasons = []
    serviced_flags = []
    for row in out.itertuples(index=False):
        factor = parts_factor(row.on_hand, row.reorder_point)
        priority = float(row.p_fail_24h) * float(row.production_impact) * factor
        hours = {component: float(getattr(row, f"hours_since_{component}")) for component in COMPONENTS}
        serviced = min(hours.values()) <= SERVICE_WINDOW_HOURS
        queued = queue_score(priority, serviced)
        sensor_means = {f"{sensor}_mean_24h": float(getattr(row, f"{sensor}_mean_24h")) for sensor in SENSOR_COLS}
        error_counts = {code: float(getattr(row, f"{code}_count_24h")) for code in ERROR_CODES}
        component = str(row.predicted_component)
        reason = build_reason(
            predicted_component=component,
            hours_since=hours.get(component, min(hours.values())),
            sensor_means=sensor_means,
            sensor_p75=p75_lookup[pd.Timestamp(row.ts)],
            error_counts=error_counts,
            parts_tight=factor > 1,
            serviced=serviced,
            low_risk=float(row.p_fail_24h) < amber_at,
        )
        factors.append(factor)
        priorities.append(priority)
        queues.append(queued)
        bands.append(band_for(float(row.p_fail_24h), red_at, amber_at))
        reasons.append(reason)
        serviced_flags.append(serviced)
    out["parts_factor"] = factors
    out["priority_score"] = priorities
    out["queue_score"] = queues
    out["band"] = bands
    out["top_reason"] = reasons
    out["serviced_within_24h"] = serviced_flags
    return out
