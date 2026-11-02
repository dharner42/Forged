"""Turn the ranked list into the jobs this shift can actually start.

The roster, the shifts, and the stock are simulated. This does not change the
priority score, and the September–December backtest does not use it.
Each person on duty can take one machine.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ontology.model import shift_id_for_timestamp
from pipeline.seed_ops import COMPONENT_SKILL


def shift_name(as_of) -> str:
    """Day 06:00–14:00, swing 14:00–22:00, night otherwise. Hours live on the Shift object."""
    return shift_id_for_timestamp(as_of)


@dataclass
class ShiftPlan:
    shift: str
    on_duty: pd.DataFrame
    work_now: pd.DataFrame
    blocked: pd.DataFrame
    deferred: pd.DataFrame

    def note_for(self, machine_id: int) -> str | None:
        for frame in (self.work_now, self.blocked, self.deferred):
            hit = frame[frame["machine_id"].astype(int).eq(int(machine_id))]
            if not hit.empty:
                return str(hit.iloc[0]["note"])
        return None


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def plan_shift(fleet: pd.DataFrame, technicians: pd.DataFrame, as_of, slots_per_tech: int = 1) -> ShiftPlan:
    shift = shift_name(as_of)
    work_cols = ["machine_id", "predicted_component", "queue_score", "technician_name", "note"]
    hold_cols = ["machine_id", "predicted_component", "queue_score", "note"]
    if fleet.empty or technicians.empty:
        return ShiftPlan(shift, technicians.iloc[0:0], _empty(work_cols), _empty(hold_cols), _empty(hold_cols))

    on_duty = technicians[technicians["shift"].eq(shift)].sort_values("technician_id").copy()
    slots = {int(tech_id): int(slots_per_tech) for tech_id in on_duty["technician_id"]}
    names = {int(row.technician_id): str(row.name) for row in on_duty.itertuples(index=False)}

    if "work_order_id" in fleet.columns and "technician_id" in fleet.columns:
        open_rows = fleet[fleet["work_order_id"].notna()]
        for row in open_rows.itertuples(index=False):
            tech_id = getattr(row, "technician_id", None)
            if pd.notna(tech_id) and int(tech_id) in slots and slots[int(tech_id)] > 0:
                slots[int(tech_id)] -= 1

    risky = fleet[fleet["band"].isin(["red", "amber"])].copy()
    if "work_order_id" in risky.columns:
        risky = risky[risky["work_order_id"].isna()]
    risky = risky.sort_values(["queue_score", "machine_id"], ascending=[False, True])

    work_now: list[dict] = []
    blocked: list[dict] = []
    deferred: list[dict] = []
    for row in risky.itertuples(index=False):
        component = str(row.predicted_component)
        skill = COMPONENT_SKILL.get(component, "general")
        on_hand = getattr(row, "on_hand", None)
        part_ok = pd.notna(on_hand) and float(on_hand) > 0
        lead = getattr(row, "lead_time_days", None)
        skilled = on_duty[on_duty["skill"].eq(skill)]
        crew_ok = not skilled.empty
        base = {
            "machine_id": int(row.machine_id),
            "predicted_component": component,
            "queue_score": float(row.queue_score),
        }
        if not part_ok or not crew_ok:
            bits = []
            if not part_ok:
                wait = f", {int(lead)}-day lead" if pd.notna(lead) else ""
                bits.append(f"out of stock{wait}")
            if not crew_ok:
                bits.append(f"no {skill} technician on the {shift} shift")
            blocked.append({**base, "note": f"{component}: " + "; ".join(bits) + ". SIMULATED."})
            continue
        free = skilled[skilled["technician_id"].map(lambda tech_id: slots.get(int(tech_id), 0) > 0)]
        if free.empty:
            who = ", ".join(names[int(tech_id)] for tech_id in skilled["technician_id"])
            deferred.append({**base, "note": f"{who} can do this skill and is already booked this shift."})
            continue
        chosen = free.sort_values("technician_id").iloc[0]
        tech_id = int(chosen["technician_id"])
        slots[tech_id] -= 1
        reorder = getattr(row, "reorder_point", None)
        shelf = ""
        if pd.notna(reorder) and float(on_hand) <= float(reorder):
            shelf = " Last part on the shelf."
        work_now.append({**base, "technician_name": names[tech_id], "note": f"{names[tech_id]}, {skill}.{shelf} SIMULATED."})

    return ShiftPlan(
        shift,
        on_duty,
        pd.DataFrame(work_now, columns=work_cols),
        pd.DataFrame(blocked, columns=hold_cols),
        pd.DataFrame(deferred, columns=hold_cols),
    )
