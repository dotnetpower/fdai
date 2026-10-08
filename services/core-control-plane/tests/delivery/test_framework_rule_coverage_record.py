"""Persisted scoped Rule coverage records reject mixed scope, activation, and catalog identity."""

from __future__ import annotations

import pytest
from fdai.core.framework_rule_evidence import SCOPED_COVERAGE_AUDIT_KIND
from fdai.delivery.framework_rule_evidence_source import (
    WorkloadRuleEvidenceStatus,
    persist_scoped_rule_coverage,
)
from fdai.delivery.persistence.postgres_wara_scope import WaraResolvedResource, WaraResolvedScope
from fdai_service_contracts.baseline_evaluation import BaselineEvaluationCoverage
from fdai_service_contracts.framework_rule_coverage import (
    FRAMEWORK_RULE_COVERAGE_LATEST_KEY,
    ScopedRuleCoverageIdentityError,
    ScopedRuleCoverageRecord,
    framework_rule_coverage_record_digest,
    framework_rule_coverage_record_key,
    verify_scoped_rule_coverage_identity,
)
from pydantic import ValidationError

from tests.delivery.test_framework_rule_evidence_source import (
    COMPLIANT_RULE,
    VIOLATED_RULE,
    _activation,
    _baseline,
    _load,
    _scope,
    _Store,
)

_OTHER_DIGEST = "sha256:" + "f" * 64


class _AuditingStore(_Store):
    """Keeps the atomic record-and-audit writes of the in-memory store observable."""


async def _ready() -> tuple[_AuditingStore, ScopedRuleCoverageRecord, BaselineEvaluationCoverage]:
    store = _AuditingStore()
    activation = _activation()
    await _baseline(store, activation)
    evidence = await _load(store, activation)
    assert evidence.status is WorkloadRuleEvidenceStatus.READY
    assert evidence.coverage_record is not None
    baseline = BaselineEvaluationCoverage.model_validate(
        await store.read_state("baseline-evaluation:latest:coverage")
    )
    return store, evidence.coverage_record, baseline


def _resealed(record: ScopedRuleCoverageRecord, **changes: object) -> dict[str, object]:
    """Change fields and recompute only the outer record digest, as a careless writer would."""

    values = {**record.model_dump(mode="python"), **changes}
    values["record_digest"] = framework_rule_coverage_record_digest(**values)
    return values


@pytest.mark.asyncio
async def test_record_binds_the_receipt_coverage_digest_and_baseline() -> None:
    store = _AuditingStore()
    activation = _activation()
    await _baseline(store, activation)
    evidence = await _load(store, activation)
    record = evidence.coverage_record
    assert record is not None

    digests = {
        item.rule_provenance.coverage_digest
        for item in evidence.receipts
        if item.rule_provenance is not None
    }
    assert digests == {record.scoped_coverage_digest}
    assert record.framework_id == "azure-waf"
    assert record.workload_id == "workload-example"
    assert [item.provider_resource_id for item in record.resources] == [
        "/providers/example/cluster-1",
        "/providers/example/storage-1",
    ]
    violated = record.rule(VIOLATED_RULE)
    compliant = record.rule(COMPLIANT_RULE)
    assert violated is not None and (violated.eligible_count, violated.violated_count) == (1, 1)
    assert compliant is not None and (compliant.eligible_count, compliant.compliant_count) == (1, 1)
    assert record.execution_authority is False
    assert record.projection_authority is False


