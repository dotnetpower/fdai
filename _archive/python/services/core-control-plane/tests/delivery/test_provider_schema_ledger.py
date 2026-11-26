"""Append-only provider schema ledger tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.delivery.provider_schema import (
    ProviderSchemaCoverage,
    ProviderSchemaError,
    ProviderSchemaSnapshot,
    ProviderSchemaType,
)
from fdai.delivery.provider_schema_ledger import ProviderSchemaLedger


def _snapshot(*, revision: str = "a" * 40, version: str = "2025-01-01") -> ProviderSchemaSnapshot:
    return ProviderSchemaSnapshot.build(
        provider="azure",
        source_revision=revision,
        types=(
            ProviderSchemaType(
                resource_type="Microsoft.Example/widgets",
                stable_api_versions=(version,),
                preview_api_versions=(),
                preferred_api_version=version,
                source_document="generated/example/types.md",
            ),
        ),
    )


def test_records_and_replays_content_verified_baseline(tmp_path: Path) -> None:
    ledger = ProviderSchemaLedger(tmp_path)
    snapshot = _snapshot()

    ledger.record_snapshot(
        snapshot,
        observed_at=datetime(2026, 8, 24, tzinfo=UTC),
        accept_baseline=True,
    )

    assert ledger.read_baseline("azure") == snapshot
    assert len(tuple((tmp_path / "azure" / "snapshots").glob("*.json"))) == 1


def test_breaking_observation_can_be_retained_without_advancing_baseline(tmp_path: Path) -> None:
    ledger = ProviderSchemaLedger(tmp_path)
    baseline = _snapshot()
    breaking = _snapshot(revision="b" * 40, version="2024-01-01")
    observed_at = datetime(2026, 8, 24, tzinfo=UTC)
    ledger.record_snapshot(baseline, observed_at=observed_at, accept_baseline=True)

    ledger.record_snapshot(breaking, observed_at=observed_at, accept_baseline=False)

    assert ledger.read_baseline("azure") == baseline
    observed = json.loads((tmp_path / "azure" / "observed.json").read_text(encoding="utf-8"))
    assert observed["schema_digest"] == breaking.schema_digest


def test_detects_snapshot_tampering_on_replay(tmp_path: Path) -> None:
    ledger = ProviderSchemaLedger(tmp_path)
    snapshot = _snapshot()
    ledger.record_snapshot(
        snapshot,
        observed_at=datetime(2026, 8, 24, tzinfo=UTC),
        accept_baseline=True,
    )
    snapshot_file = next((tmp_path / "azure" / "snapshots").glob("*.json"))
    raw = json.loads(snapshot_file.read_text(encoding="utf-8"))
    raw["types"][0]["preferred_api_version"] = "2020-01-01"
    snapshot_file.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ProviderSchemaError, match="preferred API version|digest mismatch"):
        ledger.read_baseline("azure")


def test_run_receipts_are_content_addressed_and_replayable(tmp_path: Path) -> None:
    ledger = ProviderSchemaLedger(tmp_path)
    receipt = {
        "schema_version": "1.0.0",
        "provider": "azure",
        "disposition": "unchanged",
        "checked_at": "2026-08-24T00:00:00+00:00",
        "grants_authority": False,
    }

    first = ledger.record_run("azure", receipt)
    second = ledger.record_run("azure", receipt)

    assert first == second
    assert ledger.read_last_run("azure") == receipt


def test_coverage_artifact_retains_every_explicit_type_disposition(tmp_path: Path) -> None:
    ledger = ProviderSchemaLedger(tmp_path)
    snapshot = _snapshot()
    coverage = ProviderSchemaCoverage.build(
        snapshot=snapshot,
        modeled_provider_types=frozenset(),
    )

    digest = ledger.record_coverage("azure", coverage)

    pointer = json.loads((tmp_path / "azure" / "coverage.json").read_text(encoding="utf-8"))
    artifact = json.loads(
        (tmp_path / "azure" / "coverage" / f"{digest.removeprefix('sha256:')}.json").read_text(
            encoding="utf-8"
        )
    )
    assert pointer["coverage_digest"] == digest
    assert artifact["type_count"] == 1
    assert artifact["entries"] == [
        {
            "resource_type": "microsoft.example/widgets",
            "status": "unsupported-with-reason",
            "reason": "semantic_mapping_not_reviewed",
        }
    ]
    assert artifact["grants_authority"] is False
