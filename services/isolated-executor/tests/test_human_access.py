"""Synthetic isolated membership dispatch; no real identity, Graph or application database."""

from __future__ import annotations

import asyncio
import copy
import runpy
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fdai_executor_service.adapters.entra_membership import EntraMembershipClient
from fdai_executor_service.effect_executor import ServiceDirectApiEffectExecutor
from fdai_executor_service.effect_safety import build_direct_api_request
from fdai_executor_service.human_access import IsolatedHumanAccessExecutor
from fdai_service_contracts.executor import (
    DirectApiError,
    DirectApiOutcome,
    DirectApiPreconditionError,
    IdentityToken,
    Mode,
)
from fdai_service_contracts.executor_models import Action
from fdai_service_contracts.human_access_execution import (
    HumanAccessCurrentEvidence,
    HumanAccessExecutionMaterial,
    canonical_human_access_json,
)
from fdai_service_contracts.human_access_recovery import (
    HumanAccessInverseBinding,
    mutation_evidence_digest,
)

_support = runpy.run_path(
    str(
        Path(__file__).resolve().parents[3]
        / "packages/service-contracts/tests/test_human_access_execution.py"
    )
)
AT, material, evidence = _support["AT"], _support["material"], _support["evidence"]


class Store:
    def __init__(self):
        self.rows = {}
        self.audit = []

    async def read_state(self, key):
        return copy.deepcopy(self.rows.get(key))

    async def write_state_with_audit_if_absent(self, key, value, audit_entry):
        if key in self.rows:
            return False
        self.rows[key] = copy.deepcopy(value)
        self.audit.append(copy.deepcopy(audit_entry))
        return True

    async def append_audit_entry(self, entry):
        self.audit.append(copy.deepcopy(entry))


@pytest.fixture
async def fixture():
    value = material()
    now = {"at": AT + timedelta(seconds=10)}
    requests = []
    mutable = {"membership": False, "write_status": 204, "source_status": 200}

    async def graph(request):
        requests.append(request)
        if request.method in {"POST", "DELETE"}:
            if mutable["write_status"] == 204:
                mutable["membership"] = request.method == "POST"
            return httpx.Response(mutable["write_status"])
        if mutable["source_status"] != 200:
            return httpx.Response(mutable["source_status"])
        if "/users/" in request.url.path:
            return httpx.Response(200, json={"id": value.subject_id, "accountEnabled": True})
        if "/members/" in request.url.path:
            return (
                httpx.Response(200, json={"id": value.subject_id})
                if mutable["membership"]
                else httpx.Response(404)
            )
        return httpx.Response(
            200,
            json={
                "id": value.group_id,
                "securityEnabled": True,
                "groupTypes": [],
                "isAssignableToRole": False,
            },
        )

    source = SimpleNamespace(
        material_for=AsyncMock(return_value=value),
        current=AsyncMock(side_effect=lambda m: evidence(m)),
    )
    identity = SimpleNamespace(
        get_token=AsyncMock(
            return_value=IdentityToken(
                "synthetic-placeholder",
                AT + timedelta(minutes=10),
                "https://graph.microsoft.com/.default",
            )
        )
    )
    store = Store()
    async with httpx.AsyncClient(transport=httpx.MockTransport(graph)) as client:
        adapter = IsolatedHumanAccessExecutor(
            source,
            EntraMembershipClient(client, identity, frozenset({value.group_id}), lambda: now["at"]),
            store,
            lambda: now["at"],
        )
        request = build_direct_api_request(value.action(), deadline_at=AT + timedelta(seconds=120))
        yield SimpleNamespace(
            adapter=adapter,
            material=value,
            now=now,
            requests=requests,
            mutable=mutable,
            source=source,
            identity=identity,
            store=store,
            request=request,
        )