@pytest.mark.asyncio
async def test_persisted_record_is_immutable_audited_once_and_published_latest() -> None:
    store, record, _ = await _ready()

    assert await persist_scoped_rule_coverage(store, record) is True
    assert await persist_scoped_rule_coverage(store, record) is False

    stored = await store.read_state(framework_rule_coverage_record_key(record.record_digest))
    latest = await store.read_state(FRAMEWORK_RULE_COVERAGE_LATEST_KEY)
    assert stored is not None and latest is not None
    assert ScopedRuleCoverageRecord.model_validate(stored) == record
    assert ScopedRuleCoverageRecord.model_validate(latest) == record
    audits = [
        item["entry"]
        for item in store.audit_entries
        if item["entry"].get("action_kind") == SCOPED_COVERAGE_AUDIT_KIND
    ]
    assert len(audits) == 1
    assert audits[0]["audit_ref"] == record.audit_ref
    assert audits[0]["execution_authority"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"scope_digest": _OTHER_DIGEST},
        {"rule_activation_generation_digest": _OTHER_DIGEST},
        {"rule_activation_generation_id": "rule-activation-" + "0" * 32},
        {"rule_catalog_digest": _OTHER_DIGEST},
        {"inventory_generation": "inventory-2"},
    ],
    ids=["scope", "activation-digest", "activation-id", "rule-catalog", "inventory"],
)
async def test_mixed_identity_inside_the_record_breaks_the_coverage_digest(
    changes: dict[str, object],
) -> None:
    _, record, _ = await _ready()

    with pytest.raises(ValidationError, match="scoped Rule coverage digest mismatch"):
        ScopedRuleCoverageRecord.model_validate(_resealed(record, **changes))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"evaluated_rule_catalog_digest": _OTHER_DIGEST}, "evaluated Rule catalog"),
        ({"baseline_coverage_digest": _OTHER_DIGEST}, "baseline coverage"),
        ({"inventory_observation_digest": _OTHER_DIGEST}, "inventory observation"),
        ({"expected_pair_set_digest": _OTHER_DIGEST}, "expected pair set"),
        ({"baseline_generation_id": "generation:inventory-2"}, "inventory generation"),
    ],
)
async def test_record_from_another_baseline_is_rejected(
    changes: dict[str, object],
    message: str,
) -> None:
    _, record, baseline = await _ready()
    foreign = ScopedRuleCoverageRecord.model_validate(_resealed(record, **changes))

    with pytest.raises(ScopedRuleCoverageIdentityError, match=message):
        verify_scoped_rule_coverage_identity(foreign, baseline=baseline)


@pytest.mark.asyncio
async def test_record_for_another_scope_or_activation_pin_is_rejected() -> None:
    _, record, baseline = await _ready()

    verify_scoped_rule_coverage_identity(
        record,
        baseline=baseline,
        scope_digest=record.scope_digest,
        rule_activation_generation_digest=record.rule_activation_generation_digest,
    )
    with pytest.raises(ScopedRuleCoverageIdentityError, match="scope mismatch"):
        verify_scoped_rule_coverage_identity(record, baseline=baseline, scope_digest=_OTHER_DIGEST)
    with pytest.raises(ScopedRuleCoverageIdentityError, match="activation pin mismatch"):
        verify_scoped_rule_coverage_identity(
            record, baseline=baseline, rule_activation_generation_digest=_OTHER_DIGEST
        )


@pytest.mark.asyncio
async def test_tampered_counts_mapping_and_digest_are_rejected() -> None:
    _, record, _ = await _ready()
    first = record.rules[0].model_dump(mode="python")
    shifted = {**first, "missing_count": first["missing_count"] + 1}
    duplicate_ref = record.resources[1].model_copy(
        update={"resource_ref": record.resources[0].resource_ref}
    )

    with pytest.raises(ValidationError, match="account every eligible pair"):
        ScopedRuleCoverageRecord.model_validate(
            _resealed(record, rules=(shifted, *record.rules[1:]))
        )
    with pytest.raises(ValidationError, match="resource references MUST be unique"):
        ScopedRuleCoverageRecord.model_validate(
            _resealed(record, resources=(record.resources[0], duplicate_ref))
        )
    with pytest.raises(ValidationError, match="rules MUST be unique and ordered"):
        ScopedRuleCoverageRecord.model_validate(
            _resealed(record, rules=tuple(reversed(record.rules)))
        )
    with pytest.raises(ValidationError, match="record digest mismatch"):
        ScopedRuleCoverageRecord.model_validate(
            {**record.model_dump(mode="python"), "record_digest": _OTHER_DIGEST}
        )


@pytest.mark.asyncio
async def test_ambiguous_provider_mapping_stops_with_scope_mismatch() -> None:
    store = _AuditingStore()
    activation = _activation()
    await _baseline(store, activation)
    base = _scope()
    ambiguous = WaraResolvedScope(
        workload_id=base.workload_id,
        ontology_release=base.ontology_release,
        inventory_generation=base.inventory_generation,
        resources=(
            *base.resources,
            WaraResolvedResource(
                neutral_resource_id="storage-1",
                provider_resource_id="/providers/example/storage-1-alias",
                provider_resource_type="Example/storage",
            ),
        ),
    )

    evidence = await _load(store, activation, scope=ambiguous)

    assert evidence.status is WorkloadRuleEvidenceStatus.SCOPE_MISMATCH
    assert evidence.receipts == ()
    assert evidence.coverage_record is None
