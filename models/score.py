"""Turn model probabilities into the morning queue and the plant-clock snapshot."""

from __future__ import annotations

import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xgboost as xgb

from config import LABEL_CUTOFF, SERVICE_SUPPRESSION, TEST_START
from models.azure_risk import design_matrix, load_bundle, predict_calibrated, predict_component
from models.features import PHRASES, azure_feature_frame
from models.plots import AMBER, NAVY, apply_style, save
from models.costs import (
    cost_of_selection,
    expected_random_list_cost,
    savings_from_hit_rates,
    summarize_machine_costs,
)
from models.priority import assemble_queue
from pipeline.warehouse import connect, insert_df, write_clock

PREDICTION_COLUMNS = [
    "machine_id",
    "ts",
    "p_fail_24h",
    "predicted_component",
    "parts_factor",
    "priority_score",
    "queue_score",
    "band",
    "top_reason",
]


def contribution_payloads(bundle: dict, matrix: pd.DataFrame) -> list[str]:
    """XGBoost's per-feature contributions for each row. The last column is the bias."""
    booster = bundle["model"].get_booster()
    values = booster.predict(xgb.DMatrix(matrix, feature_names=list(matrix.columns)), pred_contribs=True)
    payloads = []
    names = list(matrix.columns)
    for row_index in range(len(matrix)):
        pairs = [
            (name, float(matrix.iloc[row_index][name]), float(values[row_index, feature_index]))
            for feature_index, name in enumerate(names)
        ]
        pairs.sort(key=lambda item: abs(item[2]), reverse=True)
        payloads.append(
            json.dumps(
                [
                    {
                        "feature": name,
                        "label": PHRASES.get(name, name),
                        "value": round(value, 4),
                        "contribution": round(contribution, 5),
                    }
                    for name, value, contribution in pairs[:8]
                ]
            )
        )
    return payloads


def score_rows(feature_rows: pd.DataFrame, bundle: dict, machines: pd.DataFrame, parts: pd.DataFrame, with_contribs: bool) -> pd.DataFrame:
    medians = pd.Series(bundle["medians"])
    matrix, _ = design_matrix(feature_rows, bundle["features"], medians)
    scored = feature_rows.copy()
    scored["p_fail_24h"] = predict_calibrated(bundle, matrix)
    scored["predicted_component"] = predict_component(bundle, matrix)
    if "production_impact" in scored.columns:
        scored = scored.drop(columns=["production_impact"])
    scored = scored.merge(machines[["machine_id", "production_impact"]], on="machine_id", how="left")
    scored = scored.merge(
        parts[["component", "on_hand", "reorder_point"]],
        left_on="predicted_component",
        right_on="component",
        how="left",
    )
    assembled = assemble_queue(scored, red_at=bundle["threshold"], amber_at=bundle["amber_threshold"])
    if with_contribs:
        # Merges above are one-to-one, so row order still matches the matrix.
        assembled["contrib_json"] = contribution_payloads(bundle, matrix)
    return assembled


def _prediction_frame(assembled: pd.DataFrame) -> pd.DataFrame:
    out = assembled.loc[:, PREDICTION_COLUMNS].copy()
    out["machine_id"] = out["machine_id"].astype(int)
    out["ts"] = pd.to_datetime(out["ts"])
    out["predicted_component"] = out["predicted_component"].astype(str)
    return out


