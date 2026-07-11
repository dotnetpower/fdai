"""Governance-artifact provenance value object."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.rule_catalog.schema.provenance import Provenance

_AWARE = datetime(2026, 7, 3, tzinfo=UTC)


def test_valid_construction() -> None:
    p = Provenance(created_at=_AWARE, created_by="governance-team")
    assert p.created_by == "governance-team"
    assert p.source is None
    assert p.created_at.tzinfo is not None


def test_empty_created_by_rejected() -> None:
    with pytest.raises(ValueError, match="created_by"):
        Provenance(created_at=_AWARE, created_by="   ")


def test_naive_created_at_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Provenance(created_at=datetime(2026, 7, 3), created_by="team")  # noqa: DTZ001


def test_from_mapping_string_timestamp() -> None:
    p = Provenance.from_mapping({"created_at": "2026-07-03T00:00:00Z", "created_by": "team"})
    assert p.created_at == _AWARE
    assert p.source is None


def test_from_mapping_datetime_timestamp() -> None:
    # a YAML timestamp scalar arrives already parsed as a datetime
    p = Provenance.from_mapping({"created_at": _AWARE, "created_by": "team"})
    assert p.created_at == _AWARE


def test_from_mapping_with_source() -> None:
    p = Provenance.from_mapping(
        {"created_at": "2026-07-03T00:00:00Z", "created_by": "team", "source": "upstream-catalog"}
    )
    assert p.source == "upstream-catalog"


def test_from_mapping_bad_timestamp_rejected() -> None:
    with pytest.raises(ValueError, match="RFC 3339"):
        Provenance.from_mapping({"created_at": "not-a-date", "created_by": "team"})


def test_from_mapping_naive_string_rejected() -> None:
    # a valid ISO string without a timezone -> naive -> rejected by __post_init__
    with pytest.raises(ValueError, match="timezone-aware"):
        Provenance.from_mapping({"created_at": "2026-07-03T00:00:00", "created_by": "team"})
