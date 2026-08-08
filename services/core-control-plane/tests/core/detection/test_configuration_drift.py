from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.detection.configuration_drift import (
    ConfigurationLink,
    ConfigurationObservation,
    ConfigurationResource,
    DriftType,
    DriftVerdict,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
    compare_configuration,
)

_NOW = datetime(2026, 8, 4, tzinfo=UTC)
_DOC_HASH = "a" * 64


def _resource(
    name: str = "service-a",
    *,
    sku: str = "Standard",
    unknown: frozenset[str] = frozenset(),
    unauthorized: frozenset[str] = frozenset(),
) -> ConfigurationResource:
    attributes = {} if "sku" in unknown or "sku" in unauthorized else {"sku": sku, "state": "Ready"}
    if attributes and ("state" in unknown or "state" in unauthorized):
        attributes.pop("state")
    return ConfigurationResource(
        local_name=name,
        resource_type="example/service",
        region="Korea Central",
        attributes=attributes,
        unknown_attributes=unknown,
        unauthorized_attributes=unauthorized,
    )


def _baseline(*resources: ConfigurationResource) -> FrozenConfigurationBaseline:
    return FrozenConfigurationBaseline(
        version="s13-v1",
        created_at=_NOW,
        scope="example-scope",
        source="reviewed inventory snapshot",
        document_sha256=_DOC_HASH,
        resources=resources or (_resource(),),
        links=(ConfigurationLink("service-a", "depends_on", "service-b"),),
    )


def _observation(
    *resources: ConfigurationResource,
    completeness: EvidenceCompleteness = EvidenceCompleteness.COMPLETE,
    links: tuple[ConfigurationLink, ...] | None = None,
) -> ConfigurationObservation:
    return ConfigurationObservation(
        scope="example-scope",
        observed_at=_NOW,
        source="authoritative inventory",
        completeness=completeness,
        resources=resources or (_resource(),),
        links=(ConfigurationLink("service-a", "depends_on", "service-b"),)
        if links is None
        else links,
    )


def test_canonical_hash_is_stable_across_resource_and_attribute_order() -> None:
    first = _baseline(
        ConfigurationResource(
            local_name="service-b",
            resource_type="example/service",
            region="korea central",
            attributes={"state": "Ready", "nested": {"b": 2, "a": 1}},
        ),
        _resource(),
    )
    second = _baseline(
        ConfigurationResource(
            local_name="service-a",
            resource_type="EXAMPLE/SERVICE",
            region="KOREA CENTRAL",
            attributes={"state": "Ready", "sku": "Standard"},
        ),
        ConfigurationResource(
            local_name="service-b",
            resource_type="example/service",
            region="korea central",
            attributes={"nested": {"a": 1, "b": 2}, "state": "Ready"},
        ),
    )

    assert first.sha256 == second.sha256


def test_unchanged_snapshot_passes_with_zero_safety_counters() -> None:
    report = compare_configuration(_baseline(), _observation())

    assert report.verdict is DriftVerdict.PASSED
    assert {finding.drift_type for finding in report.findings} == {DriftType.UNCHANGED}
    assert report.mutation_count == 0
    assert report.approval_request_count == 0
    assert report.mitigation_execution_count == 0
    assert report.unsupported_claim_count == 0


def test_complete_snapshot_reports_added_removed_and_changed() -> None:
    report = compare_configuration(
        _baseline(_resource(), _resource("service-removed")),
        _observation(_resource(sku="Premium"), _resource("service-added")),
    )

    assert report.verdict is DriftVerdict.FAILED
    types = {finding.drift_type for finding in report.findings}
    assert {DriftType.ADDED, DriftType.REMOVED, DriftType.CHANGED} <= types


def test_partial_snapshot_never_turns_missing_resource_or_link_into_removed() -> None:
    report = compare_configuration(
        _baseline(_resource(), _resource("service-missing")),
        _observation(
            _resource(),
            completeness=EvidenceCompleteness.PARTIAL,
            links=(),
        ),
    )

    missing = [finding for finding in report.findings if "missing" in finding.target]
    topology = [finding for finding in report.findings if finding.field == "topology"]
    assert report.verdict is DriftVerdict.BLOCKED
    assert missing and missing[0].drift_type is DriftType.UNKNOWN
    assert topology and topology[0].drift_type is DriftType.UNKNOWN
    assert all(finding.drift_type is not DriftType.REMOVED for finding in missing + topology)


def test_unknown_and_unauthorized_attributes_remain_blocked() -> None:
    actual = ConfigurationResource(
        local_name="service-a",
        resource_type="example/service",
        region="korea central",
        attributes={},
        unknown_attributes=frozenset({"state"}),
        unauthorized_attributes=frozenset({"sku"}),
    )

    report = compare_configuration(_baseline(), _observation(actual))

    assert report.verdict is DriftVerdict.BLOCKED
    by_field = {finding.field: finding for finding in report.findings}
    assert by_field["state"].drift_type is DriftType.UNKNOWN
    assert by_field["sku"].drift_type is DriftType.UNAUTHORIZED


def test_scope_mismatch_fails_closed() -> None:
    observation = ConfigurationObservation(
        scope="another-scope",
        observed_at=_NOW,
        source="authoritative inventory",
        completeness=EvidenceCompleteness.COMPLETE,
        resources=(_resource(),),
    )

    report = compare_configuration(_baseline(), observation)

    assert report.verdict is DriftVerdict.BLOCKED
    assert report.findings[0].field == "scope"
    assert report.findings[0].drift_type is DriftType.UNAUTHORIZED


def test_rejects_duplicate_resources_and_non_finite_values() -> None:
    with pytest.raises(ValueError, match="resource keys MUST be unique"):
        _baseline(_resource(), _resource())

    with pytest.raises(ValueError, match="finite"):
        ConfigurationResource(
            local_name="service-a",
            resource_type="example/service",
            region="korea central",
            attributes={"ratio": float("nan")},
        )


def test_baseline_unknowns_block_and_allowed_exceptions_remain_visible() -> None:
    baseline = FrozenConfigurationBaseline(
        version="s13-v1",
        created_at=_NOW,
        scope="example-scope",
        source="reviewed inventory snapshot",
        document_sha256=_DOC_HASH,
        resources=(_resource(),),
        allowed_exceptions=("generated suffix may vary",),
        unknown_items=("certificate metadata inaccessible",),
    )

    report = compare_configuration(baseline, _observation(links=()))

    assert report.verdict is DriftVerdict.BLOCKED
    by_field = {finding.field: finding for finding in report.findings}
    assert by_field["allowed_exception"].verdict is DriftVerdict.NOT_APPLICABLE
    assert by_field["unknown_item"].drift_type is DriftType.UNKNOWN
