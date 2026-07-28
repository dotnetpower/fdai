"""Best Practice integration in the operational-readiness service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from fdai.composition.readiness import OperationalReadinessService
from fdai.core.deploy_preflight import PreflightAnalyzer
from fdai.core.readiness import HandoffVerdict, OwnershipTransfer
from fdai.shared.contracts.models import (
    BestPractice,
    BestPracticeRequirement,
    Category,
    Mode,
    Provenance,
    RequirementKind,
    RequirementMode,
    RequirementOutcome,
    RequirementStatus,
    Severity,
)
from fdai.shared.providers.projection import Finding, ResourceRef
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _Posture:
    def __init__(self, findings: Sequence[Finding] = ()) -> None:
        self.findings = tuple(findings)

    async def findings_for_scope(self, scope: str) -> Sequence[Finding]:
        return self.findings


class _Evidence:
    def __init__(self, outcomes: Sequence[RequirementOutcome]) -> None:
        self.outcomes = tuple(outcomes)

    async def outcomes_for_scope(self, scope: str) -> Sequence[RequirementOutcome]:
        return self.outcomes


class _Publisher:
    async def publish_readiness_report(self, report: Mapping[str, Any]) -> None:
        return None


def _control(kind: RequirementKind, ref: str) -> BestPractice:
    return BestPractice(
        id="azure-waf.reliability.re-10",
        version="1.0.0",
        framework="azure-waf",
        control_id="RE:10",
        title="Track system health",
        rationale="Health must be measured.",
        severity=Severity.HIGH,
        category=Category.RELIABILITY,
        requirement_mode=RequirementMode.ALL,
        requirements=(BestPracticeRequirement(kind=kind, ref=ref),),
        provenance=Provenance.model_validate(
            {
                "source_url": "https://example.com/control",
                "resolved_ref": "revision",
                "content_hash": "sha256:example",
                "license": "CC-BY-4.0",
                "redistribution": "embeddable",
                "retrieved_at": datetime(2026, 7, 29, tzinfo=UTC),
            }
        ),
    )


def _service(
    control: BestPractice,
    *,
    outcomes: Sequence[RequirementOutcome] = (),
    findings: Sequence[Finding] = (),
    bind_evidence: bool = True,
) -> tuple[OperationalReadinessService, InMemoryStateStore]:
    store = InMemoryStateStore()
    return (
        OperationalReadinessService(
            posture=_Posture(findings),
            preflight=PreflightAnalyzer((), mode=Mode.ENFORCE, clock=lambda: "ignored"),
            publisher=_Publisher(),
            state_store=store,
            mode=Mode.ENFORCE,
            clock=lambda: "2026-07-29T00:00:00Z",
            best_practices=(control,),
            checklist_evidence=_Evidence(outcomes) if bind_evidence else None,
        ),
        store,
    )


def _signal() -> OwnershipTransfer:
    return OwnershipTransfer(
        scope="scope-example",
        submitter="user@example.com",
        target_environment="prod",
    )


async def test_missing_evidence_blocks_enforce_handoff() -> None:
    service, _ = _service(_control(RequirementKind.ARTIFACT, "health-evidence"))

    report = await service.review(_signal())

    assert report.verdict is HandoffVerdict.BLOCKED
    assert report.findings[0].source == "best_practice"
    assert report.findings[0].control_id == "RE:10"
    assert report.findings[0].requirement_refs == ("health-evidence",)


async def test_missing_provider_abstains_and_audits_failure() -> None:
    service, store = _service(
        _control(RequirementKind.ARTIFACT, "health-evidence"),
        bind_evidence=False,
    )

    with pytest.raises(RuntimeError, match="require a checklist evidence provider"):
        await service.review(_signal())

    assert store.audit_entries[0]["entry"]["outcome"] == "assessment_failed"


async def test_live_rule_finding_overrides_provided_pass() -> None:
    rule_id = "object-storage.diagnostic-settings-required"
    control = _control(RequirementKind.RULE, rule_id)
    pass_outcome = RequirementOutcome(
        kind=RequirementKind.RULE,
        ref=rule_id,
        status=RequirementStatus.SATISFIED,
    )
    finding = Finding(
        rule_id=rule_id,
        resource=ResourceRef(resource_type="object-storage", ref="resource-example"),
        severity="high",
        reason="diagnostics missing",
    )
    service, _ = _service(control, outcomes=(pass_outcome,), findings=(finding,))

    report = await service.review(_signal())

    assert report.verdict is HandoffVerdict.BLOCKED
    assert any(item.source == "best_practice" for item in report.findings)
