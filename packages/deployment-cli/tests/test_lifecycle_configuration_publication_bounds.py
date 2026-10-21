"""Exercise the actual 256-publication and 16-MiB limits, not reduced test constants."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fdai_deployment_cli import lifecycle_configuration_publication as journal

from .test_lifecycle_configuration_cli import Case, _write
from .test_lifecycle_configuration_cli import case as case
from .test_lifecycle_configuration_publication import build, inspect, publish
from .test_lifecycle_configuration_publication import venue as venue


def test_exact_publication_count_limit_preserves_head_retry(case: Case, venue: Path) -> None:
    assert journal.MAX_PUBLICATIONS == 256
    head: str | None = None
    for index in range(1, 257):
        case.source["revision_id"] = f"{index:040x}"
        _write(case.root / "source.json", case.source)
        record = publish(case, venue, head)
        head = record.package.digest
    assert record.sequence == 256
    assert publish(case, venue, head) == record
    assert inspect(case, venue, record.revision_id) == (record, "present")
    before = (venue / journal._DATABASE).read_bytes()
    case.source["revision_id"] = f"{257:040x}"
    _write(case.root / "source.json", case.source)
    with pytest.raises(ValueError, match="count bound"):
        publish(case, venue, head)
    assert (venue / journal._DATABASE).read_bytes() == before
    assert len(list(venue.glob("*.json"))) == 256


def test_actual_retained_byte_bound_without_truncation(case: Case, venue: Path) -> None:
    assert journal.MAX_PUBLICATION_BYTES == 16 * 1024 * 1024
    schema = case.release["configuration_schema"]
    assert isinstance(schema, dict)
    schema["padding"] = {"x-fdai-axis": "deployment-environment", "x-fdai-owner": "customer"}
    case.source["environment"] = {"padding": "z" * 700_000}
    _write(case.root / "release.json", case.release)
    head: str | None = None
    records: list[journal.Publication] = []
    total = 0
    for index in range(1, 257):
        case.source["revision_id"] = f"{index:040x}"
        _write(case.root / "source.json", case.source)
        candidate = build(case, [r.package for r in records])
        artifact = journal.configuration_artifact_bytes(candidate)
        if total + len(artifact) > journal.MAX_PUBLICATION_BYTES:
            assert total <= journal.MAX_PUBLICATION_BYTES
            before = (venue / journal._DATABASE).read_bytes()
            with pytest.raises(ValueError, match="history bounds"):
                publish(case, venue, head)
            assert (venue / journal._DATABASE).read_bytes() == before
            break
        record = publish(case, venue, head)
        records.append(record)
        head = record.package.digest
        total += len(record.artifact)
    else:
        pytest.fail("the actual byte bound was not exercised")
    assert 1 < len(records) < 256
    with sqlite3.connect(venue / journal._DATABASE) as connection:
        assert connection.execute(
            "SELECT COUNT(*), SUM(length(artifact)) FROM packages"
        ).fetchone() == (
            len(records),
            total,
        )
    assert inspect(case, venue, records[-1].revision_id) == (records[-1], "present")
