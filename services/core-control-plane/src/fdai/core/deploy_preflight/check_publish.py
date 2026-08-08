"""Publish a :class:`DeploymentReadinessReport` onto an infrastructure PR.

Wave P.3 - the thin orchestrator that turns the internal Preflight
report into a
:class:`~fdai.shared.providers.preflight_check.PreflightCheck`
and hands it to an injected publisher. Same shape as
:mod:`fdai.core.assurance_twin.review` so the two flows stay
consistent.

Fails-closed: a publisher raise -> :class:`PreflightCheckOutcome.PUBLISH_ERROR`;
the caller treats it as "preflight has no opinion" and does NOT retry
blindly - retry policy is the delivery adapter's concern.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from fdai.core.deploy_preflight.report import DeploymentReadinessReport
from fdai.shared.providers.preflight_check import (
    PreflightCheck,
    PreflightCheckPublisher,
    PreflightCheckPublishError,
    PreflightCheckReceipt,
)


class PreflightCheckOutcome(StrEnum):
    """Truthful outcome of one Preflight-check publish attempt."""

    POSTED = "posted"
    ALREADY_POSTED = "already_posted"
    PUBLISH_ERROR = "publish_error"


@dataclass(frozen=True, slots=True)
class PreflightCheckResult:
    """Result of :func:`publish_preflight_check` - side-effect-free view."""

    outcome: PreflightCheckOutcome
    receipt: PreflightCheckReceipt | None = None
    error_message: str | None = None
    check: PreflightCheck | None = None


async def publish_preflight_check(
    *,
    publisher: PreflightCheckPublisher,
    pr_ref: str,
    check_key: str,
    report: DeploymentReadinessReport,
    metadata: Mapping[str, str] | None = None,
) -> PreflightCheckResult:
    """Publish one Preflight report through ``publisher``.

    Never raises: on any :class:`PreflightCheckPublishError` the
    outcome is :attr:`PreflightCheckOutcome.PUBLISH_ERROR` and the
    caller decides whether to escalate / drop / retry on a later PR
    push. Input validation on the required strings.
    """

    if not pr_ref:
        raise ValueError("pr_ref MUST be non-empty")
    if not check_key:
        raise ValueError("check_key MUST be non-empty")

    check = PreflightCheck(
        pr_ref=pr_ref,
        check_key=check_key,
        report=report,
        metadata=dict(metadata or {}),
    )

    try:
        receipt = await publisher.publish(check)
    except PreflightCheckPublishError as exc:
        return PreflightCheckResult(
            outcome=PreflightCheckOutcome.PUBLISH_ERROR,
            error_message=str(exc),
            check=check,
        )

    outcome = (
        PreflightCheckOutcome.ALREADY_POSTED
        if receipt.already_existed
        else PreflightCheckOutcome.POSTED
    )
    return PreflightCheckResult(outcome=outcome, receipt=receipt, check=check)


__all__ = [
    "PreflightCheckOutcome",
    "PreflightCheckResult",
    "publish_preflight_check",
]
