"""Shared layout for the Forged Machine Monitoring dashboard."""

import pandas as pd
import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap');
html, body, [class*="css"] { font-family: "Source Sans 3", "Segoe UI", sans-serif; }
.block-container { padding-top: 1.05rem; padding-bottom: 2.5rem; max-width: 1180px; }
.forge-top { display: flex; justify-content: space-between; gap: 18px; align-items: flex-end;
  border-bottom: 2px solid #16323f; padding-bottom: 10px; margin-bottom: 12px; }
.forge-mark { font-weight: 700; letter-spacing: 0.08em; font-size: 0.74rem; color: #1f4e5f; margin: 0; }
h1.forge-title { font-size: 1.65rem; line-height: 1.1; margin: 0; color: #16323f; font-weight: 700; }
p.forge-sub { margin: 3px 0 0 0; color: #52616b; }
.forge-clock { text-align: right; color: #16323f; }
.forge-clock b { display: block; font-size: 1.02rem; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.75rem;
  font-weight: 700; letter-spacing: 0.03em; }
.pill.red { background: #f8d6d4; color: #8c1d18; }
.pill.amber { background: #fdecc8; color: #8a5a00; }
.pill.green { background: #d9f2e5; color: #146c43; }
.pill.sim { background: #efe7fb; color: #5b3d86; }
.note { color: #52616b; font-size: 0.92rem; }
div[data-testid="stMetric"] { background: #fff; border: 1px solid #d9e1e6; border-radius: 10px; padding: 8px 12px; }
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str, clock_label: str) -> None:
    st.markdown(
        f"""
        <div class="forge-top">
          <div>
            <p class="forge-mark">FORGED MACHINE MONITORING</p>
            <h1 class="forge-title">{title}</h1>
            <p class="forge-sub">{subtitle}</p>
          </div>
          <div class="forge-clock">
            <span class="pill sim">SIMULATED OPS DATA</span>
            <b>{clock_label}</b>
            <span class="note">Plant clock, not your laptop clock</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def sample_banner(is_sample: bool) -> None:
    if not is_sample:
        return
    st.info(
        "Bundled sample plant: 12 machines and authored scores, so this app opens without downloading "
        "Azure, NASA, or AI4I. The RMSE, the 2.49 backtest, and the dollar figures are from results/ "
        "on the full files, not from these 12 machines. Machine 4 is the worked example "
        "(probability 1, impact 5, comp4 out of stock, priority 7.50)."
    )


def band_html(band: str) -> str:
    return f'<span class="pill {band}">{band.upper()}</span>'


def render_shift_plan(plan) -> None:
    """Who can start a job on this shift. Roster and stock are simulated."""
    if plan.on_duty.empty:
        duty = "no one"
    else:
        duty = ", ".join(f"{row.name} ({row.skill})" for row in plan.on_duty.itertuples(index=False))
    st.markdown(f"**On duty, {plan.shift} shift (SIMULATED):** {duty}")
    st.caption(
        "Each person on duty can take one machine. A job waits when the part is at zero or nobody with that skill is here. "
        "This does not change the priority score."
    )
    left, right = st.columns(2)
    with left:
        st.markdown("**Start this shift**")
        if plan.work_now.empty:
            st.info("Nothing in the red or amber band can be started with this crew and this stock.")
        else:
            show = plan.work_now.rename(
                columns={
                    "machine_id": "Machine",
                    "predicted_component": "Component",
                    "queue_score": "Queue",
                    "technician_name": "Who (SIMULATED)",
                    "note": "Note",
                }
            )
            show["Queue"] = show["Queue"].map(lambda value: f"{value:.2f}")
            st.dataframe(show, use_container_width=True, hide_index=True)
    with right:
        st.markdown("**Do not start**")
        held = pd.concat([plan.blocked, plan.deferred], ignore_index=True)
        if held.empty:
            st.success("Every red and amber machine can be staffed and has a part.")
        else:
            show = held.rename(
                columns={
                    "machine_id": "Machine",
                    "predicted_component": "Component",
                    "queue_score": "Queue",
                    "note": "Why",
                }
            )
            show["Queue"] = show["Queue"].map(lambda value: f"{value:.2f}")
            st.dataframe(show, use_container_width=True, hide_index=True)


def chart_layout(fig, title: str, height: int = 320):
    fig.update_layout(
        title=dict(text=title, font=dict(size=15), x=0, xanchor="left"),
        margin=dict(l=8, r=8, t=48, b=56),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Source Sans 3, sans-serif", color="#1c2430", size=13),
        legend=dict(orientation="h", yanchor="top", y=-0.22, x=0),
        height=height,
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#e6ebef")
    return fig
