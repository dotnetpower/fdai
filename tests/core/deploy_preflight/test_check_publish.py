"""Wave P.3 - PreflightCheckPublisher seam + publish_preflight_check verb."""

from __future__ import annotations

import pytest

from aiopspilot.core.deploy_preflight import (
    DeploymentReadinessReport,
    PreflightCheckOutcome,
    ReadinessVerdict,
    publish_preflight_check,
)
from aiopspilot.shared.contracts.models import Mode
from aiopspilot.shared.providers.preflight_check import (
    PreflightCheck,
    PreflightCheckPublishError,
    PreflightCheckReceipt,
)
from aiopspilot.shared.providers.testing.preflight_check import (
    InMemoryPreflightCheckPublisher,
)


def _report(*, mode: Mode = Mode.SHADOW) -> DeploymentReadinessReport:
    return DeploymentReadinessReport(
        scope="rg/example",
        generated_at="2026-07-07T00:00:00Z",
        mode=mode,
        verdict=ReadinessVerdict.CLEAR,
        findings=(),
    )


# ---------------------------------------------------------------------------
# Fake publisher contract
# ---------------------------------------------------------------------------


async def test_fake_publish_records_and_returns_receipt() -> None:
    pub = InMemoryPreflightCheckPublisher()
    check = PreflightCheck(
        pr_ref="owner/repo#1",
        check_key="k-1",
        report=_report(),
    )
    receipt = await pub.publish(check)
    assert isinstance(receipt, PreflightCheckReceipt)
    assert receipt.already_existed is False
    assert receipt.check_ref.startswith("preflight-check-")
    assert pub.records == (check,)


async def test_fake_publish_is_idempotent_by_check_key() -> None:
    pub = InMemoryPreflightCheckPublisher()
    check = PreflightCheck(
        pr_ref="owner/repo#1",
        check_key="k-1",
        report=_report(),
    )
    r1 = await pub.publish(check)
    r2 = await pub.publish(check)
    assert r1.check_ref == r2.check_ref
    assert r2.already_existed is True
    assert len(pub.records) == 1  # recorded only once


async def test_fake_next_error_raises_once() -> None:
    pub = InMemoryPreflightCheckPublisher()
    pub.next_error(PreflightCheckPublishError("checks-api 502"))
    check = PreflightCheck(pr_ref="p", check_key="k-1", report=_report())
    with pytest.raises(PreflightCheckPublishError):
        await pub.publish(check)
    # Recovers.
    receipt = await pub.publish(check)
    assert receipt.already_existed is False


def test_fake_find_helper() -> None:
    pub = InMemoryPreflightCheckPublisher()
    assert pub.find("missing") is None


async def test_fake_find_helper_returns_recorded_check() -> None:
    """`find()` returns the recorded check when the key matches."""
    pub = InMemoryPreflightCheckPublisher()
    check = PreflightCheck(pr_ref="pr-42", check_key="k-found", report=_report())
    await pub.publish(check)
    got = pub.find("k-found")
    assert got is not None
    assert got.check_key == "k-found"
    assert got.pr_ref == "pr-42"


# ---------------------------------------------------------------------------
# publish_preflight_check orchestrator
# ---------------------------------------------------------------------------


async def test_publish_returns_posted_outcome() -> None:
    pub = InMemoryPreflightCheckPublisher()
    result = await publish_preflight_check(
        publisher=pub,
        pr_ref="owner/repo#1",
        check_key="k-1",
        report=_report(),
        metadata={"correlation_id": "abc"},
    )
    assert result.outcome is PreflightCheckOutcome.POSTED
    assert result.receipt is not None
    assert result.receipt.check_ref.startswith("preflight-check-")
    assert result.error_message is None
    assert result.check is not None
    assert result.check.metadata == {"correlation_id": "abc"}


async def test_publish_idempotent_returns_already_posted() -> None:
    pub = InMemoryPreflightCheckPublisher()
    kwargs = dict(
        publisher=pub,
        pr_ref="owner/repo#1",
        check_key="k-1",
        report=_report(),
    )
    first = await publish_preflight_check(**kwargs)  # type: ignore[arg-type]
    second = await publish_preflight_check(**kwargs)  # type: ignore[arg-type]
    assert first.outcome is PreflightCheckOutcome.POSTED
    assert second.outcome is PreflightCheckOutcome.ALREADY_POSTED
    assert second.receipt is not None
    assert second.receipt.check_ref == first.receipt.check_ref  # type: ignore[union-attr]


async def test_publish_abstains_on_publisher_error() -> None:
    pub = InMemoryPreflightCheckPublisher()
    pub.next_error(PreflightCheckPublishError("checks-api 502"))
    result = await publish_preflight_check(
        publisher=pub,
        pr_ref="p",
        check_key="k-1",
        report=_report(),
    )
    assert result.outcome is PreflightCheckOutcome.PUBLISH_ERROR
    assert result.receipt is None
    assert result.error_message == "checks-api 502"
    assert result.check is not None


@pytest.mark.parametrize(
    "field, value, missing",
    [
        ("pr_ref", "", "pr_ref"),
        ("check_key", "", "check_key"),
    ],
)
async def test_publish_rejects_empty_required_args(field: str, value: str, missing: str) -> None:
    pub = InMemoryPreflightCheckPublisher()
    kwargs = {
        "publisher": pub,
        "pr_ref": "p",
        "check_key": "k",
        "report": _report(),
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=missing):
        await publish_preflight_check(**kwargs)  # type: ignore[arg-type]


async def test_shadow_and_enforce_reports_both_publish() -> None:
    """The publisher accepts any mode; the adapter labels as advisory
    when the report ran in shadow. Both variants exercise the same path."""

    pub = InMemoryPreflightCheckPublisher()
    for i, mode in enumerate([Mode.SHADOW, Mode.ENFORCE]):
        result = await publish_preflight_check(
            publisher=pub,
            pr_ref="p",
            check_key=f"k-{i}",
            report=_report(mode=mode),
        )
        assert result.outcome is PreflightCheckOutcome.POSTED
    # Two distinct posts recorded.
    assert len(pub.records) == 2


def test_result_dataclass_defaults() -> None:
    from aiopspilot.core.deploy_preflight.check_publish import PreflightCheckResult

    r = PreflightCheckResult(outcome=PreflightCheckOutcome.POSTED)
    assert r.receipt is None
    assert r.error_message is None
    assert r.check is None
