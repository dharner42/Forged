"""One machine: sensors, why it ranks, parts, and the work order."""

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from app.bootstrap import install

install(Path(__file__))

from app import db  # noqa: E402
from app.ui import band_html, chart_layout, header, inject, sample_banner  # noqa: E402
from models.shift_plan import plan_shift  # noqa: E402

st.set_page_config(page_title="Forged Machine Monitoring — Machine", page_icon="⚙", layout="wide")
inject()


def main() -> None:
    con = db.connection()
    if con is None:
        st.error("No warehouse. Run `make pipeline` and `make train`.")
        return
    fleet = db.fleet(con)
    if fleet.empty:
        st.warning("No scores yet. Run `make train`.")
        return
    clock = db.plant_clock(con)
    header("Machine", "Sensors, the factors behind the risk, and the part it would need.", clock.strftime("%a %d %b %Y, %H:%M"))
    sample = db.is_sample_plant(con)
    sample_banner(sample)

    ids = fleet["machine_id"].astype(int).tolist()
    default = int(st.session_state.get("machine_id", ids[0]))
    if default not in ids:
        default = ids[0]
    machine_id = st.selectbox("Machine", ids, index=ids.index(default))
    st.session_state["machine_id"] = int(machine_id)
    row = fleet.loc[fleet.machine_id.eq(machine_id)].iloc[0]

    left, right = st.columns([1.35, 1])
    with right:
        st.markdown(band_html(str(row.band)) + f"  &nbsp; **{row.p_fail_24h:.1%}** chance of a failure in 24 hours", unsafe_allow_html=True)
        st.markdown(
            f"Priority **{row.priority_score:.2f}** = {row.p_fail_24h:.1%} × impact {int(row.production_impact)} "
            f"× parts factor {row.parts_factor:.1f}"
        )
        st.markdown(f"Queue score **{row.queue_score:.2f}**")
        st.markdown(row.top_reason)
        shift = plan_shift(fleet, db.technicians(con), clock)
        shift_note = shift.note_for(int(machine_id))
        if shift_note:
            st.info(shift_note)
        if float(row.p_fail_24h) >= 0.99 or float(row.p_fail_24h) <= 0.01:
            st.caption(
                "Calibrated scores on this dataset sit near 0% or 100%. "
                "Check the sensor reason before you dispatch. A real plant will not be this sharp."
            )
        if sample:
            st.caption(
                "Impact, the parts factor, and the technician roster are SIMULATED. "
                "On this bundled sample the probability is authored so the screen can rank machines. It is not the Azure model."
            )
        else:
            st.caption("Impact, the parts factor, and the technician roster are SIMULATED. The probability is the model.")
        contribs = []
        if isinstance(row.contrib_json, str) and row.contrib_json:
            contribs = json.loads(row.contrib_json)
        if contribs:
            fig = go.Figure(
                go.Bar(
                    x=[item["contribution"] for item in contribs][::-1],
                    y=[item["label"] for item in contribs][::-1],
                    orientation="h",
                    marker_color=["#9f2d2d" if item["contribution"] > 0 else "#1d6b45" for item in contribs][::-1],
                )
            )
            st.plotly_chart(
                chart_layout(fig, "What is pushing this prediction", height=360),
                use_container_width=True,
            )
            st.caption(
                "Red raises the raw model score, green lowers it. These are XGBoost feature contributions "
                "before calibration, so they explain the ranking rather than a percentage-point change."
            )
        on_hand = row.on_hand
        reorder = row.reorder_point
        if pd.notna(on_hand):
            state = "short" if int(on_hand) == 0 or int(on_hand) < int(reorder) else "in stock"
            st.markdown(
                f"**{row.predicted_component}** part: {int(on_hand)} on hand, reorder point {int(reorder)}, "
                f"lead time {int(row.lead_time_days)} days. Status: **{state}**. Stock figures are SIMULATED."
            )
        if pd.notna(row.work_order_id):
            st.info(
                f"Work order {int(row.work_order_id)} is open, assigned to {row.technician_name} "
                f"({row.technician_shift}). The name is SIMULATED."
            )
            if st.button("Mark repaired", type="primary"):
                st.session_state["flash"] = db.mark_repaired(con, int(row.work_order_id))
                st.rerun()
        else:
            if st.button("Create work order", type="primary"):
                st.session_state["flash"] = db.create_work_order(con, int(machine_id))
                st.rerun()
        if st.session_state.get("flash"):
            st.success(st.session_state.pop("flash"))

    with left:
        sensors = db.sensor_history(con, int(machine_id), clock)
        if sensors.empty:
            st.info("No sensor history at or before the plant clock.")
        else:
            fig = make_subplots(rows=4, cols=1, shared_xaxes=True, subplot_titles=("Voltage", "Rotation", "Pressure", "Vibration"))
            colors = ["#1f4e5f", "#3d6b7a", "#8a5a00", "#9f2d2d"]
            for index, column in enumerate(["volt", "rotate", "pressure", "vibration"]):
                fig.add_trace(
                    go.Scatter(x=sensors["ts"], y=sensors[column], line=dict(color=colors[index], width=1.4), showlegend=False),
                    row=index + 1,
                    col=1,
                )
            fig.update_layout(height=640, margin=dict(l=8, r=8, t=28, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Last 14 days at or before the plant clock. Events after the clock are hidden.")

    events = db.machine_events(con, int(machine_id), clock)
    e1, e2, e3 = st.columns(3)
    e1.markdown("**Recent errors**")
    e1.dataframe(events["faults"], use_container_width=True, hide_index=True)
    e2.markdown("**Replacements**")
    e2.dataframe(events["maintenance"], use_container_width=True, hide_index=True)
    e2.caption("Scheduled rows come from the Azure maintenance file. Unscheduled rows are repairs you log here.")
    e3.markdown("**Recorded failures**")
    e3.dataframe(events["failures"], use_container_width=True, hide_index=True)
    e3.caption("Failures after the plant clock are not shown.")


if __name__ == "__main__":
    main()
else:
    main()
