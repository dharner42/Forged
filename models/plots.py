"""Small matplotlib helpers. Charts are written for the README, not only the screen."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config import PLOTS_DIR

NAVY = "#1f4e5f"
AMBER = "#b86e00"
RED = "#9f2d2d"
INK = "#1c2430"


def apply_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#c5d0d6",
            "axes.labelcolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "text.color": INK,
            "axes.titlesize": 12,
            "axes.titleweight": "semibold",
        }
    )


def save(fig, name: str) -> Path:
    apply_style()
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PLOTS_DIR / name
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path
