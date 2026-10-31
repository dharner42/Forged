"""A tiny raw folder rebuilds a warehouse with stable simulated impact."""

from pathlib import Path

import pandas as pd

from pipeline.run import build_database


def _write_azure(folder: Path) -> None:
    azure = folder / "azure"
    azure.mkdir(parents=True)
    start = pd.Timestamp("2015-01-01 06:00:00")
    hours = pd.date_range(start, periods=8, freq="h")
    rows = []
    for machine_id in (1, 2):
        for ts in hours:
            rows.append(
                {
                    "datetime": ts,
                    "machineID": machine_id,
                    "volt": 170,
                    "rotate": 450,
                    "pressure": 100,
                    "vibration": 40,
                }
            )
    pd.DataFrame(rows).to_csv(azure / "PdM_telemetry.csv", index=False)
    pd.DataFrame(
        {"datetime": [hours[3]], "machineID": [1], "errorID": ["error1"]}
    ).to_csv(azure / "PdM_errors.csv", index=False)
    pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2014-06-01 06:00:00"), pd.Timestamp("2014-06-01 06:00:00")],
            "machineID": [1, 2],
            "comp": ["comp1", "comp2"],
        }
    ).to_csv(azure / "PdM_maint.csv", index=False)
    pd.DataFrame(
        {"datetime": [hours[7]], "machineID": [1], "failure": ["comp4"]}
    ).to_csv(azure / "PdM_failures.csv", index=False)
    pd.DataFrame(
        {"machineID": [1, 2], "model": ["model1", "model4"], "age": [3, 15]}
    ).to_csv(azure / "PdM_machines.csv", index=False)


def test_rebuild_is_reproducible_and_labels_simulated_ops(tmp_path):
    raw = tmp_path / "raw"
    _write_azure(raw)
    first = tmp_path / "one.duckdb"
    second = tmp_path / "two.duckdb"
    counts = build_database(raw, first, strict_counts=False, load_benchmarks=False)
    build_database(raw, second, strict_counts=False, load_benchmarks=False)
    assert counts["machines"] == 2
    assert counts["sensor_readings"] == 16
    assert counts["faults"] == 1
    assert counts["failures"] == 1
    assert counts["parts"] == 4
    assert counts["technicians"] == 6

    import duckdb

    one = duckdb.connect(str(first))
    two = duckdb.connect(str(second))
    impact_one = one.execute("SELECT machine_id, line, production_impact FROM machines ORDER BY 1").fetchdf()
    impact_two = two.execute("SELECT machine_id, line, production_impact FROM machines ORDER BY 1").fetchdf()
    parts = one.execute("SELECT component, on_hand, simulated FROM parts ORDER BY part_id").fetchdf()
    techs = one.execute("SELECT count(*) FROM technicians WHERE simulated").fetchone()[0]
    scheduled = one.execute("SELECT count(*) FROM maintenance_events WHERE type = 'scheduled'").fetchone()[0]
    one.close()
    two.close()
    pd.testing.assert_frame_equal(impact_one, impact_two)
    assert set(impact_one["production_impact"]) <= {1, 2, 3, 4, 5}
    assert bool(parts["simulated"].all())
    assert int(parts.loc[parts.component.eq("comp4"), "on_hand"].iloc[0]) == 0
    assert techs == 6
    assert scheduled == 2