def backtest(daily: pd.DataFrame, failures: pd.DataFrame, machines: pd.DataFrame, parts: pd.DataFrame | None = None) -> dict:
    """How often the morning top 10 fails within 7 days, versus two naive lists.

    When ``parts`` is provided, the same mornings are priced with the rates in
    ``cost_assumptions.py``. The hit counts do not change.
    """
    daily = daily.copy()
    daily["ts"] = pd.to_datetime(daily["ts"])
    failures = failures.copy()
    failures["ts"] = pd.to_datetime(failures["ts"])
    horizon = pd.Timedelta(days=7)
    obs_end = pd.Timestamp("2015-12-31 06:00:00")
    days = [
        pd.Timestamp(ts)
        for ts in sorted(daily["ts"].unique())
        if pd.Timestamp(ts) + horizon <= obs_end
    ]
    oldest = (
        machines.sort_values(["age_years", "machine_id"], ascending=[False, True]).head(10)["machine_id"].astype(int).tolist()
    )
    priority_hits = []
    probability_hits = []
    oldest_hits = []
    random_hits = []
    priority_costs = []
    oldest_costs = []
    random_costs = []
    n_machines = int(machines["machine_id"].nunique()) if len(machines) else 0
    for day in days:
        group = daily[daily["ts"] == day]
        window = failures[(failures["ts"] > day) & (failures["ts"] <= day + horizon)]
        failed = set(int(machine_id) for machine_id in window["machine_id"].unique())

        def hits(ids) -> int:
            return sum(int(machine_id) in failed for machine_id in ids)

        by_priority = group.sort_values(["priority_score", "machine_id"], ascending=[False, True]).head(10)
        by_probability = group.sort_values(["p_fail_24h", "machine_id"], ascending=[False, True]).head(10)
        priority_hits.append(hits(by_priority["machine_id"]))
        probability_hits.append(hits(by_probability["machine_id"]))
        oldest_hits.append(hits(oldest))
        random_hits.append(10.0 * len(failed) / 100.0)
        if parts is not None:
            priority_costs.append(cost_of_selection(by_priority["machine_id"], window, machines, parts))
            oldest_costs.append(cost_of_selection(oldest, window, machines, parts))
            random_costs.append(
                expected_random_list_cost(window, machines, parts, n_machines=n_machines, list_size=10)
            )

    def avg(values) -> float:
        return float(np.mean(values)) if values else 0.0

    metrics = {
        "mornings": len(days),
        "horizon_days": 7,
        "priority_avg_hits": avg(priority_hits),
        "probability_avg_hits": avg(probability_hits),
        "oldest_avg_hits": avg(oldest_hits),
        "random10_avg_hits": avg(random_hits),
        "service_suppression": SERVICE_SUPPRESSION,
        "ranked_by": "priority_score (the published formula, not the 24-hour service rule)",
    }
    if parts is not None and priority_costs:
        metrics["savings"] = summarize_machine_costs(priority_costs, oldest_costs, random_costs)
    else:
        metrics["savings"] = savings_from_hit_rates(metrics)
    metrics["sentence"] = (
        f"On {metrics['mornings']} mornings from September through late December, "
        f"the priority formula's top 10 had an average of {metrics['priority_avg_hits']:.2f} machines "
        f"that failed within 7 days, versus {metrics['oldest_avg_hits']:.2f} for oldest-machine-first, "
        f"{metrics['probability_avg_hits']:.2f} for failure probability alone, "
        f"and {metrics['random10_avg_hits']:.2f} for a random 10 machines."
    )
    _plot_backtest(days, priority_hits, oldest_hits)
    return metrics


def _plot_backtest(days, priority_hits, oldest_hits) -> None:
    if not days:
        return
    priority = pd.Series(priority_hits, index=pd.to_datetime(days)).resample("W").mean()
    oldest = pd.Series(oldest_hits, index=pd.to_datetime(days)).resample("W").mean()
    apply_style()
    fig, ax = plt.subplots(figsize=(7.4, 4.3))
    ax.plot(priority.index, priority.values, color=NAVY, linewidth=2, label="Priority formula")
    ax.plot(oldest.index, oldest.values, color=AMBER, linewidth=2, label="Oldest machine first")
    ax.set_ylabel("Top-10 machines that failed within 7 days")
    ax.set_title("Morning list, averaged by week")
    ax.legend(frameon=False)
    fig.autofmt_xdate()
    save(fig, "backtest_lift.png")


