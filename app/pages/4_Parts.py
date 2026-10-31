"""SIMULATED parts and the SIMULATED technician roster."""

from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from app.bootstrap import install

install(Path(__file__))

from app import db  # noqa: E402
from app.ui import chart_layout, header, inject  # noqa: E402

st.set_page_config(page_title="Forge — Parts", page_icon="⚙", layout="wide")
inject()


def main() -> None:
    con = db.connection()
    if con is None:
        st.error("No warehouse. Run `make pipeline` and `make train`.")
        return
    clock = db.plant_clock(con)
    header(
        "Parts and technicians",
        "Every number on this page is SIMULATED. The public datasets have no storeroom and no roster.",
        clock.strftime("%a %d %b %Y, %H:%M"),
    )
    st.markdown(
        '<span class="pill sim">SIMULATED</span> '
        "Stock, reorder points, lead times, technician names, skills, and shifts were generated for the demo. "
        "They are not measurements.",
        unsafe_allow_html=True,
    )

    fleet = db.fleet(con)
    parts = db.parts_table(con)
    if fleet.empty:
        demand = {component: 0 for component in parts["component"]}
    else:
        risky = fleet[fleet["band"].isin(["red", "amber"])]
        demand = risky.groupby("predicted_component").size().to_dict()
    parts = parts.copy()
    parts["predicted_demand"] = parts["component"].map(lambda component: int(demand.get(component, 0)))
    parts["alert"] = (parts["on_hand"] < parts["reorder_point"]) | (parts["on_hand"] < parts["predicted_demand"]) | (
        parts["on_hand"] == 0
    )
    parts["why"] = parts.apply(_why, axis=1)

    st.subheader("Will the part arrive before the risky window closes?")
    st.markdown(
        "Predicted demand is the count of amber and red machines whose likely failing component is this part. "
        "The model horizon is 24 hours. Every lead time on this board is longer than that, so a stockout "
        "cannot be filled before the risky window closes."
    )
    if not parts["alert"].any():
        st.success("No part is below its reorder point, and predicted demand does not exceed stock.")
    else:
        short = ", ".join(parts.loc[parts.alert, "component"].tolist())
        st.error(f"Short parts: {short}. These stock figures are SIMULATED.")

    fig = go.Figure()
    fig.add_trace(go.Bar(name="On hand (SIMULATED)", x=parts["component"], y=parts["on_hand"], marker_color="#1f4e5f"))
    fig.add_trace(go.Bar(name="Reorder point (SIMULATED)", x=parts["component"], y=parts["reorder_point"], marker_color="#e0c27a"))
    fig.add_trace(go.Bar(name="Amber + red demand", x=parts["component"], y=parts["predicted_demand"], marker_color="#9f2d2d"))
    fig.update_layout(barmode="group")
    st.plotly_chart(chart_layout(fig, "Stock versus what the current queue is about to ask for", height=360), use_container_width=True)

    show = parts.rename(
        columns={
            "component": "Component",
            "on_hand": "On hand (SIMULATED)",
            "reorder_point": "Reorder point (SIMULATED)",
            "lead_time_days": "Lead time, days (SIMULATED)",
            "predicted_demand": "Predicted demand",
            "why": "Flag",
        }
    )
    st.dataframe(
        show[
            [
                "Component",
                "On hand (SIMULATED)",
                "Reorder point (SIMULATED)",
                "Lead time, days (SIMULATED)",
                "Predicted demand",
                "Flag",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Technicians")
    st.caption("Names, skills, and shifts are SIMULATED. A new work order picks the matching skill with the fewest open jobs.")
    techs = db.technicians(con)
    st.dataframe(
        techs.rename(
            columns={
                "technician_id": "Id",
                "name": "Name (SIMULATED)",
                "skill": "Skill (SIMULATED)",
                "shift": "Shift (SIMULATED)",
                "open_work_orders": "Open work orders",
            }
        )[["Id", "Name (SIMULATED)", "Skill (SIMULATED)", "Shift (SIMULATED)", "Open work orders"]],
        use_container_width=True,
        hide_index=True,
    )
    st.markdown(
        "Skill map used for assignment, also SIMULATED, because the dataset never says what comp1–comp4 are: "
        "comp1 mechanical, comp2 hydraulics, comp3 electrical, comp4 general."
    )


def _why(row) -> str:
    reasons = []
    if int(row.on_hand) == 0:
        reasons.append("out of stock")
    elif int(row.on_hand) < int(row.reorder_point):
        reasons.append("below reorder point")
    if int(row.on_hand) < int(row.predicted_demand):
        reasons.append("demand exceeds stock inside the lead time")
    if not reasons:
        return ""
    return "; ".join(reasons) + " (SIMULATED)"


if __name__ == "__main__":
    main()
else:
    main()
