"""Unit tests for ContextEngine.compute_diff — the pure snapshot diff
that powers change events on source sync."""

from src.context_engine import ContextEngine


def diff(old_items, new_items):
    return ContextEngine().compute_diff({"items": old_items}, {"items": new_items})


def test_added_item():
    diffs = diff([], [{"ref": "U1", "value": "ATmega328P"}])
    assert diffs == [{
        "type": "added", "ref": "U1",
        "old": None, "new": {"ref": "U1", "value": "ATmega328P"},
        "changed_fields": [],
    }]


def test_removed_item():
    diffs = diff([{"ref": "R1", "value": "10k"}], [])
    assert len(diffs) == 1
    assert diffs[0]["type"] == "removed"
    assert diffs[0]["ref"] == "R1"
    assert diffs[0]["new"] is None


def test_modified_item_reports_changed_fields():
    diffs = diff(
        [{"ref": "U2", "value": "TB6612", "pin": 5}],
        [{"ref": "U2", "value": "TB6612FNG", "pin": 5}],
    )
    assert len(diffs) == 1
    assert diffs[0]["type"] == "modified"
    assert diffs[0]["changed_fields"] == ["value"]


def test_unchanged_items_produce_no_diff():
    items = [{"ref": "U1", "value": "ATmega328P"}, {"ref": "R1", "value": "10k"}]
    assert diff(items, list(items)) == []


def test_mixed_diff():
    old = [{"ref": "A", "v": 1}, {"ref": "B", "v": 2}]
    new = [{"ref": "B", "v": 3}, {"ref": "C", "v": 4}]
    types = {d["ref"]: d["type"] for d in diff(old, new)}
    assert types == {"A": "removed", "B": "modified", "C": "added"}
