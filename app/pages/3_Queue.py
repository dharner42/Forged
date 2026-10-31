"""The full ranked work queue and the open work orders."""

from pathlib import Path

import streamlit as st

from app.bootstrap import install

install(Path(__file__))

from app import db  # noqa: E402
from app.ui import header, inject, render_shift_plan  # noqa: E402
from models.shift_plan import plan_shift  # noqa: E402

st.set_page_config(page_title="Forge — Work queue", page_icon="⚙", layout="wide")
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
    header(
        "Work queue",
        "Ranked by queue score. A repair in the last 24 hours moves a machine down without erasing its probability.",
        clock.strftime("%a %d %b %Y, %H:%M"),
    )

    render_shift_plan(plan_shift(fleet, db.technicians(con), clock))
    orders = db.open_work_orders(con, clock)
    st.subheader(f"Open work orders ({len(orders)})")
    if orders.empty:
        st.info("No open work orders at this plant clock. Create one from the list below.")
    else:
        st.dataframe(orders, use_container_width=True, hide_index=True)
        choice = st.selectbox(
            "Close a work order",
            orders["work_order_id"].astype(int).tolist(),
            format_func=lambda wid: f"WO {wid} · machine {int(orders.loc[orders.work_order_id.eq(wid), 'machine_id'].iloc[0])}",
        )
        if st.button("Mark repaired", type="primary"):
            st.session_state["flash"] = db.mark_repaired(con, int(choice))
            st.rerun()

    st.subheader("Ranked machines")
    fleet = fleet.copy()
    fleet.insert(0, "plant_rank", range(1, len(fleet) + 1))
    lines = ["All lines"] + sorted(fleet["line"].unique().tolist())
    bands = ["All bands", "red", "amber", "green"]
    f1, f2 = st.columns(2)
    line = f1.selectbox("Line (SIMULATED)", lines)
    band = f2.selectbox("Band", bands)
    view = fleet.copy()
    if line != "All lines":
        view = view[view.line == line]
    if band != "All bands":
        view = view[view.band == band]
    if view.empty:
        st.info("Nothing matches those filters.")
        return

    display = view.copy()
    display.insert(0, "Rank", display["plant_rank"])
    display["P(fail 24h)"] = (display["p_fail_24h"] * 100).map(lambda v: f"{v:.1f}%")
    display["Priority"] = display["priority_score"].map(lambda v: f"{v:.2f}")
    display["Queue"] = display["queue_score"].map(lambda v: f"{v:.2f}")
    display["Work order"] = display["work_order_id"].map(lambda v: "" if pd_isna(v) else str(int(v)))
    st.dataframe(
        display.rename(
            columns={
                "machine_id": "Machine",
                "line": "Line (SIMULATED)",
                "model": "Model",
                "age_years": "Age",
                "production_impact": "Impact (SIMULATED)",
                "predicted_component": "Component",
                "band": "Band",
                "top_reason": "Why",
            }
        )[
            [
                "Rank",
                "Machine",
                "Line (SIMULATED)",
                "Model",
                "Age",
                "Impact (SIMULATED)",
                "P(fail 24h)",
                "Priority",
                "Queue",
                "Band",
                "Component",
                "Work order",
                "Why",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        height=420,
    )
    picked = st.selectbox("Machine", view["machine_id"].astype(int).tolist(), format_func=lambda mid: f"Machine {mid}")
    b1, b2 = st.columns(2)
    if b1.button("Open machine"):
        st.session_state["machine_id"] = int(picked)
        st.switch_page("pages/2_Machine.py")
    if b2.button("Create work order"):
        st.session_state["flash"] = db.create_work_order(con, int(picked))
        st.rerun()
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))


def pd_isna(value) -> bool:
    import pandas as pd

    return bool(pd.isna(value))


if __name__ == "__main__":
    main()
else:
    main()
