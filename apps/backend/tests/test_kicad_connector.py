"""Unit tests for the KiCad schematic parser, using the real Elegoo V4
schematic shipped in demo-assets as a fixture."""

import os

from src.connectors.kicad import KiCadConnector
from models import EntityType

FIXTURE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "demo-assets", "elegoo_kicad",
))


def test_ingest_extracts_components_and_nets():
    result = KiCadConnector(FIXTURE, "test-project").ingest()
    assert result["entities"], "expected entities from the schematic"
    assert result["relations"], "expected net connections between components"


def test_ingest_finds_known_motor_driver():
    result = KiCadConnector(FIXTURE, "test-project").ingest()
    names = [e.name.lower() for e in result["entities"]]
    assert any("tb6612" in n for n in names), "TB6612 motor driver should be parsed"


def test_ingest_types_parts_and_nets():
    result = KiCadConnector(FIXTURE, "test-project").ingest()
    types = {e.entity_type for e in result["entities"]}
    assert EntityType.ELECTRICAL_PART in types
    assert EntityType.INTERFACE in types  # nets


def test_ingest_relations_reference_real_entities():
    result = KiCadConnector(FIXTURE, "test-project").ingest()
    entity_ids = {e.id for e in result["entities"]}
    for rel in result["relations"]:
        assert rel.source_entity_id in entity_ids
        assert rel.target_entity_id in entity_ids
