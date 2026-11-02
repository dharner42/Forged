"""Turn the morning list into dollars using ``cost_assumptions.py``.

Two ways to price the same backtest:

- ``savings_from_hit_rates`` multiplies the gap in average hits by the cost of
  one reference machine. The stored metrics file only has those averages, so
  this is the figure in ``results/`` until a training run replaces it.
- ``cost_of_selection`` and ``expected_random_list_cost`` price the actual
  machines. ``backtest`` calls them when the parts table is in hand, and
  ``make train`` writes that sum into the metrics file.
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd

from cost_assumptions import (
    DOWNTIME_USD_PER_HOUR_BY_IMPACT,
    EMERGENCY_LABOR_HOURS,
    EMERGENCY_LABOR_PREMIUM,
    EXPEDITE_MULTIPLIER,
    INSPECTION_LABOR_HOURS,
    LABOR_USD_PER_HOUR,
    LIST_SIZE,
    PART_COST_USD,
    PLANNED_DOWNTIME_HOURS,
    PLANNED_LABOR_HOURS,
    REFERENCE_COMPONENT,
    REFERENCE_IMPACT,
    REFERENCE_PARTS_SHORT,
    UNPLANNED_DOWNTIME_HOURS,
)
from models.priority import parts_factor

ASSUMPTIONS_FILE = "cost_assumptions.py"


def downtime_rate(impact: int) -> float:
    try:
        return float(DOWNTIME_USD_PER_HOUR_BY_IMPACT[int(impact)])
    except KeyError as exc:
        raise KeyError(f"production impact {impact} has no downtime rate") from exc


def part_cost(component: str, parts_short: bool) -> float:
    try:
        base = float(PART_COST_USD[str(component)])
    except KeyError as exc:
        raise KeyError(f"component {component} has no part cost") from exc
    if parts_short:
        return base * float(EXPEDITE_MULTIPLIER)
    return base


def inspection_cost() -> float:
    return float(INSPECTION_LABOR_HOURS) * float(LABOR_USD_PER_HOUR)


def planned_repair_cost(impact: int, component: str, parts_short: bool) -> float:
    return (
        float(PLANNED_DOWNTIME_HOURS) * downtime_rate(impact)
        + float(PLANNED_LABOR_HOURS) * float(LABOR_USD_PER_HOUR)
        + part_cost(component, parts_short)
    )


def unplanned_failure_cost(impact: int, component: str, parts_short: bool) -> float:
    return (
        float(UNPLANNED_DOWNTIME_HOURS) * downtime_rate(impact)
        + float(EMERGENCY_LABOR_HOURS) * float(LABOR_USD_PER_HOUR) * float(EMERGENCY_LABOR_PREMIUM)
        + part_cost(component, parts_short)
    )


def savings_per_extra_catch(impact: int, component: str, parts_short: bool) -> float:
    """Dollars saved by catching one more failure on a fixed-length list.

    The missed failure costs the unplanned amount, and the slot it did not
    occupy was spent inspecting a machine that did not fail. Catching it pays
    the planned repair instead of both of those.
    """
    return unplanned_failure_cost(impact, component, parts_short) + inspection_cost() - planned_repair_cost(
        impact, component, parts_short
    )


def _cents(value: float) -> float:
    return round(float(value), 2)


def _money(value: float) -> str:
    return f"${value:,.0f}"


def savings_from_hit_rates(backtest: dict) -> dict:
    """Price the published hit-rate gap on the reference machine."""
    per_catch = savings_per_extra_catch(REFERENCE_IMPACT, REFERENCE_COMPONENT, REFERENCE_PARTS_SHORT)
    mornings = int(backtest["mornings"])
    priority = float(backtest["priority_avg_hits"])
    oldest = float(backtest["oldest_avg_hits"])
    random_hits = float(backtest["random10_avg_hits"])
    gap_oldest = priority - oldest
    gap_random = priority - random_hits
    per_morning_oldest = gap_oldest * per_catch
    per_morning_random = gap_random * per_catch
    window_oldest = per_morning_oldest * mornings
    window_random = per_morning_random * mornings
    note = (
        f"Over {mornings} mornings, the rates in {ASSUMPTIONS_FILE} applied to one reference machine "
        f"(impact {REFERENCE_IMPACT}, {REFERENCE_COMPONENT}, part in stock) price the priority list at "
        f"{_money(window_oldest)} versus oldest-machine-first and {_money(window_random)} versus a random "
        f"{LIST_SIZE}. One extra catch on that machine is {_money(per_catch)}: the unplanned stop, plus the "
        f"inspection the list slot no longer wastes, minus the planned repair. "
        f"The stored backtest keeps average hits, not the machine ids, so this edition does not use each "
        f"machine's own impact. Impact, stock, and these rates are assumptions, not a supplier's invoices. "
        f"`make train` replaces this with the sum over the actual machines on each morning."
    )
    return {
        "method": "reference_machine",
        "reference_impact": REFERENCE_IMPACT,
        "reference_component": REFERENCE_COMPONENT,
        "reference_parts_short": REFERENCE_PARTS_SHORT,
        "usd_per_extra_catch": _cents(per_catch),
        "extra_catches_per_morning_vs_oldest": gap_oldest,
        "extra_catches_per_morning_vs_random": gap_random,
        "usd_per_morning_vs_oldest": _cents(per_morning_oldest),
        "usd_per_morning_vs_random": _cents(per_morning_random),
        "usd_window_vs_oldest": _cents(window_oldest),
        "usd_window_vs_random": _cents(window_random),
        "mornings": mornings,
        "list_size": LIST_SIZE,
        "assumptions_file": ASSUMPTIONS_FILE,
        "note": note,
    }


def _impact(machines: pd.DataFrame, machine_id: int) -> int:
    row = machines.loc[machines["machine_id"].astype(int).eq(int(machine_id))]
    if row.empty:
        raise KeyError(f"machine {machine_id} is not on the fleet")
    return int(row.iloc[0]["production_impact"])


def _failure_component(failed_window: pd.DataFrame, machine_id: int) -> str:
    rows = failed_window.loc[failed_window["machine_id"].astype(int).eq(int(machine_id))]
    if rows.empty:
        raise KeyError(f"machine {machine_id} has no failure in the window")
    if "ts" in rows.columns:
        rows = rows.sort_values("ts")
    return str(rows.iloc[0]["component"])


def _parts_short(parts: pd.DataFrame, component: str) -> bool:
    if parts is None or parts.empty:
        return True
    row = parts.loc[parts["component"].astype(str).eq(str(component))]
    if row.empty:
        return True
    return parts_factor(row.iloc[0]["on_hand"], row.iloc[0]["reorder_point"]) > 1.0


def _event_cost(machine_id: int, failed_window: pd.DataFrame, machines: pd.DataFrame, parts: pd.DataFrame, planned: bool) -> float:
    component = _failure_component(failed_window, machine_id)
    short = _parts_short(parts, component)
    impact = _impact(machines, machine_id)
    if planned:
        return planned_repair_cost(impact, component, short)
    return unplanned_failure_cost(impact, component, short)


def cost_of_selection(
    selected_ids: Iterable,
    failed_window: pd.DataFrame,
    machines: pd.DataFrame,
    parts: pd.DataFrame,
) -> float:
    """Cost of working ``selected_ids`` and missing every other failure in the window.

    A selected machine that fails is a planned repair. A selected machine that
    does not fail is an inspection. A failure that was not selected is unplanned.
    Stock is the seeded snapshot, not a reconstruction of that morning's shelf.
    """
    selected: list[int] = []
    seen: set[int] = set()
    for machine_id in selected_ids:
        mid = int(machine_id)
        if mid in seen:
            continue
        seen.add(mid)
        selected.append(mid)
    failed_ids = set(int(machine_id) for machine_id in failed_window["machine_id"].unique()) if len(failed_window) else set()
    total = 0.0
    for mid in selected:
        if mid in failed_ids:
            total += _event_cost(mid, failed_window, machines, parts, planned=True)
        else:
            total += inspection_cost()
    for mid in failed_ids - seen:
        total += _event_cost(mid, failed_window, machines, parts, planned=False)
    return total


def expected_random_list_cost(
    failed_window: pd.DataFrame,
    machines: pd.DataFrame,
    parts: pd.DataFrame,
    n_machines: int,
    list_size: int = LIST_SIZE,
) -> float:
    """Expected cost of a random list of ``list_size`` on this morning.

    Each machine is on the list with probability ``list_size / n_machines``,
    which is also how the backtest's random hit rate is defined.
    """
    if n_machines <= 0:
        return 0.0
    chance = min(1.0, float(list_size) / float(n_machines))
    failed_ids = set(int(machine_id) for machine_id in failed_window["machine_id"].unique()) if len(failed_window) else set()
    total = 0.0
    for machine_id in machines["machine_id"].astype(int):
        if int(machine_id) in failed_ids:
            planned = _event_cost(int(machine_id), failed_window, machines, parts, planned=True)
            unplanned = _event_cost(int(machine_id), failed_window, machines, parts, planned=False)
            total += chance * planned + (1.0 - chance) * unplanned
        else:
            total += chance * inspection_cost()
    return total


def summarize_machine_costs(priority_costs: list[float], oldest_costs: list[float], random_costs: list[float]) -> dict:
    mornings = len(priority_costs)
    if mornings == 0 or len(oldest_costs) != mornings or len(random_costs) != mornings:
        raise ValueError("strategy cost lists must be non-empty and the same length")
    priority_total = float(sum(priority_costs))
    oldest_total = float(sum(oldest_costs))
    random_total = float(sum(random_costs))
    window_oldest = oldest_total - priority_total
    window_random = random_total - priority_total
    note = (
        f"Over {mornings} mornings, the rates in {ASSUMPTIONS_FILE} were applied to the actual machines on each "
        f"list. The priority list costs {_money(window_oldest)} less than oldest-machine-first and "
        f"{_money(window_random)} less than the expected cost of a random {LIST_SIZE}. "
        f"A caught failure is a planned repair. A missed failure is an unplanned stop. A list slot with no "
        f"failure in the window is an inspection. Stock is the seeded snapshot, not that morning's shelf. "
        f"Impact and these rates are assumptions, not a supplier's invoices."
    )
    return {
        "method": "machine_level",
        "usd_per_morning_vs_oldest": _cents(window_oldest / mornings),
        "usd_per_morning_vs_random": _cents(window_random / mornings),
        "usd_window_vs_oldest": _cents(window_oldest),
        "usd_window_vs_random": _cents(window_random),
        "priority_cost_window": _cents(priority_total),
        "oldest_cost_window": _cents(oldest_total),
        "random_cost_window": _cents(random_total),
        "mornings": mornings,
        "list_size": LIST_SIZE,
        "assumptions_file": ASSUMPTIONS_FILE,
        "note": note,
    }


def savings_table(savings: dict) -> str:
    """A markdown table plus the note. Shared by ``results/results.md`` and the README source."""
    if savings.get("method") == "reference_machine":
        header = (
            "| Comparison | Extra catches per morning | USD per morning | USD over the window |\n"
            "| --- | ---: | ---: | ---: |\n"
        )
        body = (
            f"| Versus oldest-machine-first | {savings['extra_catches_per_morning_vs_oldest']:.2f} | "
            f"{_money(savings['usd_per_morning_vs_oldest'])} | {_money(savings['usd_window_vs_oldest'])} |\n"
            f"| Versus a random {savings['list_size']} | {savings['extra_catches_per_morning_vs_random']:.2f} | "
            f"{_money(savings['usd_per_morning_vs_random'])} | {_money(savings['usd_window_vs_random'])} |"
        )
    else:
        header = "| Comparison | USD per morning | USD over the window |\n| --- | ---: | ---: |\n"
        body = (
            f"| Versus oldest-machine-first | {_money(savings['usd_per_morning_vs_oldest'])} | "
            f"{_money(savings['usd_window_vs_oldest'])} |\n"
            f"| Versus a random {savings['list_size']} | {_money(savings['usd_per_morning_vs_random'])} | "
            f"{_money(savings['usd_window_vs_random'])} |"
        )
    return header + body


def savings_section(savings: dict) -> str:
    intro = (
        "Assumptions live in `cost_assumptions.py` and nowhere else. Downtime is priced by production impact. "
        "A missed failure costs unplanned downtime, emergency labor, and the part. A failure caught on the list "
        "costs a shorter planned stop, straight-time labor, and the same part, with the expedite multiplier when "
        "that component is out of stock or below its reorder point. A list slot spent on a machine that does not "
        "fail costs a short inspection. The backtest list length is fixed, so the strategies are compared on the "
        "same number of jobs."
    )
    if savings.get("method") == "reference_machine":
        which = (
            f"This edition prices the published hit-rate gap on one reference machine: impact "
            f"{savings['reference_impact']}, {savings['reference_component']}, part in stock. "
            f"One extra catch on that machine is {_money(savings['usd_per_extra_catch'])}."
        )
    else:
        which = (
            "This edition sums those rates over the machines actually on each morning's list. "
            "The random column is an expectation, matching the random hit rate, not one shuffled draw."
        )
    return f"{intro}\n\n{which}\n\n{savings_table(savings)}\n\n{savings['note']}"
