"""Shop floor: machines laid out by line, colored by band."""

import sys
from pathlib import Path

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "config.py").exists())
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import db
from app.ui import chart_layout, header, inject, sample_banner
from pipeline.seed_ops import LINES

st.set_page_config(page_title="Forged Machine Monitoring — Floorplan", page_icon="⚙", layout="wide")
inject()

BAND_COLOR = {"red": "#c0392b", "amber": "#d08c1b", "green": "#2e8b57"}
BAND_EDGE = {"red": "#6a1b15", "amber": "#7a5010", "green": "#1a5236"}


def _layout(fleet: pd.DataFrame) -> pd.DataFrame:
    """Assign grid (x, y) positions: one row per line, machines packed left-to-right."""
    rows = []
    for row_index, line in enumerate(LINES):
        line_df = fleet[fleet["line"] == line].sort_values("machine_id")
        for col_index, record in enumerate(line_df.itertuples(index=False)):
            rows.append(
                {
                    "machine_id": int(record.machine_id),
                    "line": line,
                    "x": col_index,
                    "y": len(LINES) - 1 - row_index,
                }
            )
    return pd.DataFrame(rows)


def _hover(row: pd.Series) -> str:
    wo = ""
    if pd.notna(row.get("work_order_id")):
        wo = f"<br>Work order {int(row['work_order_id'])}"
        if pd.notna(row.get("technician_name")):
            wo += f" — {row['technician_name']}"
    return (
        f"<b>Machine {int(row['machine_id'])}</b> &nbsp; {row['band'].upper()}"
        f"<br>{row['line']} · {row['model']} · age {row['age_years']:.1f} yr"
        f"<br>Impact (SIMULATED): {int(row['production_impact'])}"
        f"<br>P(fail 24h): {row['p_fail_24h'] * 100:.1f}%"
        f"<br>Priority: {row['priority_score']:.2f} · Queue: {row['queue_score']:.2f}"
        f"<br>Likely component: {row['predicted_component']}"
        f"{wo}"
    )


def _figure(grid: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    cols = max(1, int(grid["x"].max()) + 1)
    # Line backdrops so empty space reads as the aisle for that line.
    for row_index, line in enumerate(LINES):
        y = len(LINES) - 1 - row_index
        fig.add_shape(
            type="rect",
            x0=-0.6,
            x1=cols - 0.4,
            y0=y - 0.45,
            y1=y + 0.45,
            line=dict(color="#d9e1e6", width=1),
            fillcolor="rgba(246,247,249,0.9)",
            layer="below",
        )
        fig.add_annotation(
            x=-0.75,
            y=y,
            text=f"<b>{line}</b>",
            showarrow=False,
            xanchor="right",
            font=dict(size=12, color="#1f4e5f"),
        )
    for band in ("green", "amber", "red"):
        sub = grid[grid["band"] == band]
        if sub.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=sub["x"],
                y=sub["y"],
                mode="markers+text",
                name=band.upper(),
                marker=dict(
                    symbol="square",
                    size=42,
                    color=BAND_COLOR[band],
                    line=dict(color=BAND_EDGE[band], width=1.5),
                ),
                text=sub["machine_id"].astype(str),
                textposition="middle center",
                textfont=dict(color="#ffffff", size=11, family="Source Sans 3, sans-serif"),
                hovertext=[_hover(record) for _, record in sub.iterrows()],
                hoverinfo="text",
            )
        )
    fig.update_xaxes(visible=False, range=[-2.4, cols + 0.2])
    fig.update_yaxes(visible=False, range=[-0.6, len(LINES) - 0.2])
    return fig


def main() -> None:
    con = db.connection()
    if con is None:
        header("Shop floor", "The warehouse has not been built yet.", "No plant clock")
        st.error("No warehouse found. Run `make pipeline` and `make train`.")
        return
    clock = db.plant_clock(con)
    header(
        "Shop floor",
        "Every machine at the plant clock, grouped by line. Color is the fleet band, same as the home page.",
        clock.strftime("%a %d %b %Y, %H:%M"),
    )
    sample_banner(db.is_sample_plant(con))

    fleet = db.fleet(con)
    if fleet.empty:
        st.warning("No scores yet. Run `make train`.")
        return

    positions = _layout(fleet)
    grid = positions.merge(fleet.drop(columns=["line"]), on="machine_id", how="left")

    reds = int((grid["band"] == "red").sum())
    ambers = int((grid["band"] == "amber").sum())
    greens = int((grid["band"] == "green").sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Machines on floor", len(grid))
    c2.metric("Red", reds)
    c3.metric("Amber", ambers)
    c4.metric("Green", greens)

    st.plotly_chart(
        chart_layout(_figure(grid), "Lines run left to right. Tile labels are machine IDs.", height=420),
        use_container_width=True,
    )
    st.caption(
        "Positions pack each line left to right in machine-ID order. This is an auto-layout, "
        "not a surveyed floor plan — the public datasets have no bay coordinates. Hover a tile "
        "for the full scorecard; the Machine page has the sensor traces."
    )

    worst = grid.sort_values(["queue_score", "p_fail_24h"], ascending=[False, False]).head(1)
    if not worst.empty:
        focus_default = int(worst.iloc[0]["machine_id"])
    else:
        focus_default = int(grid.iloc[0]["machine_id"])
    ids = grid["machine_id"].astype(int).tolist()
    index = ids.index(focus_default) if focus_default in ids else 0
    picked = st.selectbox(
        "Open a machine from the floor",
        ids,
        index=index,
        format_func=lambda mid: f"Machine {mid}",
    )
    if st.button("Open machine", type="primary"):
        st.session_state["machine_id"] = int(picked)
        st.switch_page("pages/2_Machine.py")


if __name__ == "__main__":
    main()
else:
    main()
