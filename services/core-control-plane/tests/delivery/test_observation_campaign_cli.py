"""Focused observation campaign CLI composition tests."""

from __future__ import annotations

import pytest
from fdai.delivery.observation_campaign_cli import (
    _campaign_id,
    _csv,
    _required_consistent,
    _required_first,
)


def test_campaign_id_is_bounded_machine_identifier() -> None:
    values = {_campaign_id() for _ in range(100)}
    value = next(iter(values))

    assert len(values) == 100
    assert value.startswith("campaign-")
    assert value == value.lower()
    assert len(value) < 96


def test_csv_deduplicates_scopes_in_order() -> None:
    assert _csv("first, second, first") == ("first", "second")


def test_required_first_uses_first_populated_environment(monkeypatch) -> None:
    monkeypatch.setenv("SECOND", "value")

    assert _required_first("FIRST", "SECOND") == "value"


def test_required_consistent_rejects_conflicting_aliases(monkeypatch) -> None:
    monkeypatch.setenv("FIRST", "one")
    monkeypatch.setenv("SECOND", "two")

    with pytest.raises(ValueError, match="MUST agree"):
        _required_consistent("FIRST", "SECOND")
