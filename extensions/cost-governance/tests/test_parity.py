from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import fdai.core.verticals.cost_governance as legacy_cost_governance
import pytest
from fdai.core.verticals.cost_governance import (
    FinOpsActionKind as LegacyActionKind,
)
from fdai.core.verticals.cost_governance import FinOpsCandidate as LegacyCandidate
from fdai.core.verticals.cost_governance import (
    FinOpsEnvironment as LegacyEnvironment,
)
from fdai.core.verticals.cost_governance import FinOpsGuard as LegacyGuard
from fdai.core.verticals.cost_governance import (
    LegacyRollingCostAdvisoryProvider,
)
from fdai.core.verticals.cost_governance import ResourceContext as LegacyContext
from fdai.shared.providers.cost_governance import CostAnalysisSample

from fdai_cost_governance import (
    ApprovedParityDifference,
    CostGovernanceParityHarness,
    CostParityError,
    CostParityOwner,
    CostParityRecord,
    FinOpsActionKind,
    FinOpsCandidate,
    FinOpsEnvironment,
    FinOpsGuard,
    ResourceContext,
    RollingCostAdvisoryProvider,
    value_digest,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS = REPO_ROOT / "tests/integration/fixtures/cost_governance_w6_parity/parity-corpus.json"


def _corpus() -> dict[str, Any]:
    value = json.loads(CORPUS.read_text(encoding="utf-8"))
    assert value["frozen"] is True
    return value


def _record(
    *,
    case: dict[str, Any],
    owner: CostParityOwner,
    legacy: bool,
) -> CostParityRecord:
    if legacy:
        decision = LegacyGuard().evaluate(
            LegacyCandidate(
                action_id=case["action_id"],
                kind=LegacyActionKind(case["kind"]),
                resource=LegacyContext(
                    resource_id=case["resource_id"],
                    environment=LegacyEnvironment(case["environment"]),
                    tags=frozenset(case["tags"]),
                    current_capacity=case["current_capacity"],
                    dependent_ids=tuple(case["dependent_ids"]),
                ),
                target_capacity=case["target_capacity"],
            )
        )
    else:
        decision = FinOpsGuard().evaluate(
            FinOpsCandidate(
                action_id=case["action_id"],
                kind=FinOpsActionKind(case["kind"]),
                resource=ResourceContext(
                    resource_id=case["resource_id"],
                    environment=FinOpsEnvironment(case["environment"]),
                    tags=frozenset(case["tags"]),
                    current_capacity=case["current_capacity"],
                    dependent_ids=tuple(case["dependent_ids"]),
                ),
                target_capacity=case["target_capacity"],
            )
        )
    reasons = tuple(decision.reasons)
    return CostParityRecord(
        case_id=case["case_id"],
        implementation=owner,
        decision=decision.outcome.value,
        reasons=reasons,
        topic="object.policy-decision",
        payload={
            "action_id": decision.action_id,
            "decision": decision.outcome.value,
            "reasons": list(reasons),
        },
        audit_fields={
            "action_id": decision.action_id,
            "reason_count": len(reasons),
            "terminal": True,
        },
        ontology_lineage=_corpus()["ontology_lineage"],
    )


async def _advisory_record(
    *,
    owner: CostParityOwner,
    legacy: bool,
) -> CostParityRecord:
    corpus = _corpus()
    case = corpus["advisory_case"]
    now = datetime.fromisoformat(case["observed_at"].replace("Z", "+00:00"))
    provider = (
        LegacyRollingCostAdvisoryProvider(
            ontology_release_digest=corpus["ontology_lineage"]["ontology_release_digest"],
            clock=lambda: now,
        )
        if legacy
        else RollingCostAdvisoryProvider(
            ontology_release_digest=corpus["ontology_lineage"]["ontology_release_digest"],
            clock=lambda: now,
        )
    )
    advisory = None
    for index, amount in enumerate(case["amounts_usd"]):
        advisory = await provider.analyze_cost_sample(
            CostAnalysisSample(
                scope_id=case["scope_id"],
                resource_id=case["resource_id"],
                amount_usd=Decimal(amount),
                observed_at=now,
                correlation_id=f"parity-sample-{index}",
                source_authority="parity-fixture",
                completeness=Decimal("1"),
                ontology_release_digest=corpus["ontology_lineage"]["ontology_release_digest"],
            )
        )
        now = now.replace(minute=now.minute + 1)
    assert advisory is not None
    effects = []
    for action_type in case["effect_action_types"]:
        estimate = provider.estimate_cost_effect(action_type)
        effects.append(
            None
            if estimate is None
            else {
                "action_type": estimate.action_type,
                "confidence": str(estimate.confidence),
                "evidence_digest": estimate.evidence_digest,
                "monthly_delta_usd": str(estimate.monthly_delta_usd),
                "source_authority": estimate.source_authority,
            }
        )
    payload = {
        "amount_usd": str(advisory.amount_usd),
        "baseline_usd": str(advisory.baseline_usd),
        "correlation_id": advisory.correlation_id,
        "effects": effects,
        "impact": str(advisory.impact),
        "ratio": str(advisory.ratio),
        "recommendation": advisory.recommendation,
        "resource_id": advisory.resource_id,
        "scope_id": advisory.scope_id,
    }
    return CostParityRecord(
        case_id=case["case_id"],
        implementation=owner,
        decision="advisory",
        reasons=(),
        topic="object.cost-anomaly",
        payload=payload,
        audit_fields={
            "effect_count": len(effects),
            "observed_at": advisory.observed_at.astimezone(UTC).isoformat(),
            "terminal": True,
        },
        ontology_lineage=corpus["ontology_lineage"],
    )


async def _records() -> tuple[
    tuple[CostParityRecord, ...],
    tuple[CostParityRecord, ...],
]:
    corpus = _corpus()
    legacy = tuple(
        _record(case=case, owner=CostParityOwner.LEGACY, legacy=True)
        for case in corpus["guard_cases"]
    )
    package = tuple(
        _record(case=case, owner=CostParityOwner.PACKAGE, legacy=False)
        for case in corpus["guard_cases"]
    )
    return (
        (*legacy, await _advisory_record(owner=CostParityOwner.LEGACY, legacy=True)),
        (*package, await _advisory_record(owner=CostParityOwner.PACKAGE, legacy=False)),
    )


async def test_frozen_guard_and_advisory_corpus_has_exact_parity() -> None:
    legacy, package = await _records()

    report = CostGovernanceParityHarness().compare(
        legacy=legacy,
        package=package,
        selected_owner=CostParityOwner.PACKAGE,
        publisher_claims=(CostParityOwner.PACKAGE,),
    )

    assert report.case_count == 6
    assert report.approved_difference_count == 0
    assert report.publication_records == package


async def test_versioned_exact_difference_is_required_and_consumed() -> None:
    legacy, package = await _records()
    changed = package[0]
    changed_payload = {**changed.payload, "contract_version": "2.0.0"}
    package = (
        CostParityRecord(
            case_id=changed.case_id,
            implementation=changed.implementation,
            decision=changed.decision,
            reasons=changed.reasons,
            topic=changed.topic,
            payload=changed_payload,
            audit_fields=changed.audit_fields,
            ontology_lineage=changed.ontology_lineage,
        ),
        *package[1:],
    )
    with pytest.raises(CostParityError, match="unapproved"):
        CostGovernanceParityHarness().compare(
            legacy=legacy,
            package=package,
            selected_owner=CostParityOwner.PACKAGE,
            publisher_claims=(CostParityOwner.PACKAGE,),
        )

    report = CostGovernanceParityHarness().compare(
        legacy=legacy,
        package=package,
        selected_owner=CostParityOwner.PACKAGE,
        publisher_claims=(CostParityOwner.PACKAGE,),
        approved_differences=(
            ApprovedParityDifference(
                mechanism_version="1.0.0",
                approval_id="parity-difference:payload-v2",
                case_id=changed.case_id,
                field="payload",
                legacy_value_digest=value_digest(dict(legacy[0].payload)),
                package_value_digest=value_digest(changed_payload),
            ),
        ),
    )
    assert report.approved_difference_count == 1


async def test_dual_writer_or_nonselected_writer_is_a_hard_failure() -> None:
    legacy, package = await _records()
    harness = CostGovernanceParityHarness()

    with pytest.raises(CostParityError, match="dual-writer"):
        harness.compare(
            legacy=legacy,
            package=package,
            selected_owner=CostParityOwner.PACKAGE,
            publisher_claims=(CostParityOwner.LEGACY, CostParityOwner.PACKAGE),
        )
    with pytest.raises(CostParityError, match="dual-writer"):
        harness.compare(
            legacy=legacy,
            package=package,
            selected_owner=CostParityOwner.PACKAGE,
            publisher_claims=(CostParityOwner.PACKAGE, CostParityOwner.PACKAGE),
        )
    with pytest.raises(CostParityError, match="only the selected"):
        harness.compare(
            legacy=legacy,
            package=package,
            selected_owner=CostParityOwner.PACKAGE,
            publisher_claims=(CostParityOwner.LEGACY,),
        )


async def test_dual_read_without_publication_is_inert() -> None:
    legacy, package = await _records()
    report = CostGovernanceParityHarness().compare(
        legacy=legacy,
        package=package,
        selected_owner=CostParityOwner.PACKAGE,
        publisher_claims=(),
    )

    assert report.publication_records == ()


def test_n_minus_one_python_facade_remains_deprecated_and_inert() -> None:
    assert legacy_cost_governance.FinOpsGuard is LegacyGuard
    assert legacy_cost_governance.COMPATIBILITY_STATUS == "deprecated-inert-parity-only"
    assert legacy_cost_governance.REMOVAL_REVIEW_GATE == "w7-operational-validation-complete"