def choose_demo_morning(daily: pd.DataFrame) -> pd.Timestamp:
    """A November Monday with a wide priority spread.

    The choice does not look at which machine later failed. Metrics use every
    morning, not this one.
    """
    daily = daily.copy()
    daily["ts"] = pd.to_datetime(daily["ts"])
    best_ts = None
    best_key = None
    for ts, group in daily.groupby("ts"):
        stamp = pd.Timestamp(ts)
        if stamp.month != 11 or stamp.dayofweek != 0 or stamp.hour != 6:
            continue
        spread = float(group["priority_score"].max() - group["priority_score"].median())
        interesting = bool((group["band"] != "green").any())
        key = (int(interesting), spread)
        if best_key is None or key > best_key:
            best_key = key
            best_ts = stamp
    if best_ts is None:
        return pd.Timestamp("2015-11-16 06:00:00")
    return best_ts


def publish_scores(trained: dict) -> dict:
    """Write September–December morning scores and the demo clock snapshot."""
    mornings = score_rows(
        trained["frame"].loc[
            (trained["frame"]["ts"] >= TEST_START)
            & (trained["frame"]["ts"] <= LABEL_CUTOFF)
            & (trained["frame"]["ts"].dt.hour == 6)
            & (trained["frame"]["ts"].dt.minute == 0)
        ],
        trained["bundle"],
        trained["machines"],
        trained["parts"],
        with_contribs=False,
    )
    report = backtest(mornings, trained["failures"], trained["machines"], trained["parts"])
    demo_as_of = choose_demo_morning(mornings)
    con = connect()
    try:
        con.execute("DELETE FROM predictions")
        insert_df(con, "predictions", _prediction_frame(mornings), PREDICTION_COLUMNS)
    finally:
        con.close()
    score_current(
        demo_as_of,
        note="November Monday with the widest priority spread. Not chosen by later failures.",
    )
    report["demo_as_of"] = str(demo_as_of)
    return report


def score_current(as_of, con=None, note: str = "Plant clock") -> pd.Timestamp:
    """Rescore every machine at `as_of` using only information known by then."""
    as_of = pd.Timestamp(as_of)
    bundle = load_bundle()
    own = con is None
    if own:
        con = connect()
    try:
        start = as_of - pd.Timedelta(hours=48)
        telemetry = con.execute(
            """
            SELECT machine_id, ts, volt, rotate, pressure, vibration
            FROM sensor_readings
            WHERE ts <= ? AND ts > ?
            """,
            [as_of.to_pydatetime(), start.to_pydatetime()],
        ).fetchdf()
        errors = con.execute(
            "SELECT machine_id, ts, error_code FROM faults WHERE ts <= ? AND ts > ?",
            [as_of.to_pydatetime(), start.to_pydatetime()],
        ).fetchdf()
        maintenance = con.execute(
            "SELECT machine_id, ts, component FROM maintenance_events WHERE ts <= ?",
            [as_of.to_pydatetime()],
        ).fetchdf()
        machines = con.execute(
            "SELECT machine_id, model, age_years, line, production_impact FROM machines"
        ).fetchdf()
        parts = con.execute("SELECT component, on_hand, reorder_point FROM parts").fetchdf()
        if telemetry.empty:
            raise RuntimeError(f"No telemetry at or before {as_of}.")
        for frame in (telemetry, errors, maintenance):
            if "ts" in frame.columns:
                frame["ts"] = pd.to_datetime(frame["ts"])
        features = azure_feature_frame(telemetry, errors, maintenance, machines)
        latest = features.sort_values("ts").groupby("machine_id", as_index=False).tail(1)
        scored = score_rows(latest, bundle, machines, parts, with_contribs=True)
        scored["ts"] = as_of
        payload = _prediction_frame(scored)
        payload["serviced_within_24h"] = scored["serviced_within_24h"].astype(bool).to_numpy()
        payload["contrib_json"] = scored["contrib_json"].tolist()
        con.execute("DELETE FROM current_scores")
        insert_df(
            con,
            "current_scores",
            payload,
            PREDICTION_COLUMNS + ["serviced_within_24h", "contrib_json"],
        )
        write_clock(con, as_of, note)
    finally:
        if own:
            con.close()
    return as_of
