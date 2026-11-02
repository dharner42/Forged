"""The cost model: downtime, parts, labor, and the list comparison."""

from pathlib import Path

import pandas as pd
import pytest

from models.costs import (
    cost_of_selection,
    expected_random_list_cost,
    inspection_cost,
    planned_repair_cost,
    savings_from_hit_rates,
    savings_per_extra_catch,
    summarize_machine_costs,
    unplanned_failure_cost,
)
from models.priority import parts_factor, priority_score


def test_parts_factor_is_one_point_five_when_out_of_stock():
    # priority = P(fail) x impact x parts factor. Out of stock, or below the
    # reorder point, uses 1.5. At the reorder point the part is still in stock.
    assert parts_factor(0, 2) == 1.5
    assert parts_factor(1, 2) == 1.5
    assert parts_factor(2, 2) == 1.0
    assert priority_score(0.40, 5, on_hand=0, reorder_point=2) == pytest.approx(3.0)
    assert priority_score(0.40, 5, on_hand=4, reorder_point=2) == pytest.approx(2.0)
    # The demo morning: probability 1, impact 5, comp4 at zero -> 7.50.
    assert priority_score(1.0, 5, on_hand=0, reorder_point=2) == pytest.approx(7.5)


def test_reference_machine_arithmetic_is_visible():
    # Impact 3, comp2, in stock. Numbers are the rates in cost_assumptions.py.
    # Unplanned: 6h * $1000 + 4h * $75 * 1.5 + $420 = $6,870
    # Planned:   1.5h * $1000 + 2h * $75 + $420 = $2,070
    # Inspection: 0.5h * $75 = $37.50
    # Extra catch: 6870 + 37.50 - 2070 = 4837.50
    assert unplanned_failure_cost(3, "comp2", parts_short=False) == pytest.approx(6870.0)
    assert planned_repair_cost(3, "comp2", parts_short=False) == pytest.approx(2070.0)
    assert inspection_cost() == pytest.approx(37.5)
    assert savings_per_extra_catch(3, "comp2", parts_short=False) == pytest.approx(4837.5)
    # Out of stock multiplies the part, not the downtime.
    short = unplanned_failure_cost(3, "comp2", parts_short=True)
    assert short - 6870.0 == pytest.approx(420.0 * 0.35)


def test_published_hit_rates_price_the_priority_list():
    published = {
        "mornings": 115,
        "priority_avg_hits": 2.4869565217391303,
        "oldest_avg_hits": 1.5043478260869565,
        "random10_avg_hits": 1.2547826086956522,
    }
    savings = savings_from_hit_rates(published)
    assert savings["method"] == "reference_machine"
    assert savings["usd_per_extra_catch"] == pytest.approx(4837.5)
    assert savings["extra_catches_per_morning_vs_oldest"] == pytest.approx(2.4869565217391303 - 1.5043478260869565)
    assert savings["usd_window_vs_oldest"] == pytest.approx(546637.5)
    assert savings["usd_window_vs_random"] == pytest.approx(685473.75)
    assert savings["usd_window_vs_oldest"] > 0
    assert savings["usd_window_vs_random"] > savings["usd_window_vs_oldest"]
    assert "cost_assumptions.py" in savings["note"]
    assert "not a supplier's invoices" in savings["note"]
    written = Path("results/results.md").read_text()
    assert "$546,638" in written
    assert "$685,474" in written
    assert "$4,838" in written


def test_machine_level_savings_follow_who_is_caught():
    machines = pd.DataFrame(
        {
            "machine_id": [1, 2, 3, 4],
            "production_impact": [5, 1, 1, 1],
        }
    )
    parts = pd.DataFrame(
        {
            "component": ["comp1", "comp2"],
            "on_hand": [8, 0],
            "reorder_point": [2, 2],
        }
    )
    # Machine 1 (impact 5, comp1 in stock) fails. Machine 2 (comp2, out of stock) fails.
    failed = pd.DataFrame(
        {
            "machine_id": [1, 2],
            "ts": [pd.Timestamp("2015-11-18"), pd.Timestamp("2015-11-19")],
            "component": ["comp1", "comp2"],
        }
    )
    # Priority catches the expensive failure. Oldest-first catches the cheap one.
    priority = cost_of_selection([1, 3], failed, machines, parts)
    oldest = cost_of_selection([2, 4], failed, machines, parts)
    assert priority < oldest
    # Working nobody means both failures are unplanned and there is no inspection.
    missed = cost_of_selection([], failed, machines, parts)
    assert missed == pytest.approx(
        unplanned_failure_cost(5, "comp1", False) + unplanned_failure_cost(1, "comp2", True)
    )
    # A random list of 2 out of 4 puts each machine on the list with probability 0.5.
    random_cost = expected_random_list_cost(failed, machines, parts, n_machines=4, list_size=2)
    caught_1 = 0.5 * planned_repair_cost(5, "comp1", False) + 0.5 * unplanned_failure_cost(5, "comp1", False)
    caught_2 = 0.5 * planned_repair_cost(1, "comp2", True) + 0.5 * unplanned_failure_cost(1, "comp2", True)
    inspections = 0.5 * inspection_cost() * 2
    assert random_cost == pytest.approx(caught_1 + caught_2 + inspections)

    summary = summarize_machine_costs([priority], [oldest], [random_cost])
    assert summary["method"] == "machine_level"
    assert summary["usd_window_vs_oldest"] == pytest.approx(oldest - priority)
    assert summary["mornings"] == 1
