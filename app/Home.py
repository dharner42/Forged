"""Fleet readiness: the shift lead's first screen."""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.bootstrap import install

install(Path(__file__))

from app import db  # noqa: E402
from app.ui import chart_layout, header, inject, render_shift_plan  # noqa: E402
from models.shift_plan import plan_shift  # noqa: E402
from config import CLOCK_MAX, CLOCK_MIN  # noqa: E402

st.set_page_config(page_title="Forged Machine Monitoring — Fleet", page_icon="⚙", layout="wide")
inject()


def _clock_label(stamp: pd.Timestamp) -> str:
    return stamp.strftime("%a %d %b %Y, %H:%M")


def _part_alerts(fleet: pd.DataFrame, parts: pd.DataFrame) -> pd.DataFrame:
    risky = fleet[fleet["band"].isin(["red", "amber"])]
    demand = risky.groupby("predicted_component").size().rename("demand")
    board = parts.merge(demand, left_on="component", right_index=True, how="left")
    board["demand"] = board["demand"].fillna(0).astype(int)
    board["alert"] = (board["on_hand"] < board["reorder_point"]) | (board["on_hand"] < board["demand"]) | (
        board["on_hand"] == 0
    )
    return board


def main() -> None:
    con = db.connection()
    if con is None:
        header("Fleet readiness", "The warehouse has not been built yet.", "No plant clock")
        st.error("No warehouse found. From the repo root run `make download`, then `make pipeline`, then `make train`.")
        return

    try:
        clock = db.plant_clock(con)
    except Exception as exc:
        st.error(str(exc))
        return

    fleet = db.fleet(con)
    header(
        "Fleet readiness",
        "What to fix first on this shift. Scores use only readings at or before the plant clock.",
        _clock_label(clock),
    )

    if fleet.empty:
        st.warning("Machines are loaded, but there is no score snapshot. Run `make train`.")
        return

    parts = db.parts_table(con)
    alerts = _part_alerts(fleet, parts)
    n = len(fleet)
    greens = int((fleet.band == "green").sum())
    ambers = int((fleet.band == "amber").sum())
    reds = int((fleet.band == "red").sum())
    readiness = greens / n if n else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("In the green", f"{readiness:.0%}")
    c2.metric("Green", greens)
    c3.metric("Amber", ambers)
    c4.metric("Red", reds)
    c5.metric("Part alerts", int(alerts["alert"].sum()))
    st.caption(
        "Green means the calibrated 24-hour failure probability is under the amber cutoff chosen on August 2015. "
        "On this synthetic plant the calibrated score usually sits near 0 or near 1, so amber is rare. "
        "Line and production impact are SIMULATED. Part alerts are SIMULATED stock."
    )

    st.subheader("This shift")
    render_shift_plan(plan_shift(fleet, db.technicians(con), clock))

    history = db.morning_history(con, clock)
    left, right = st.columns([1.5, 1])
    with left:
        if history.empty:
            st.info("No morning history at or before this clock. Training writes September–December mornings.")
        else:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=history["ts"], y=history["mean_p"], name="Mean P(fail in 24h)", line=dict(color="#1f4e5f", width=2)))
            fig.add_trace(go.Bar(x=history["ts"], y=history["reds"], name="Red machines", marker_color="#e7b2ae", opacity=0.85, yaxis="y2"))
            fig.update_layout(yaxis2=dict(overlaying="y", side="right", title="Red machines", showgrid=False))
            st.plotly_chart(chart_layout(fig, "Test-period mornings still visible at this clock", height=340), use_container_width=True)
            st.caption("History stops at the plant clock. Later mornings exist in the warehouse and stay hidden.")
    with right:
        st.markdown("**How to read a row**")
        st.markdown(
            "Priority = P(fail in 24 hours) × production impact × parts factor. "
            "The parts factor is **1.5** when that component's part is out of stock or below its reorder point, otherwise **1**. "
            "Impact is a SIMULATED 1–5 rating."
        )
        st.markdown(
            "If any component was replaced in the last 24 hours, the queue score is 15% of the formula. "
            "The probability itself is still shown. The September–December backtest ranks by the formula only."
        )
        report = db.metrics()
        if report and report.get("backtest"):
            st.markdown(report["backtest"]["sentence"])

    st.subheader("Fix these first")
    show = fleet.head(8).copy()
    show["P(fail 24h)"] = (show["p_fail_24h"] * 100).map(lambda v: f"{v:.1f}%")
    show["Priority"] = show["priority_score"].map(lambda v: f"{v:.2f}")
    show["Queue"] = show["queue_score"].map(lambda v: f"{v:.2f}")
    show = show.rename(
        columns={
            "machine_id": "Machine",
            "line": "Line (SIMULATED)",
            "production_impact": "Impact (SIMULATED)",
            "predicted_component": "Likely component",
            "band": "Band",
            "top_reason": "Why",
        }
    )
    st.dataframe(
        show[
            [
                "Machine",
                "Line (SIMULATED)",
                "Impact (SIMULATED)",
                "P(fail 24h)",
                "Priority",
                "Queue",
                "Band",
                "Likely component",
                "Why",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        height=320,
    )

    options = fleet["machine_id"].tolist()
    picked = st.selectbox("Open a machine or log an action", options, format_func=lambda mid: f"Machine {mid}")
    a, b, c = st.columns([1, 1, 2])
    if a.button("Open machine", type="primary"):
        st.session_state["machine_id"] = int(picked)
        st.switch_page("pages/2_Machine.py")
    if b.button("Create work order"):
        st.session_state["flash"] = db.create_work_order(con, int(picked))
        st.rerun()
    open_id = fleet.loc[fleet.machine_id.eq(picked), "work_order_id"]
    if c.button("Mark repaired", disabled=bool(open_id.isna().all())):
        st.session_state["flash"] = db.mark_repaired(con, int(open_id.dropna().iloc[0]))
        st.rerun()
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))

    with st.expander("Move the plant clock"):
        st.markdown(
            "The replay does not insert rows one hour at a time. The full year is already in the warehouse. "
            "Moving the clock hides the future and rescores every machine from readings up to that hour."
        )
        with st.form("clock"):
            day = st.date_input(
                "Date",
                value=clock.date(),
                min_value=CLOCK_MIN.date(),
                max_value=CLOCK_MAX.date(),
            )
            hour = st.selectbox("Hour", list(range(24)), index=int(clock.hour))
            submitted = st.form_submit_button("Move plant clock")
        if submitted:
            stamp = pd.Timestamp(day) + pd.Timedelta(hours=int(hour))
            with st.spinner("Rescoring the fleet at the new clock..."):
                db.move_clock(con, stamp)
            st.rerun()
        report = db.metrics()
        if report and report.get("demo_as_of"):
            if st.button("Reset to the demo morning"):
                with st.spinner("Restoring the demo morning..."):
                    db.move_clock(con, pd.Timestamp(report["demo_as_of"]))
                st.rerun()


if __name__ == "__main__":
    main()
else:
    main()
