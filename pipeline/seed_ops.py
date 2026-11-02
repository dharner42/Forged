"""SIMULATED parts, technicians, lines, and production impact.

Nothing in this module comes from the public datasets. The roster and the stock
levels are fixed so a demo is explainable. Production impact is the only random
draw, and it uses seed 42.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ontology.model import COMPONENT_SKILL, SHIFTS

LINES = ("Machining", "Assembly", "Test", "Finish")

# One stocked part per Azure component. comp2 is below its reorder point and
# comp4 is out of stock, so the parts factor is visible on the queue.
PARTS = (
    {"part_id": 1, "component": "comp1", "on_hand": 8, "reorder_point": 3, "lead_time_days": 5},
    {"part_id": 2, "component": "comp2", "on_hand": 1, "reorder_point": 4, "lead_time_days": 14},
    {"part_id": 3, "component": "comp3", "on_hand": 5, "reorder_point": 2, "lead_time_days": 7},
    {"part_id": 4, "component": "comp4", "on_hand": 0, "reorder_point": 2, "lead_time_days": 21},
)

# Names are fictional. The skill map is also simulated: the dataset never says
# what comp1–comp4 physically are.
TECHNICIANS = (
    {"technician_id": 1, "name": "A. Rivera", "skill": "mechanical", "shift": "day"},
    {"technician_id": 2, "name": "B. Okonkwo", "skill": "mechanical", "shift": "swing"},
    {"technician_id": 3, "name": "C. Nguyen", "skill": "electrical", "shift": "day"},
    {"technician_id": 4, "name": "D. Petrov", "skill": "electrical", "shift": "night"},
    {"technician_id": 5, "name": "E. Shah", "skill": "hydraulics", "shift": "day"},
    {"technician_id": 6, "name": "F. Alvarez", "skill": "general", "shift": "swing"},
)


def shifts_frame() -> pd.DataFrame:
    """One row per Shift object. Hours come from the ontology, not a second copy."""
    return pd.DataFrame(
        [
            {
                "shift_id": shift.shift_id,
                "name": shift.name,
                "start_hour": shift.start_hour,
                "end_hour": shift.end_hour,
                "simulated": True,
            }
            for shift in SHIFTS
        ]
    )


def assign_machine_ops(machines: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    out = machines.sort_values("machine_id").copy()
    rng = np.random.default_rng(seed)
    out["production_impact"] = rng.integers(1, 6, size=len(out))
    out["line"] = [(LINES[(int(mid) - 1) % len(LINES)]) for mid in out["machine_id"]]
    return out


def parts_frame() -> pd.DataFrame:
    frame = pd.DataFrame(PARTS)
    frame["simulated"] = True
    return frame


def technicians_frame() -> pd.DataFrame:
    frame = pd.DataFrame(TECHNICIANS)
    frame["simulated"] = True
    return frame


def pick_technician(techs: pd.DataFrame, open_counts: dict[int, int], component: str) -> int:
    """Prefer the simulated skill for this component, then the lightest workload."""
    skill = COMPONENT_SKILL.get(component, "general")
    pool = techs[techs["skill"] == skill]
    if pool.empty:
        pool = techs[techs["skill"] == "general"]
    if pool.empty:
        pool = techs
    ranked = pool.copy()
    ranked["open_n"] = ranked["technician_id"].map(lambda i: int(open_counts.get(int(i), 0)))
    ranked = ranked.sort_values(["open_n", "technician_id"])
    return int(ranked.iloc[0]["technician_id"])
