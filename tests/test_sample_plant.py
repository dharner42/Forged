"""The bundled sample opens without the public datasets and keeps the formula."""

from pipeline.sample_plant import (
    build_sample_plant,
    is_sample_note,
    move_sample_clock,
    suppress_after_repair,
)
from pipeline.warehouse import connect, read_clock


def test_sample_plant_ranks_machine_4_at_7_50(tmp_path):
    path = build_sample_plant(tmp_path / "sample.duckdb")
    con = connect(path)
    try:
        note = con.execute("SELECT note FROM plant_clock WHERE id = 1").fetchone()[0]
        assert is_sample_note(note)
        row = con.execute(
            """
            SELECT p_fail_24h, production_impact, parts_factor, priority_score, queue_score, band
            FROM fix_first WHERE machine_id = 4
            """
        ).fetchone()
        assert row[0] == 1.0
        assert row[1] == 5
        assert row[2] == 1.5
        assert row[3] == 7.5
        assert row[4] == 7.5
        assert row[5] == "red"
        top = con.execute("SELECT machine_id FROM fix_first ORDER BY rank LIMIT 1").fetchone()[0]
        assert top == 4
        assert con.execute("SELECT count(*) FROM machines").fetchone()[0] == 12
        assert con.execute("SELECT count(*) FROM sensor_readings").fetchone()[0] > 100
    finally:
        con.close()


def test_sample_repair_applies_the_shop_rule_without_the_model(tmp_path):
    path = build_sample_plant(tmp_path / "sample.duckdb")
    con = connect(path)
    try:
        before = con.execute("SELECT priority_score FROM current_scores WHERE machine_id = 4").fetchone()[0]
        suppress_after_repair(con, 4)
        after = con.execute(
            "SELECT queue_score, serviced_within_24h, top_reason FROM current_scores WHERE machine_id = 4"
        ).fetchone()
        assert after[0] == before * 0.15
        assert bool(after[1])
        assert str(after[2]).startswith("Serviced in the last 24 hours")
    finally:
        con.close()


def test_sample_clock_move_keeps_the_sample_flag(tmp_path):
    path = build_sample_plant(tmp_path / "sample.duckdb")
    con = connect(path)
    try:
        move_sample_clock(con, "2015-11-20 15:00")
        assert is_sample_note(con.execute("SELECT note FROM plant_clock WHERE id = 1").fetchone()[0])
        assert str(read_clock(con)).startswith("2015-11-20 15:00")
    finally:
        con.close()
