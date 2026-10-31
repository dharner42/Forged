"""Draw the architecture and schema figures committed under docs/."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def _box(ax, x, y, w, h, title, detail, face):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        linewidth=1,
        edgecolor="#16323f",
        facecolor=face,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h * 0.62, title, ha="center", va="center", fontsize=11, fontweight="semibold", color="#16323f")
    ax.text(x + w / 2, y + h * 0.32, detail, ha="center", va="center", fontsize=8.5, color="#52616b")


def architecture() -> None:
    fig, ax = plt.subplots(figsize=(11.2, 3.4))
    ax.set_xlim(0, 11.2)
    ax.set_ylim(0, 3.4)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    boxes = [
        (0.25, 1.15, "Raw files", "Azure, AI4I, C-MAPSS"),
        (2.35, 1.15, "Pipeline", "load, validate, seed"),
        (4.45, 1.15, "DuckDB", "plant ontology"),
        (6.55, 1.15, "Models", "24h risk, RUL, AI4I"),
        (8.65, 1.15, "Priority", "risk × impact × parts"),
    ]
    for x, y, title, detail in boxes:
        _box(ax, x, y, 1.85, 1.15, title, detail, "#f4f7f8")
    _box(ax, 4.45, 0.15, 1.85, 0.8, "Streamlit", "queue and repairs", "#e7eef1")
    for x in (2.1, 4.2, 6.3, 8.4):
        ax.annotate("", xy=(x + 0.25, 1.72), xytext=(x, 1.72), arrowprops=dict(arrowstyle="->", color="#16323f"))
    ax.annotate("", xy=(5.35, 1.15), xytext=(5.35, 0.95), arrowprops=dict(arrowstyle="->", color="#16323f"))
    ax.annotate(
        "",
        xy=(6.3, 0.55),
        xytext=(5.4, 0.55),
        arrowprops=dict(arrowstyle="->", color="#16323f", linestyle="dashed"),
    )
    ax.text(5.85, 0.28, "work orders", fontsize=8, color="#52616b")
    fig.tight_layout()
    fig.savefig(DOCS / "architecture.png", dpi=140)
    plt.close(fig)


def schema() -> None:
    fig, ax = plt.subplots(figsize=(11.2, 6.2))
    ax.set_xlim(0, 11.2)
    ax.set_ylim(0, 6.2)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    tables = [
        (0.3, 4.5, "machines", "id, model, age\nline*, impact*"),
        (3.0, 4.5, "sensor_readings", "machine, ts\nvolt, rotate\npressure, vibration"),
        (5.7, 4.5, "faults", "machine, ts\nerror_code"),
        (8.4, 4.5, "failures", "machine, ts\ncomponent"),
        (0.3, 2.6, "maintenance_events", "machine, ts\ncomponent, type\ntechnician"),
        (3.0, 2.6, "work_orders", "machine, component\nstatus, priority\nopened, closed"),
        (5.7, 2.6, "parts*", "component\non hand, reorder\nlead time"),
        (8.4, 2.6, "technicians*", "name, skill, shift"),
        (3.0, 0.5, "current_scores", "P(fail 24h)\npriority, queue\nreason, band"),
        (5.7, 0.5, "predictions", "morning scores\nSep–Dec test"),
    ]
    for x, y, title, detail in tables:
        _box(ax, x, y, 2.4, 1.5, title, detail, "#f7f1e8" if title.endswith("*") or "*" in title else "#f4f7f8")
    ax.text(0.3, 0.15, "* Simulated. Not in the public files. Parts and technicians are entirely simulated.", fontsize=9, color="#52616b")
    fig.tight_layout()
    fig.savefig(DOCS / "schema.png", dpi=140)
    plt.close(fig)


if __name__ == "__main__":
    DOCS.mkdir(parents=True, exist_ok=True)
    architecture()
    schema()
    print(f"Wrote {DOCS / 'architecture.png'} and {DOCS / 'schema.png'}")
