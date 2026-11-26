"""RecordingRemediationPrPublisher - invariant tests for the in-memory fake."""

from __future__ import annotations

from uuid import UUID

import pytest
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import RemediationPr
from fdai.shared.providers.testing.remediation_pr import (
    RecordingRemediationPrPublisher,
)


def _pr(
    *,
    idempotency_key: str = "k1",
    mode: Mode = Mode.SHADOW,
    labels: tuple[str, ...] = ("shadow",),
) -> RemediationPr:
    return RemediationPr(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key=idempotency_key,
        rule_ids=("r1",),
        title="t",
        body="b",
        patch="p",
        patch_path="infra/x.tf",
        labels=labels,
        mode=mode,
    )


@pytest.mark.asyncio
async def test_first_publish_assigns_incrementing_pr_ref() -> None:
    pub = RecordingRemediationPrPublisher()
    r1 = await pub.publish(_pr(idempotency_key="k1"))
    r2 = await pub.publish(_pr(idempotency_key="k2"))
    assert r1.pr_ref == "pr-1"
    assert r2.pr_ref == "pr-2"
    assert not r1.already_existed and not r2.already_existed


@pytest.mark.asyncio
async def test_duplicate_key_returns_already_existed() -> None:
    pub = RecordingRemediationPrPublisher()
    first = await pub.publish(_pr(idempotency_key="dup"))
    second = await pub.publish(_pr(idempotency_key="dup"))
    assert first.pr_ref == second.pr_ref
    assert second.already_existed is True
    # Only one record.
    assert len(pub.records) == 1


@pytest.mark.asyncio
async def test_enforce_without_enforce_label_is_rejected() -> None:
    pub = RecordingRemediationPrPublisher()
    with pytest.raises(ValueError, match="enforce"):
        await pub.publish(_pr(mode=Mode.ENFORCE, labels=("shadow",)))


@pytest.mark.asyncio
async def test_enforce_with_enforce_label_is_accepted() -> None:
    pub = RecordingRemediationPrPublisher()
    receipt = await pub.publish(_pr(mode=Mode.ENFORCE, labels=("shadow", "enforce")))
    assert receipt.pr_ref == "pr-1"


@pytest.mark.asyncio
async def test_find_returns_recorded_pr_by_idempotency_key() -> None:
    pub = RecordingRemediationPrPublisher()
    await pub.publish(_pr(idempotency_key="k1"))
    await pub.publish(_pr(idempotency_key="k2"))
    assert pub.find("k1") is not None
    assert pub.find("k2") is not None
    assert pub.find("nope") is None
