from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from fdai_executor_service.adapters.subscription_tag_direct_api import (
    AzureSubscriptionTagConfig,
    AzureSubscriptionTagDirectApiExecutor,
    SubscriptionTagDirectApiRouter,
)
from fdai_service_contracts.executor import (
    DirectApiAuthenticationError,
    DirectApiError,
    DirectApiOutcome,
    DirectApiPermissionDeniedError,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
    IdentityToken,
    Mode,
)

_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_TARGET = "scope-0123456789abcdef/subscription"
_FIXED_NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


class _Identity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="executor-token",
            expires_at=_FIXED_NOW + timedelta(hours=1),
            audience=audience,
        )


def _request(mode: Mode) -> DirectApiRequest:
    return DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key="subscription-tag-one",
        action_type_name="remediate.subscription-tag-add",
        rule_ids=("operator.request.remediate.subscription-tag-add",),
        resource_ref=_TARGET,
        arguments={
            "target_resource_ref": _TARGET,
            "tag_name": "fdai-live-check",
            "tag_value": "issue-1623",
        },
        labels=("enforce",) if mode is Mode.ENFORCE else ("shadow",),
        mode=mode,
        metadata={
            "audit_ref": "action:subscription-tag-one",
            "stop_condition": "provider_api_error_streak",
            "rollback_ref": "snapshot_restore",
            "max_resources": "1",
            "executor_identity_ref": "identity/change",
        },
    )


