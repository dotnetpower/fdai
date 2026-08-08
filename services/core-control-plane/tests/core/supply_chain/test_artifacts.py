"""Trusted supply-chain artifact contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.supply_chain import (
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
)

_NOW = datetime(2026, 7, 17, 11, 0, tzinfo=UTC)


def _record() -> TrustedArtifactRecord:
    return TrustedArtifactRecord(
        kind=TrustedArtifactKind.EXTENSION,
        artifact_id="example.extension",
        version="1.2.3",
        source="publisher.example",
        content_sha256="a" * 64,
        artifact=b"archive",
        signature=b"s" * 64,
        state=TrustedArtifactState.DISABLED,
        revision=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_valid_record_preserves_disabled_first_state() -> None:
    record = _record()

    assert record.state is TrustedArtifactState.DISABLED
    assert record.kind is TrustedArtifactKind.EXTENSION


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("artifact_id", "BAD"),
        ("version", "latest"),
        ("content_sha256", "bad"),
        ("signature", b"short"),
        ("revision", 0),
        ("updated_at", _NOW - timedelta(seconds=1)),
    ),
)
def test_invalid_record_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(_record(), **{field: value})
