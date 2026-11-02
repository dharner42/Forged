"""The object model matches the document and a built warehouse."""

from pathlib import Path

from ontology.model import (
    COMPONENTS,
    LINKS,
    OBJECTS,
    SHIFTS,
    assert_warehouse_matches_ontology,
    shift_id_for_hour,
)
from pipeline.run import build_database
from pipeline.warehouse import connect
from tests.test_pipeline import _write_azure


def test_shift_hours_match_the_shop_rule():
    assert shift_id_for_hour(6) == "day"
    assert shift_id_for_hour(13) == "day"
    assert shift_id_for_hour(14) == "swing"
    assert shift_id_for_hour(21) == "swing"
    assert shift_id_for_hour(22) == "night"
    assert shift_id_for_hour(5) == "night"
    assert [shift.shift_id for shift in SHIFTS] == ["day", "swing", "night"]


def test_components_are_the_feature_ids():
    from models.features import COMPONENTS as feature_components

    assert list(COMPONENTS) == feature_components


def test_the_document_names_every_object_and_link():
    text = Path("docs/ONTOLOGY.md").read_text()
    for obj in OBJECTS:
        assert obj.name in text
        assert obj.table in text
    for link in LINKS:
        assert link.name in text


def test_a_built_warehouse_satisfies_the_ontology(tmp_path):
    raw = tmp_path / "raw"
    _write_azure(raw)
    db_path = tmp_path / "plant.duckdb"
    build_database(raw, db_path, strict_counts=False, load_benchmarks=False)
    con = connect(db_path)
    try:
        counts = assert_warehouse_matches_ontology(con)
    finally:
        con.close()
    assert counts["Machine"] == 2
    assert counts["Shift"] == 3
    assert counts["Technician"] == 6
    assert counts["Inventory"] == 4
    assert counts["WorkOrder"] == 0
    assert counts["Failure"] == 1