async def test_shadow_has_no_token_source_or_provider_io(fixture):
    f = fixture
    receipt = await f.adapter.execute(replace(f.request, mode=Mode.SHADOW))
    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert not f.requests and not f.store.rows
    f.identity.get_token.assert_not_awaited()
    f.source.material_for.assert_not_awaited()


async def test_acknowledged_grant_is_not_independent_effect_and_retry_does_not_write_again(fixture):
    f = fixture
    receipt = await f.adapter.execute(f.request)
    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert (
        receipt.detail == "membership dispatch recorded; independent effect observation is pending"
    )
    assert [r.method for r in f.requests] == ["GET", "GET", "GET", "POST"]
    assert [entry["action_kind"] for entry in f.store.audit] == [
        "human_access.dispatch.intent",
        "human_access.dispatch.acknowledged",
    ]
    assert all(not key.startswith("human_assignment:") for key in f.store.rows)
    restarted = replace(f.adapter)
    assert await restarted.execute(f.request) == receipt
    assert len(f.requests) == 4


async def test_already_satisfied_membership_is_not_owned_for_rollback(fixture):
    f = fixture
    f.mutable["membership"] = True
    receipt = await f.adapter.execute(f.request)
    assert receipt.outcome is DirectApiOutcome.ALREADY_APPLIED
    assert all(request.method == "GET" for request in f.requests)
    result = next(row for key, row in f.store.rows.items() if key.endswith(":result"))
    assert result["owned_mutation"] is False


@pytest.mark.parametrize("status", [301, 401, 403, 429, 503])
async def test_provider_refusal_is_not_retried_or_reinterpreted_as_membership(status, fixture):
    f = fixture
    f.mutable["source_status"] = status
    with pytest.raises(DirectApiError):
        await f.adapter.execute(f.request)
    assert len(f.requests) == 1 and not f.store.rows


async def test_promotion_changes_during_token_read_blocks_all_graph_calls(fixture):
    f = fixture

    def revoke(_audience):
        f.source.current.side_effect = lambda value: HumanAccessCurrentEvidence.model_validate(
            {**evidence(value).model_dump(), "promotion_mode": "shadow"}
        )
        return IdentityToken(
            "synthetic-placeholder",
            AT + timedelta(minutes=10),
            "https://graph.microsoft.com/.default",
        )

    f.identity.get_token.side_effect = revoke
    with pytest.raises(DirectApiPreconditionError, match="promotion_changed"):
        await f.adapter.execute(f.request)
    assert not f.requests


async def test_expiry_after_current_source_io_prevents_token_and_mutation(fixture):
    f = fixture

    def expire(value):
        f.now["at"] = AT + timedelta(seconds=120)
        return evidence(value)

    f.source.current.side_effect = expire
    with pytest.raises(DirectApiPreconditionError):
        await f.adapter.execute(f.request)
    assert not f.requests
    f.identity.get_token.assert_not_awaited()


async def test_cancellation_after_intent_retains_unknown_and_never_repeats_mutation(fixture):
    f = fixture
    original = f.adapter.graph.dispatch
    f.adapter = replace(
        f.adapter,
        graph=SimpleNamespace(
            inspect=f.adapter.graph.inspect, dispatch=AsyncMock(side_effect=asyncio.CancelledError)
        ),
    )
    with pytest.raises(asyncio.CancelledError):
        await f.adapter.execute(f.request)
    assert len(f.store.rows) == 1 and next(iter(f.store.rows)).endswith(":intent")
    f.adapter = replace(
        f.adapter, graph=SimpleNamespace(inspect=f.adapter.graph.inspect, dispatch=original)
    )
    with pytest.raises(DirectApiPreconditionError, match="unobserved"):
        await f.adapter.execute(f.request)
    assert [r.method for r in f.requests] == ["GET", "GET", "GET"]