async def test_subscription_tag_executor_plans_then_verifies_mutation() -> None:
    requests: list[httpx.Request] = []
    reads = iter(
        (
            {"properties": {"tags": {"owner": "platform"}}},
            {
                "properties": {
                    "tags": {
                        "owner": "platform",
                        "fdai-live-check": "issue-1623",
                    }
                }
            },
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=next(reads))
        return httpx.Response(
            200,
            json={"properties": {"tags": {"fdai-live-check": "issue-1623"}}},
        )

    identity = _Identity()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureSubscriptionTagDirectApiExecutor(
            config=AzureSubscriptionTagConfig(subscription_id=_SUBSCRIPTION),
            identity=identity,
            http_client=client,
        ).execute(_request(Mode.ENFORCE))

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert [request.method for request in requests] == ["GET", "PATCH", "GET"]
    assert all(f"/subscriptions/{_SUBSCRIPTION}/" in request.url.path for request in requests)
    assert identity.audiences == [
        "https://management.azure.com/.default",
        "https://management.azure.com/.default",
        "https://management.azure.com/.default",
    ]


async def test_subscription_tag_executor_shadow_only_reads_current_tags() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"properties": {"tags": {}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureSubscriptionTagDirectApiExecutor(
            config=AzureSubscriptionTagConfig(subscription_id=_SUBSCRIPTION),
            identity=_Identity(),
            http_client=client,
        ).execute(_request(Mode.SHADOW))

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert [request.method for request in requests] == ["GET"]


def test_subscription_tag_config_rejects_invalid_uuid() -> None:
    with pytest.raises(ValueError, match="valid subscription id"):
        AzureSubscriptionTagConfig(subscription_id="not-a-uuid")


@pytest.mark.parametrize(
    ("mutator", "exc_type", "match"),
    [
        (
            lambda r: replace(r, action_type_name="ops.start-vm"),
            DirectApiPreconditionError,
            "received another action",
        ),
        (
            lambda r: replace(r, labels=()),
            DirectApiPromotionError,
            "explicit enforce label",
        ),
        (
            lambda r: replace(r, arguments={}),
            DirectApiPreconditionError,
            "target_resource_ref",
        ),
        (
            lambda r: replace(r, resource_ref="scope-other/subscription"),
            DirectApiPreconditionError,
            "MUST match the canonical target",
        ),
        (
            lambda r: replace(
                r,
                metadata={**r.metadata, "executor_identity_ref": "identity/finops"},
            ),
            DirectApiPreconditionError,
            "change executor identity",
        ),
        (
            lambda r: replace(r, metadata={**r.metadata, "rollback_ref": "other"}),
            DirectApiPreconditionError,
            "snapshot_restore rollback",
        ),
        (
            lambda r: replace(r, metadata={**r.metadata, "max_resources": "2"}),
            DirectApiPreconditionError,
            "max_resources=1",
        ),
    ],
)
async def test_subscription_tag_preconditions(
    mutator: object,
    exc_type: type[Exception],
    match: str,
) -> None:
    async with httpx.AsyncClient() as client:
        executor = AzureSubscriptionTagDirectApiExecutor(
            config=AzureSubscriptionTagConfig(subscription_id=_SUBSCRIPTION),
            identity=_Identity(),
            http_client=client,
        )
        with pytest.raises(exc_type, match=match):
            await executor.execute(mutator(_request(Mode.ENFORCE)))  # type: ignore[operator]


async def test_subscription_tag_rejects_non_string_resolved_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai_service_contracts.executor import AzureOperationTarget

    monkeypatch.setattr(
        "fdai_executor_service.adapters.subscription_tag_direct_api.resolve_azure_operation_target",
        lambda *_args: AzureOperationTarget(
            operation_id="op",
            resource_ref=_TARGET,
            arguments={"tag_name": 123, "tag_value": "v"},
        ),
    )
    async with httpx.AsyncClient() as client:
        executor = AzureSubscriptionTagDirectApiExecutor(
            config=AzureSubscriptionTagConfig(subscription_id=_SUBSCRIPTION),
            identity=_Identity(),
            http_client=client,
        )
        with pytest.raises(DirectApiPreconditionError, match="bounded tag text"):
            await executor.execute(_request(Mode.ENFORCE))


@pytest.mark.parametrize("rollback_succeeds", [True, False])
async def test_subscription_tag_rollback_on_verification_mismatch(
    rollback_succeeds: bool,
) -> None:
    get_responses = iter(
        [
            {"properties": {"tags": {"owner": "platform"}}},
            {"properties": {"tags": {"owner": "platform", "fdai-live-check": "wrong"}}},
            {
                "properties": {
                    "tags": {"owner": "platform"} if rollback_succeeds else {"owner": "drifted"}
                }
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=next(get_responses))
        return httpx.Response(200, json={"properties": {"tags": {}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        executor = AzureSubscriptionTagDirectApiExecutor(
            config=AzureSubscriptionTagConfig(subscription_id=_SUBSCRIPTION),
            identity=_Identity(),
            http_client=client,
        )
        expected = "prior snapshot was restored" if rollback_succeeds else "could not restore"
        with pytest.raises(DirectApiError, match=expected):
            await executor.execute(_request(Mode.ENFORCE))


@pytest.mark.parametrize(
    ("response_factory", "exc_type", "match"),
    [
        (
            lambda req: httpx.Response(401, json={}),
            DirectApiAuthenticationError,
            "rejected subscription tag authentication",
        ),
        (
            lambda req: httpx.Response(403, json={}),
            DirectApiPermissionDeniedError,
            "denied the subscription tag executor",
        ),
        (
            lambda req: httpx.Response(500, json={}),
            DirectApiError,
            "returned HTTP 500",
        ),
        (
            lambda req: httpx.Response(200, content=b"not-json"),
            DirectApiError,
            "was not JSON",
        ),
        (
            lambda req: httpx.Response(200, json=["list"]),
            DirectApiError,
            "was not an object",
        ),
        (
            lambda req: httpx.Response(200, content=b"x" * 32_769),
            DirectApiError,
            "exceeded its byte limit",
        ),
        (
            lambda req: httpx.Response(200, json={"properties": {"tags": {"bad": 1}}}),
            DirectApiError,
            "string map",
        ),
        (
            lambda req: (
                httpx.Response(200, json={"properties": {"tags": {}}})
                if req.method == "GET"
                else httpx.Response(200, json={"properties": None})
            ),
            DirectApiError,
            "mutation returned an invalid response",
        ),
    ],
)
async def test_subscription_tag_http_and_payload_errors(
    response_factory: object,
    exc_type: type[Exception],
    match: str,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response_factory)  # type: ignore[arg-type]
    ) as client:
        executor = AzureSubscriptionTagDirectApiExecutor(
            config=AzureSubscriptionTagConfig(subscription_id=_SUBSCRIPTION),
            identity=_Identity(),
            http_client=client,
        )
        with pytest.raises(exc_type, match=match):
            await executor.execute(_request(Mode.ENFORCE))


async def test_subscription_tag_transport_error_and_router() -> None:
    def failing_transport(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(failing_transport)) as client:
        executor = AzureSubscriptionTagDirectApiExecutor(
            config=AzureSubscriptionTagConfig(subscription_id=_SUBSCRIPTION),
            identity=_Identity(),
            http_client=client,
        )
        with pytest.raises(DirectApiError, match="request failed"):
            await executor.execute(_request(Mode.SHADOW))

    class _SubExecutor:
        async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
            return DirectApiReceipt(outcome=DirectApiOutcome.SUCCEEDED, receipt_ref="sub:ok")

    class _StatusFallback:
        async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
            return DirectApiReceipt(outcome=DirectApiOutcome.SUCCEEDED, receipt_ref="fb:ok")

        async def operation_status(self, request: DirectApiRequest) -> DirectApiReceipt | None:
            return DirectApiReceipt(outcome=DirectApiOutcome.ALREADY_APPLIED, receipt_ref="fb:st")

    router_no_fb = SubscriptionTagDirectApiRouter(_SubExecutor(), None)
    assert (await router_no_fb.execute(_request(Mode.SHADOW))).receipt_ref == "sub:ok"
    assert await router_no_fb.operation_status(_request(Mode.ENFORCE)) is None
    other_req = replace(_request(Mode.ENFORCE), action_type_name="ops.start-vm")
    with pytest.raises(DirectApiPreconditionError, match="no isolated Executor adapter"):
        await router_no_fb.execute(other_req)
    assert await router_no_fb.operation_status(other_req) is None

    router_with_fb = SubscriptionTagDirectApiRouter(_SubExecutor(), _StatusFallback())
    assert (await router_with_fb.execute(other_req)).receipt_ref == "fb:ok"
    status_receipt = await router_with_fb.operation_status(other_req)
    assert status_receipt is not None and status_receipt.receipt_ref == "fb:st"


def test_human_access_current_replacements_validation() -> None:
    import copy
    import runpy
    from pathlib import Path

    from fdai_executor_service.adapters.postgres_human_access import (
        _require_current_replacements,
    )

    support = runpy.run_path(
        str(
            Path(__file__).resolve().parents[3]
            / "packages/service-contracts/tests/test_human_access_execution.py"
        )
    )
    at, material_fn = support["AT"], support["material"]
    rev_mat = material_fn(revoke=True)
    rev_intent = {
        "revocation": {
            "case_id": "case:orig",
            "revision": 4,
            "replacement_revisions": {"case:primary": 8, "case:backup": 8},
        }
    }
    good_receipts = [
        {"kind": "iam", "receipt_ref": "r1", "digest": "a" * 64, "received_at": at.isoformat()},
        {
            "kind": "ownership",
            "receipt_ref": "r2",
            "digest": "b" * 64,
            "received_at": at.isoformat(),
        },
    ]
    good_related: dict[str, object] = {
        "human_assignment:case:case:orig": {
            "revocation_case_id": rev_mat.action().params["case_id"],
            "state": "degraded",
            "revision": 5,
            "intent": {
                "duty_bindings": [{"agent_name": "Thor", "scope_ref": "scope:1", "duty": "primary"}]
            },
        },
        "human_assignment:case:case:primary": {
            "revision": 8,
            "state": "active",
            "revocation_case_id": None,
            "effect_receipts": copy.deepcopy(good_receipts),
            "intent": {
                "subject": {"provider": "entra", "subject_id": "person:primary"},
                "duty_bindings": [
                    {"agent_name": "Thor", "scope_ref": "scope:1", "duty": "primary"}
                ],
            },
        },
        "human_assignment:case:case:backup": {
            "revision": 8,
            "state": "active",
            "revocation_case_id": None,
            "effect_receipts": copy.deepcopy(good_receipts),
            "intent": {
                "subject": {"provider": "entra", "subject_id": "person:backup"},
                "duty_bindings": [{"agent_name": "Thor", "scope_ref": "scope:1", "duty": "backup"}],
            },
        },
    }
    _require_current_replacements(
        {"related_cases": good_related, "other_demand": False},
        material=rev_mat,
        intent=rev_intent,
    )

    for rel_mut, intent_mut, match in [
        (
            lambda d: d.__setitem__("other_demand", True),
            lambda _i: None,
            "incomplete or still demanded",
        ),
        (
            lambda d: d["related_cases"]["human_assignment:case:case:orig"].__setitem__(
                "state", "active"
            ),
            lambda _i: None,
            "exact retained removal hold",
        ),
        (
            lambda _d: None,
            lambda i: i["revocation"].__setitem__("replacement_revisions", {}),
            "replacement intent changed",
        ),
        (
            lambda d: d["related_cases"]["human_assignment:case:case:primary"].__setitem__(
                "state", "degraded"
            ),
            lambda _i: None,
            "exact active revision",
        ),
        (
            lambda d: d["related_cases"]["human_assignment:case:case:primary"].__setitem__(
                "effect_receipts", []
            ),
            lambda _i: None,
            "replacement effects are incomplete",
        ),
        (
            lambda d: d["related_cases"]["human_assignment:case:case:primary"]["effect_receipts"][
                0
            ].__setitem__("digest", "bad"),
            lambda _i: None,
            "effect evidence is malformed",
        ),
        (
            lambda d: d["related_cases"]["human_assignment:case:case:primary"]["effect_receipts"][
                0
            ].__setitem__("received_at", "2026-09-15T12:00:00"),
            lambda _i: None,
            "effect time is unavailable",
        ),
        (
            lambda d: d["related_cases"]["human_assignment:case:case:primary"][
                "intent"
            ].__setitem__("subject", {"provider": "other", "subject_id": "p"}),
            lambda _i: None,
            "not independently observed",
        ),
        (
            lambda d: d["related_cases"]["human_assignment:case:case:primary"]["intent"][
                "duty_bindings"
            ].__setitem__(0, "bad"),
            lambda _i: None,
            "duty binding is malformed",
        ),
        (
            lambda d: d["related_cases"]["human_assignment:case:case:orig"].__setitem__(
                "intent", None
            ),
            lambda _i: None,
            "original duty coverage is unavailable",
        ),
        (
            lambda d: d["related_cases"]["human_assignment:case:case:backup"]["intent"][
                "duty_bindings"
            ][0].__setitem__("scope_ref", "scope:other"),
            lambda _i: None,
            "replacement coverage is incomplete",
        ),
    ]:
        p_copy = {"related_cases": copy.deepcopy(good_related), "other_demand": False}
        i_copy = copy.deepcopy(rev_intent)
        rel_mut(p_copy)  # type: ignore[no-untyped-call]
        intent_mut(i_copy)  # type: ignore[no-untyped-call]
        with pytest.raises(ValueError, match=match):
            _require_current_replacements(p_copy, material=rev_mat, intent=i_copy)
