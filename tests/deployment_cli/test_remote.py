"""Remote exact-plan integrity guard tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from fdai.deployment_cli.remote import (
    DeploymentPlanContext,
    DeploymentPlanRecord,
    DeploymentSubmission,
    PlanStatus,
    RemoteDeploymentError,
    RemoteDeploymentService,
    deployment_context_digest,
    validate_exact_plan,
)

_NOW = datetime(2026, 7, 17, 3, 0, tzinfo=UTC)
_TENANT = UUID("00000000-0000-0000-0000-000000000001")
_SUBSCRIPTION = UUID("00000000-0000-0000-0000-000000000002")


def _context() -> DeploymentPlanContext:
    return DeploymentPlanContext(
        tenant_id=_TENANT,
        subscription_id=_SUBSCRIPTION,
        environment="dev",
        bundle_digest="a" * 64,
        commit_sha="b" * 40,
        backend_ref="backend:dev",
        runner_ref="runner:private",
    )


def _record(**overrides: object) -> DeploymentPlanRecord:
    values: dict[str, object] = {
        "plan_id": "plan-1",
        "plan_digest": "c" * 64,
        "context": _context(),
        "created_at": _NOW,
        "expires_at": _NOW + timedelta(hours=1),
        "status": PlanStatus.READY,
        "workflow_url": "https://example.com/workflows/1",
    }
    values.update(overrides)
    return DeploymentPlanRecord(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("record", "message"),
    (
        (_record(status=PlanStatus.APPLIED), "not ready"),
        (_record(expires_at=_NOW + timedelta(seconds=1)), "expired"),
        (_record(preflight_blocks=True), "preflight"),
        (_record(runner_available=False), "runner"),
    ),
)
def test_apply_guard_rejects_non_ready_contexts(
    record: DeploymentPlanRecord,
    message: str,
) -> None:
    at = record.expires_at if message == "expired" else _NOW
    with pytest.raises(RemoteDeploymentError, match=message):
        validate_exact_plan(record, expected_context=_context(), now=at)


def test_apply_guard_rejects_any_context_mismatch() -> None:
    expected = replace(_context(), runner_ref="runner:other")
    with pytest.raises(RemoteDeploymentError, match="context"):
        validate_exact_plan(_record(), expected_context=expected, now=_NOW)


def test_apply_guard_rejects_feature_topology_mismatch() -> None:
    expected = replace(_context(), deploy_operator_api=True)

    with pytest.raises(RemoteDeploymentError, match="context"):
        validate_exact_plan(_record(), expected_context=expected, now=_NOW)


def test_context_digest_binds_every_feature_flag() -> None:
    baseline = deployment_context_digest(_context())

    assert baseline != deployment_context_digest(replace(_context(), deploy_console=True))
    assert baseline != deployment_context_digest(replace(_context(), deploy_operator_api=True))
    assert baseline != deployment_context_digest(
        replace(_context(), deploy_dev_operations_gateway=True)
    )
    assert baseline != deployment_context_digest(
        replace(_context(), deploy_document_ingestion=True)
    )


def test_apply_guard_accepts_matching_digest_only_metadata() -> None:
    record = _record(
        context=None,
        context_digest=deployment_context_digest(_context()),
    )

    validate_exact_plan(record, expected_context=_context(), now=_NOW)


def test_apply_guard_rejects_mismatched_digest_only_metadata() -> None:
    record = _record(context=None, context_digest="d" * 64)

    with pytest.raises(RemoteDeploymentError, match="context"):
        validate_exact_plan(record, expected_context=_context(), now=_NOW)


def test_verification_resume_requires_matching_applying_claim() -> None:
    validate_exact_plan(
        _record(status=PlanStatus.APPLYING),
        expected_context=_context(),
        now=_NOW,
        resume_verification=True,
    )

    with pytest.raises(RemoteDeploymentError, match="verification resume"):
        validate_exact_plan(
            _record(status=PlanStatus.READY),
            expected_context=_context(),
            now=_NOW,
            resume_verification=True,
        )


class _Transport:
    def __init__(self, record: DeploymentPlanRecord) -> None:
        self.record = record
        self.apply_calls: list[tuple[str, str, DeploymentPlanContext, bool]] = []

    async def submit_plan(self, context: DeploymentPlanContext) -> DeploymentSubmission:
        return DeploymentSubmission("submission-plan", "https://example.com/workflows/plan")

    async def get_plan(self, plan_id: str) -> DeploymentPlanRecord:
        assert plan_id == self.record.plan_id
        return self.record

    async def submit_apply(
        self,
        *,
        plan_id: str,
        plan_digest: str,
        context: DeploymentPlanContext,
        resume_verification: bool = False,
    ) -> DeploymentSubmission:
        self.apply_calls.append((plan_id, plan_digest, context, resume_verification))
        return DeploymentSubmission("submission-apply", "https://example.com/workflows/apply")


async def test_service_submits_stored_digest_and_context_only_after_guard() -> None:
    transport = _Transport(_record())
    service = RemoteDeploymentService(transport=transport)

    result = await service.submit_apply(
        plan_id="plan-1",
        expected_context=_context(),
        now=_NOW,
    )

    assert result.submission_id == "submission-apply"
    assert transport.apply_calls == [("plan-1", "c" * 64, _context(), False)]


async def test_service_resumes_verification_without_requiring_ready_status() -> None:
    transport = _Transport(_record(status=PlanStatus.APPLYING))
    service = RemoteDeploymentService(transport=transport)

    result = await service.submit_apply(
        plan_id="plan-1",
        expected_context=_context(),
        now=_NOW,
        resume_verification=True,
    )

    assert result.submission_id == "submission-apply"
    assert transport.apply_calls == [("plan-1", "c" * 64, _context(), True)]


async def test_service_never_submits_apply_when_guard_fails() -> None:
    transport = _Transport(_record(preflight_blocks=True))
    service = RemoteDeploymentService(transport=transport)

    with pytest.raises(RemoteDeploymentError, match="preflight"):
        await service.submit_apply(
            plan_id="plan-1",
            expected_context=_context(),
            now=_NOW,
        )

    assert transport.apply_calls == []