async def test_acknowledgement_audit_failure_keeps_unknown_not_success(fixture):
    f = fixture
    write = f.store.write_state_with_audit_if_absent

    async def fail_result(key, value, audit):
        if key.endswith(":result"):
            raise RuntimeError("synthetic audit failure")
        return await write(key, value, audit)

    f.store.write_state_with_audit_if_absent = fail_result
    with pytest.raises(RuntimeError, match="audit"):
        await f.adapter.execute(f.request)
    assert f.mutable["membership"] is True
    assert await f.adapter.operation_status(f.request) is None
    with pytest.raises(DirectApiPreconditionError, match="unobserved"):
        await f.adapter.execute(f.request)
    assert sum(r.method == "POST" for r in f.requests) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("resource_ref", "human-assignment:case:example"),
        ("arguments", {"case_id": "case:other", "expected_revision": 5}),
        ("idempotency_key", "key:other"),
    ],
)
async def test_original_action_identity_cannot_be_rewritten_at_provider_boundary(
    field, value, fixture
):
    f = fixture
    with pytest.raises(DirectApiPreconditionError, match="original Action"):
        await f.adapter.execute(replace(f.request, **{field: value}))
    assert not f.requests


async def test_two_cases_with_opposite_operations_share_one_effect_lock(fixture):
    f = fixture
    first = f.material
    second_data = material(revoke=True).model_dump()
    second_action = material(revoke=True).action().model_dump(mode="json")
    second_action["action_id"] = "00000000-0000-0000-0000-000000000031"
    second_action["idempotency_key"] = "key:second"
    second_action["params"]["case_id"] = "case:second"
    second_data["action_json"] = canonical_human_access_json(second_action)
    second = HumanAccessExecutionMaterial.model_validate(second_data)
    by_id = {str(item.action().action_id): item for item in (first, second)}
    f.source.material_for.side_effect = lambda *, action_id, action_digest: by_id[str(action_id)]
    entered = []
    locks = {}

    @asynccontextmanager
    async def acquire(key):
        async with locks.setdefault(key, asyncio.Lock()):
            entered.append(key)
            yield

    service = ServiceDirectApiEffectExecutor(
        executor=f.adapter,
        audit_store=f.store,
        resource_lock=SimpleNamespace(acquire=acquire),
        idempotency=None,
        allow_enforce=True,
        clock=lambda: f.now["at"],
    )
    results = await asyncio.gather(
        *(
            service.execute(action=value.action(), deadline_at=AT + timedelta(seconds=120))
            for value in (first, second)
        )
    )
    assert [result.outcome.value for result in results] == ["dispatched", "dispatched"]
    target_locks = [key for key in entered if key.startswith("fdai:resource:")]
    assert target_locks == [first.membership_plan().membership_lock_key] * 2
    assert [r.method for r in f.requests if r.method != "GET"] == ["POST", "DELETE"]


def _reviewed_inverse(f):
    """Construct explicit new human approval evidence over the actual retained original attempt."""
    original = f.material
    intent = next(row for key, row in f.store.rows.items() if key.endswith(":intent"))
    result = next(row for key, row in f.store.rows.items() if key.endswith(":result"))
    f.now["at"] += timedelta(seconds=1)
    inverse = HumanAccessInverseBinding(
        original_action_id=original.action().action_id,
        original_action_digest=original.action_digest,
        original_material_digest=original.digest,
        original_idempotency_key=original.action().idempotency_key,
        original_target_digest=original.membership_plan().target_digest,
        original_attempt_digest=mutation_evidence_digest(intent, result),
        original_before_membership=intent["before_membership"],
        original_receipt_ref=result["receipt_ref"],
        original_completed_at=result["recorded_at"],
        target_fence_digest="sha256:" + "a" * 64,
        target_fence_generation=1,
        demand_digest="b" * 64,
    )
    data = original.action().model_dump(mode="json")
    restore = inverse.original_before_membership
    data.update(
        action_id=str(UUID(int=66)),
        event_id=str(UUID(int=67)),
        idempotency_key="inverse:reviewed",
        action_type="ops.apply-human-access" if restore else "ops.revoke-human-access",
        operation="attach" if restore else "detach",
        created_at=f.now["at"].isoformat(),
        params={
            "case_id": original.action().params["case_id"],
            "expected_revision": 5,
            "recovery_of": str(original.action().action_id),
        },
    )
    data["action_type_ref"]["name"] = data["action_type"]
    value = HumanAccessExecutionMaterial.model_validate(
        {
            **original.model_dump(),
            "action_json": canonical_human_access_json(
                Action.model_validate(data).model_dump(mode="json")
            ),
            "inverse": inverse,
            "approval_ids": ["approval:inverse"],
            "recorded_at": f.now["at"],
            "expires_at": f.now["at"] + timedelta(minutes=5),
        }
    )

    def current(m):
        record = evidence(m).model_dump()
        record.update(
            current_case_state="degraded",
            observed_at=f.now["at"],
            expires_at=f.now["at"] + timedelta(seconds=30),
        )
        for approval in record["approvals"]:
            approval["decided_at"] = f.now["at"]
        return HumanAccessCurrentEvidence.model_validate(record)

    f.source.current.side_effect = current
    f.source.material_for.side_effect = None
    f.source.material_for.return_value = value
    return value, build_direct_api_request(
        value.action(), deadline_at=f.now["at"] + timedelta(seconds=120)
    )


