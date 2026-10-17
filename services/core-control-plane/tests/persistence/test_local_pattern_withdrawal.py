"""Source-owner withdrawals across LOCAL intake awaits, not deployed qualification."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from fdai.core.case_history.derived import CaseHistoryProjectionStore
from fdai.core.tiers.t1_lightweight.retained_pattern_bindings import RetainedPatternQualification
from fdai.core.tiers.t1_lightweight.retained_pattern_lease import RetainedPatternLeaseEvidence
from fdai.delivery.persistence.local_pattern_owner import (
    LOCAL_VENUE,
    LocalPatternArtifactStore,
    owner_key,
)
from fdai.delivery.persistence.local_pattern_validation import artifact_key
from fdai.delivery.persistence.state_store_decision_evidence import decision_evidence_state_key

from tests.core.tiers.t1_lightweight.test_contextual_reuse import _event
from tests.core.tiers.t1_lightweight.test_retained_patterns import NOW
from tests.persistence.test_local_pattern_qualification import local_case as local_case
from tests.persistence.test_postgres_state_store import saga_database as saga_database

_STAGES = (
    "request",
    "read:1",
    "projection:2",
    "resolve",
    "statistics:1",
    "verify:1",
    "statistics:2",
    "read:2",
    "verify:2",
    "lease",
)
_WITHDRAWALS = (
    "negative_artifact",
    "negative_corruption",
    "negative_metadata",
    "projection",
    "measurement",
    "principal",
    "authentication_request",
    "reuse_policy",
    "read_admission",
    "reuse_admission",
    "action",
)


def _after_await(
    monkeypatch: pytest.MonkeyPatch,
    case: tuple[Any, ...],
    callback: Callable[[str], Awaitable[None]],
) -> None:
    _, _, owner, _, source, qualifier, *_ = case

    def wrap(target: Any, attribute: str, stage: str, *, numbered: bool = False) -> None:
        original = getattr(target, attribute)
        count = 0

        async def call(*args: Any, **kwargs: Any) -> Any:
            nonlocal count
            value = await original(*args, **kwargs)
            count += 1
            await callback(f"{stage}:{count}" if numbered else stage)
            return value

        monkeypatch.setattr(target, attribute, call)

    wrap(source, "_request_source", "request")
    wrap(source, "_read", "read", numbered=True)
    wrap(CaseHistoryProjectionStore, "pattern_records", "projection", numbered=True)
    wrap(source, "_resolve", "resolve")
    wrap(source, "_statistics_source", "statistics", numbered=True)
    wrap(owner, "verify", "verify", numbered=True)

    class BeforeLease:
        @asynccontextmanager
        async def lease(
            self, request: RetainedPatternQualification
        ) -> AsyncIterator[RetainedPatternLeaseEvidence | None]:
            await callback("lease")
            async with qualifier.lease(request) as evidence:
                yield evidence

    monkeypatch.setattr(source, "_leased_qualifier", BeforeLease())


async def _withdraw(case: tuple[Any, ...], kind: str) -> None:
    _, store, owner, h, _, _, records, read_lookup, reuse_lookup, observed = case
    context = h.action.operational_case
    assert context is not None and h.statistics is not None
    if kind == "negative_artifact":
        await LocalPatternArtifactStore(store=store, venue=LOCAL_VENUE).delete(
            records[-1].storage_ref
        )
    elif kind == "negative_corruption":
        key = artifact_key(records[-1].storage_ref)
        raw = dict(await store.read_state(key))
        raw["content_base64"] = "e30="
        await store.write_state(key, raw)
    elif kind == "negative_metadata":
        await store.delete_state("case-history:latest:" + records[-1].case_id)
    elif kind == "projection":
        await store.delete_state("case-history-derived:v1:" + "f" * 64)
    elif kind == "measurement":
        await owner.retain_statistics(h.statistics, authorized=False)
    elif kind in {"principal", "authentication_request"}:
        principal = h.request.context
        if kind == "authentication_request":
            principal = principal.model_copy(
                update={"authentication_request_ref": "substituted-request"}
            )
        await owner.retain_principal(
            context=principal,
            scope="f" * 64,
            purpose=h.request.purpose,
            allowed=kind != "principal",
            valid_until=NOW + timedelta(minutes=3),
        )
    elif kind == "reuse_policy":
        await owner.retain_reuse(
            event=_event(),
            action=h.action,
            context=context,
            verification=replace(observed, policy_allowed=False),
        )
    elif kind == "action":
        await store.delete_state(owner_key("action", h.action.action_type))
    elif kind in {"read_admission", "reuse_admission"}:
        await store.delete_state(
            decision_evidence_state_key(
                **(read_lookup if kind == "read_admission" else reuse_lookup)
            )
        )
    else:
        raise AssertionError("unknown source-owner withdrawal")


@pytest.mark.parametrize("stage", _STAGES)
@pytest.mark.parametrize("kind", _WITHDRAWALS)
async def test_each_awaited_intake_boundary_rejects_owner_withdrawal(
    local_case: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, stage: str, kind: str
) -> None:
    _, _, owner, h, *_ = local_case
    baseline = await h.tier(verifier=owner, compare=False).evaluate(event=_event())
    applied = False

    async def mutate(current: str) -> None:
        nonlocal applied
        if current == stage and not applied:
            applied = True
            await _withdraw(local_case, kind)

    _after_await(monkeypatch, local_case, mutate)
    result = await h.tier(verifier=owner).evaluate(event=_event())
    assert applied, f"intake did not reach the tested boundary: {stage}"
    comparison = result.retained_pattern_comparison
    assert comparison is not None and comparison.challenger_match is None
    assert comparison.stop_reason is not None
    assert comparison.final_lease is None and comparison.final_qualification is None
    assert (
        replace(result, retained_pattern_comparison=None, eligibility_comparison=None) == baseline
    )
    assert not comparison.audit_mapping()["operationally_proven"]


@pytest.mark.parametrize("stage", _STAGES)
@pytest.mark.parametrize("cancel", [False, True])
async def test_each_awaited_boundary_preserves_deadline_and_cancellation(
    local_case: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, stage: str, cancel: bool
) -> None:
    _, store, owner, h, _, _, records, *_ = local_case
    entered = asyncio.Event()

    async def pause(current: str) -> None:
        if current == stage:
            entered.set()
            await asyncio.Event().wait()

    _after_await(monkeypatch, local_case, pause)
    task = asyncio.create_task(
        h.tier(verifier=owner, timeout=5 if cancel else 0.3).evaluate(event=_event())
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await task
            assert result.reason == "no_neighbour_found"
            assert result.retained_pattern_comparison.stop_reason == "t1_deadline_exceeded"
        assert await asyncio.wait_for(
            store.delete_state("case-history:latest:" + records[-1].case_id), timeout=2
        )
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
