"""Planning rates for the savings estimate.

Every dollar figure in ``results/`` and on the dashboard is computed from this
file. Nothing else in the repo sets a price.

These are not invoices and not measurements from a plant. A maintenance lead
would replace them with the shop's own rates. Impact, stock, and part costs are
simulated, same as the roster.

The comparison assumes the crew works a fixed list of ``LIST_SIZE`` machines,
which is the list the backtest already uses. Catching one more failure spends
a slot that would otherwise have been a short inspection of a machine that did
not fail, and it pays a planned repair instead of an unplanned stop.
"""

from __future__ import annotations

# Unplanned-downtime rate, USD per hour, by simulated production impact (1–5).
# Impact 1 is a support machine. Impact 5 is a constraint or a certified
# process where a stop holds a defense order.
DOWNTIME_USD_PER_HOUR_BY_IMPACT: dict[int, float] = {
    1: 250.0,
    2: 500.0,
    3: 1000.0,
    4: 2000.0,
    5: 4000.0,
}

# Hours the machine is down if the failure is not on the morning list.
UNPLANNED_DOWNTIME_HOURS: float = 6.0
# Hours the machine is down if the crew works it from the list before it fails.
PLANNED_DOWNTIME_HOURS: float = 1.5

# Loaded maintenance-technician rate. Emergency labor adds a call-in premium.
LABOR_USD_PER_HOUR: float = 75.0
PLANNED_LABOR_HOURS: float = 2.0
EMERGENCY_LABOR_HOURS: float = 4.0
EMERGENCY_LABOR_PREMIUM: float = 1.5
# A list slot spent on a machine that does not fail in the window.
INSPECTION_LABOR_HOURS: float = 0.5

# Standard part cost, USD. One SKU per component, same stand-in as the stock.
PART_COST_USD: dict[str, float] = {
    "comp1": 180.0,
    "comp2": 420.0,
    "comp3": 260.0,
    "comp4": 510.0,
}
# Applied when that component is out of stock or below its reorder point.
EXPEDITE_MULTIPLIER: float = 1.35

# Same length as the morning list in the backtest.
LIST_SIZE: int = 10

# Used when a report only has average hit counts, not the machine ids.
# Impact 3 is the middle of the 1–5 scale. comp2 is the median part cost.
# The part is in stock, so the expedite multiplier is not applied.
REFERENCE_IMPACT: int = 3
REFERENCE_COMPONENT: str = "comp2"
REFERENCE_PARTS_SHORT: bool = False
