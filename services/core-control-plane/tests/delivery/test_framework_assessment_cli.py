"""Governed live-runner composition tests for WAF and CAF shadow assessment."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.framework_assessment import (
    FrameworkAssessmentRuntime,
    FrameworkAssessmentService,
    FrameworkSatisfactionStatus,
)
from fdai.delivery.framework_assessment_cli import (
    FrameworkAssessmentJobSettings,
    _caf_hierarchy_evidence,
    _load_hierarchy_generation,
    _profile,
    _waf_scope_digest,
    execute_framework_assessment_tick,
)
from fdai.delivery.persistence.postgres_wara_scope import (
    WaraResolvedResource,
    WaraResolvedScope,
)
from fdai.rule_catalog.schema.framework_assessment import (
    canonical_digest,
    load_framework_assessment_catalog,
)

ROOT = Path(__file__).resolve().parents[4]
GENERATED = ROOT / "rule-catalog/framework-assessments/generated"
NOW = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)


def _catalog(name: str):
    return load_framework_assessment_catalog(GENERATED / f"{name}.json")


def _scope() -> WaraResolvedScope:
    return WaraResolvedScope(
        workload_id="workload-example",
        ontology_release="2026.09",
        inventory_generation="inventory-1",
        resources=(
            WaraResolvedResource(
                neutral_resource_id="resource-example",
                provider_resource_id="/subscriptions/example/resourceGroups/example/providers/Microsoft.Compute/virtualMachines/vm",
                provider_resource_type="Microsoft.Compute/virtualMachines",
            ),
        ),
    )


def _settings(tmp_path: Path) -> FrameworkAssessmentJobSettings:
    hierarchy = tmp_path / "hierarchy.json"
    hierarchy.write_text(
        json.dumps(
            {
                "count": 1,
                "totalRecords": 1,
                "resultTruncated": False,
                "data": [{"subscription_id": "subscription-example"}],
            }
        ),
        encoding="utf-8",
    )
    return FrameworkAssessmentJobSettings(
        dsn="postgresql://example",
        workload_id="workload-example",
        inventory_freshness_seconds=86_400,
        maximum_resources=1_000,
        tenant_id="tenant-example",
        subscription_id="subscription-example",
        hierarchy_path=hierarchy,
        reviewer_identity="reviewer@example.com",
    )


class _Store:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    async def append_audit_entry(self, entry):
        self.entries.append(dict(entry))


class _Bus:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def publish(self, topic, key, payload):
        del topic, key
        self.events.append(dict(payload))
        return object()


def test_live_profiles_cover_complete_catalogs_with_exact_generations() -> None:
    waf = _catalog("azure-waf")
    caf = _catalog("azure-caf")
    scope = _scope()
    waf_profile = _profile(
        waf,
        scope_digest=_waf_scope_digest(scope),
        ontology_release=scope.ontology_release,
        reviewer_identity="reviewer@example.com",
        reviewed_at=NOW,
        inventory_generation=scope.inventory_generation,
    )
    caf_profile = _profile(
        caf,
        scope_digest=canonical_digest({"scope": "estate"}),
        ontology_release=scope.ontology_release,
        reviewer_identity="reviewer@example.com",
        reviewed_at=NOW,
        hierarchy_generation=canonical_digest({"hierarchy": "current"}),
    )

    assert len(waf_profile.applicability) == 59
    assert len(caf_profile.applicability) == 15
    assert waf_profile.inventory_generation == "inventory-1"
    assert caf_profile.hierarchy_generation is not None


def test_caf_hierarchy_receipts_are_exact_scope_and_no_authority(tmp_path: Path) -> None:
    catalog = _catalog("azure-caf")
    generation, complete = _load_hierarchy_generation(_settings(tmp_path).hierarchy_path)

    receipts = _caf_hierarchy_evidence(
        catalog,
        scope_digest=canonical_digest({"scope": "estate"}),
        hierarchy_generation=generation,
        hierarchy_complete=complete,
        observed_at=NOW,
    )

    assert len(receipts) == 2
    assert all(item.hierarchy_generation == generation for item in receipts)
    assert all(item.outcome is FrameworkSatisfactionStatus.SATISFIED for item in receipts)


def test_truncated_hierarchy_cannot_claim_complete_observation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.hierarchy_path.write_text(
        json.dumps(
            {
                "count": 1,
                "totalRecords": 2,
                "resultTruncated": True,
                "$skipToken": "opaque",
                "data": [{"subscription_id": "subscription-example"}],
            }
        ),
        encoding="utf-8",
    )
    generation, complete = _load_hierarchy_generation(settings.hierarchy_path)

    receipts = _caf_hierarchy_evidence(
        _catalog("azure-caf"),
        scope_digest=canonical_digest({"scope": "estate"}),
        hierarchy_generation=generation,
        hierarchy_complete=complete,
        observed_at=NOW,
    )

    assert complete is False
    assert all(item.truncated for item in receipts)
    assert all(item.outcome is FrameworkSatisfactionStatus.UNKNOWN for item in receipts)


async def test_tick_publishes_sanitized_waf_and_caf_snapshots(tmp_path: Path) -> None:
    waf = _catalog("azure-waf")
    caf = _catalog("azure-caf")
    store = _Store()
    bus = _Bus()

    report = await execute_framework_assessment_tick(
        settings=_settings(tmp_path),
        scope=_scope(),
        waf_service=FrameworkAssessmentService(
            FrameworkAssessmentRuntime(waf),
            store,
            bus,
        ),
        caf_service=FrameworkAssessmentService(
            FrameworkAssessmentRuntime(caf),
            store,
            bus,
        ),
        waf_catalog=waf,
        caf_catalog=caf,
        now=NOW,
        source_revision="a" * 40,
    )

    assert report.workload_resource_count == 1
    assert len(store.entries) == len(bus.events) == 2
    assert all(event["execution_authority"] is False for event in bus.events)
    assert bus.events[0]["scope_digest"].startswith("sha256:")
    assert "workload-example" not in json.dumps(report.to_dict())


def test_publication_is_an_explicit_opt_in_that_needs_a_bus() -> None:
    from fdai.delivery.framework_assessment_cli import (
        FrameworkAssessmentJobConfigurationError,
        publication_requested,
    )

    assert publication_requested({}) is False
    assert publication_requested({"FDAI_FRAMEWORK_ASSESSMENT_PUBLISH": "0"}) is False
    assert (
        publication_requested(
            {
                "FDAI_FRAMEWORK_ASSESSMENT_PUBLISH": "1",
                "KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:19092",
            }
        )
        is True
    )
    for environ in (
        {"FDAI_FRAMEWORK_ASSESSMENT_PUBLISH": "1"},
        {"FDAI_FRAMEWORK_ASSESSMENT_PUBLISH": "yes", "KAFKA_BOOTSTRAP_SERVERS": "x:1"},
    ):
        with pytest.raises(FrameworkAssessmentJobConfigurationError):
            publication_requested(environ)


async def test_published_tick_reports_publication_and_publishes_every_framework(
    tmp_path: Path,
) -> None:
    waf = _catalog("azure-waf")
    caf = _catalog("azure-caf")
    mcsb = _catalog("azure-mcsb")
    store = _Store()
    bus = _Bus()
    from fdai.delivery.framework_rule_evidence_source import (
        WorkloadRuleEvidence,
        WorkloadRuleEvidenceStatus,
    )

    report = await execute_framework_assessment_tick(
        settings=_settings(tmp_path),
        scope=_scope(),
        waf_service=FrameworkAssessmentService(FrameworkAssessmentRuntime(waf), store, bus),
        caf_service=FrameworkAssessmentService(FrameworkAssessmentRuntime(caf), store, bus),
        waf_catalog=waf,
        caf_catalog=caf,
        now=NOW,
        source_revision="a" * 40,
        mcsb=(
            FrameworkAssessmentService(FrameworkAssessmentRuntime(mcsb), store, bus),
            mcsb,
            WorkloadRuleEvidence(WorkloadRuleEvidenceStatus.NO_ACTIVATION, None),
        ),
        publication_status="published",
    )

    assert report.to_dict()["publication_status"] == "published"
    assert {event["framework_id"] for event in bus.events} == {
        "azure-waf",
        "azure-caf",
        "azure-mcsb",
    }
    assert len(store.entries) == len(bus.events) == 3