@pytest.mark.parametrize("revoke", [False, True])
async def test_reviewed_inverse_restores_actual_original_prestate_once(revoke, fixture):
    f = fixture
    f.material = material(revoke=revoke)
    f.source.material_for.return_value = f.material
    f.request = build_direct_api_request(
        f.material.action(), deadline_at=AT + timedelta(seconds=120)
    )
    f.mutable["membership"] = revoke
    await f.adapter.execute(f.request)
    original, request = _reviewed_inverse(f)
    receipt = await f.adapter.execute(request)
    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert f.mutable["membership"] is revoke
    assert (
        original.membership_plan().membership_lock_key
        == f.material.membership_plan().membership_lock_key
    )
    assert await replace(f.adapter).execute(request) == receipt
    assert [r.method for r in f.requests if r.method != "GET"] == (
        ["DELETE", "POST"] if revoke else ["POST", "DELETE"]
    )


async def test_unowned_original_membership_cannot_be_recovered(fixture):
    f = fixture
    f.mutable["membership"] = True
    await f.adapter.execute(f.request)
    # A forged inverse must still be the opposite operation; ownership cannot be inferred from it.
    _, request = _reviewed_inverse(f)
    before = len(f.requests)
    with pytest.raises(ValueError, match="owned mutation"):
        await f.adapter.execute(request)
    assert len(f.requests) == before and f.mutable["membership"] is True


async def test_inverse_without_fresh_human_decisions_cannot_call_graph(fixture):
    f = fixture
    await f.adapter.execute(f.request)
    value, request = _reviewed_inverse(f)
    current = f.source.current.side_effect(value).model_dump()
    current["approvals"] = ()
    f.source.current.side_effect = lambda _: HumanAccessCurrentEvidence.model_validate(current)
    before = len(f.requests)
    with pytest.raises(DirectApiPreconditionError, match="quorum"):
        await f.adapter.execute(request)
    assert len(f.requests) == before and f.mutable["membership"] is True


async def test_intervening_membership_change_prevents_unowned_inverse(fixture):
    f = fixture
    await f.adapter.execute(f.request)
    _, request = _reviewed_inverse(f)
    f.mutable["membership"] = False
    with pytest.raises(DirectApiPreconditionError, match="changed before inverse"):
        await f.adapter.execute(request)
    assert [r.method for r in f.requests if r.method != "GET"] == ["POST"]


async def test_membership_attempt_audit_conforms_to_actual_executor_writer(fixture):
    from fdai_executor_service.adapters.postgres_state import _require_executor_audit_entry

    await fixture.adapter.execute(fixture.request)
    for entry in fixture.store.audit:
        _require_executor_audit_entry(entry)
