"""Pre-remediation PR refresh and invalidation without live provider calls."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from fdai.core.deploy_preflight.report import DeploymentReadinessReport, ReadinessVerdict
from fdai.delivery.deploy_preflight.pr_publication import (
    PreflightHoldReason,
    PreflightPublicationHoldError,
    PreflightVerifiedPrPublisher,
    RefreshedPreflight,
)
from fdai.delivery.gitops_pr.adapter import GitOpsPrAdapter, GitOpsPrConfig
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.feasibility_probe import (
    FindingSeverity,
    ProbeCategory,
    ProbeEvidence,
    ProbeFinding,
    ProbeResolution,
    ResolutionKind,
)
from fdai.shared.providers.remediation_pr import PublishReceipt, RemediationPr

_NOW = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
_SCOPE = "rg:example"
_CATEGORY = ProbeCategory.POLICY_GUARDRAIL


def _pr(patch: str = "disk_provisioning=attach_existing") -> RemediationPr:
    return RemediationPr(
        action_id=UUID("00000000-0000-0000-0000-000000000042"),
        idempotency_key="key",
        rule_ids=("rule",),
        title="Shadow change",
        body="Review before merging",
        patch=patch,
        patch_path="infra/example.tfvars",
    )


def _finding(severity: FindingSeverity) -> ProbeFinding:
    return ProbeFinding(
        id="private-policy-id-should-not-escape",
        category=_CATEGORY,
        severity=severity,
        title="private-finding-title",
        evidence=ProbeEvidence(source="private-source", detail="private-detail"),
        resolution=ProbeResolution(kind=ResolutionKind.MANUAL),
    )


def _report(
    *,
    scope: str = _SCOPE,
    generated_at: str | None = None,
    findings: tuple[ProbeFinding, ...] = (),
    checked: tuple[ProbeCategory, ...] = (_CATEGORY,),
    verdict: ReadinessVerdict | None = None,
    mode: Mode = Mode.SHADOW,
) -> DeploymentReadinessReport:
    return DeploymentReadinessReport(
        scope=scope,
        generated_at=generated_at or _NOW.isoformat(),
        findings=findings,
        checked_categories=checked,
        verdict=verdict
        or (
            ReadinessVerdict.BLOCKED
            if any(f.severity is FindingSeverity.BLOCKING for f in findings)
            else ReadinessVerdict.NEEDS_REVIEW
            if findings
            else ReadinessVerdict.CLEAR
        ),
        mode=mode,
    )


class _Publisher:
    def __init__(self) -> None:
        self.calls: list[RemediationPr] = []

    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        self.calls.append(pr)
        return PublishReceipt(pr_ref="owner/repo#1", already_existed=len(self.calls) > 1)


class _Refresh:
    def __init__(self, report: DeploymentReadinessReport, digest: str | None = None) -> None:
        self.report = report
        self.digest = digest
        self.calls: list[str] = []

    async def __call__(self, pr: RemediationPr) -> RefreshedPreflight:
        self.calls.append(pr.patch)
        return RefreshedPreflight(
            report=self.report,
            patch_sha256=self.digest or hashlib.sha256(pr.patch.encode("utf-8")).hexdigest(),
        )


def _guard(publisher: _Publisher, refresh: _Refresh | None) -> PreflightVerifiedPrPublisher:
    return PreflightVerifiedPrPublisher(
        publisher=publisher,
        refresh=refresh,
        expected_scope=_SCOPE,
        required_categories=frozenset({_CATEGORY}),
        clock=lambda: _NOW,
    )


async def test_clean_refresh_precedes_each_publish_including_idempotent_redelivery() -> None:
    publisher = _Publisher()
    refresh = _Refresh(_report())
    guard = _guard(publisher, refresh)
    first = await guard.publish(_pr())
    assert first.already_existed is False
    assert (await guard.publish(_pr())).already_existed is True
    assert refresh.calls == [_pr().patch, _pr().patch]
    assert len(publisher.calls) == 2

    refresh.report = _report(generated_at=(_NOW - timedelta(hours=1)).isoformat())
    with pytest.raises(PreflightPublicationHoldError) as held:
        await guard.publish(_pr())
    assert held.value.reason is PreflightHoldReason.STALE_EVIDENCE
    assert len(publisher.calls) == 2


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        (_report(scope="rg:other"), PreflightHoldReason.SCOPE_DRIFT),
        (
            _report(generated_at=(_NOW - timedelta(hours=1)).isoformat()),
            PreflightHoldReason.STALE_EVIDENCE,
        ),
        (_report(generated_at="unparseable"), PreflightHoldReason.STALE_EVIDENCE),
        (
            _report(generated_at=(_NOW + timedelta(minutes=2)).isoformat()),
            PreflightHoldReason.STALE_EVIDENCE,
        ),
        (_report(checked=()), PreflightHoldReason.INCOMPLETE_COVERAGE),
        (
            _report(findings=(_finding(FindingSeverity.BLOCKING),)),
            PreflightHoldReason.BLOCKING_FINDING,
        ),
        (
            _report(
                findings=(_finding(FindingSeverity.WARNING),),
                verdict=ReadinessVerdict.CLEAR,
            ),
            PreflightHoldReason.INVALID_REPORT,
        ),
    ],
)
async def test_invalidated_report_never_reaches_pr_publisher(
    report: DeploymentReadinessReport, expected: PreflightHoldReason
) -> None:
    publisher = _Publisher()
    with pytest.raises(PreflightPublicationHoldError) as held:
        await _guard(publisher, _Refresh(report)).publish(_pr())
    assert held.value.reason is expected
    assert publisher.calls == []
    assert held.value.to_dict() == {"decision": "human_review", "hold": expected.value}
    assert "private-" not in str(held.value)


async def test_shadow_blocker_is_not_a_publication_bypass() -> None:
    report = _report(findings=(_finding(FindingSeverity.BLOCKING),))
    assert report.blocks_deploy is False
    publisher = _Publisher()
    with pytest.raises(PreflightPublicationHoldError) as held:
        await _guard(publisher, _Refresh(report)).publish(_pr())
    assert held.value.reason is PreflightHoldReason.BLOCKING_FINDING
    assert publisher.calls == []


async def test_blocked_refresh_prevents_real_gitops_adapter_from_calling_http() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("blocked preflight reached the GitOps adapter")

    adapter = GitOpsPrAdapter(
        config=GitOpsPrConfig(owner="example", repo="iac"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        token="test-token",
    )
    guard = PreflightVerifiedPrPublisher(
        publisher=adapter,
        refresh=_Refresh(_report(findings=(_finding(FindingSeverity.BLOCKING),))),
        expected_scope=_SCOPE,
        required_categories=frozenset({_CATEGORY}),
        clock=lambda: _NOW,
    )
    with pytest.raises(PreflightPublicationHoldError) as held:
        await guard.publish(_pr())
    assert held.value.reason is PreflightHoldReason.BLOCKING_FINDING
    assert requests == []


async def test_patch_digest_must_bind_exact_candidate() -> None:
    publisher = _Publisher()
    refresh = _Refresh(_report(), digest=hashlib.sha256(b"old patch").hexdigest())
    with pytest.raises(PreflightPublicationHoldError) as held:
        await _guard(publisher, refresh).publish(_pr())
    assert held.value.reason is PreflightHoldReason.PATCH_DRIFT
    assert publisher.calls == []


async def test_unavailable_refresh_never_falls_back_to_publication() -> None:
    publisher = _Publisher()
    with pytest.raises(PreflightPublicationHoldError) as held:
        await _guard(publisher, None).publish(_pr())
    assert held.value.reason is PreflightHoldReason.UNAVAILABLE
    assert publisher.calls == []

    async def unavailable(_pr: RemediationPr) -> RefreshedPreflight:
        raise RuntimeError("private-credential-value")

    guard = PreflightVerifiedPrPublisher(
        publisher=publisher,
        refresh=unavailable,
        expected_scope=_SCOPE,
        required_categories=frozenset({_CATEGORY}),
        clock=lambda: _NOW,
    )
    with pytest.raises(PreflightPublicationHoldError) as held:
        await guard.publish(_pr())
    assert held.value.reason is PreflightHoldReason.UNAVAILABLE
    assert "private-" not in str(held.value)
    assert publisher.calls == []


async def test_warning_only_report_can_publish_a_draft_without_approval() -> None:
    publisher = _Publisher()
    receipt = await _guard(
        publisher, _Refresh(_report(findings=(_finding(FindingSeverity.WARNING),)))
    ).publish(_pr())
    assert receipt.pr_ref == "owner/repo#1"
    assert publisher.calls[0].mode is Mode.SHADOW


def test_invalid_refresh_configuration_fails_at_binding() -> None:
    publisher = _Publisher()
    with pytest.raises(ValueError, match="required_categories"):
        PreflightVerifiedPrPublisher(
            publisher=publisher,
            refresh=None,
            expected_scope=_SCOPE,
            required_categories=frozenset(),
        )
