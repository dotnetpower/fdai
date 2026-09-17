from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from fdai_executor_service.adapters.kubernetes_direct_api import (
    KubernetesApiResponse,
    KubernetesDirectApiConfig,
    KubernetesDirectApiExecutor,
    KubernetesDirectApiRouter,
)
from fdai_service_contracts.executor import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
    Mode,
)


class _Transport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Mapping[str, object], bool]] = []

    async def request(
        self,
        *,
        method: str,
        path: str,
        body: Mapping[str, object],
        dry_run: bool,
    ) -> KubernetesApiResponse:
        self.calls.append((method, path, body, dry_run))
        return KubernetesApiResponse(
            status_code=200,
            body={"metadata": {"uid": "uid-1", "resourceVersion": "rv-2"}},
            resource_version="rv-2",
        )


class _Fallback:
    def __init__(self) -> None:
        self.calls: list[DirectApiRequest] = []

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        self.calls.append(request)
        return _receipt()


def _receipt() -> DirectApiReceipt:
    return DirectApiReceipt(
        outcome=DirectApiOutcome.SUCCEEDED,
        receipt_ref="fallback:one",
    )


def _request(
    *,
    action_type: str = "ops.scale-out",
    mode: Mode = Mode.ENFORCE,
) -> DirectApiRequest:
    arguments: dict[str, object] = {
        "target_resource_ref": "resource:deployment",
        "reason": "Order backlog exceeded the reviewed operating band.",
        "target_platform": "kubernetes",
        "cluster_ref": "cluster:one",
        "target_kind": "Deployment",
        "namespace": "fdai-runtime",
        "resource_name": "operator-service",
        "target_uid": "uid-1",
        "resource_version": "rv-1",
        "replica_count": 2,
    }
    if action_type == "ops.restart-service":
        arguments["target_resource_ref"] = "resource:pod"
        arguments["target_kind"] = "Pod"
        arguments["resource_name"] = "operator-service-abc"
        arguments["restart_reason"] = arguments.pop("reason")
        arguments["grace_period_seconds"] = 30
        arguments.pop("replica_count")
    if action_type == "ops.rollback-kubernetes-rollout":
        arguments.pop("replica_count")
        arguments["container_images"] = {
            "operator-service": "example.invalid/operator@sha256:" + ("a" * 64)
        }
    return DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key="operation:kubernetes-one",
        action_type_name=action_type,
        rule_ids=("rule:aks-runtime",),
        resource_ref=str(arguments["target_resource_ref"]),
        arguments=arguments,
        labels=("enforce",) if mode is Mode.ENFORCE else ("shadow",),
        mode=mode,
    )


def _executor(transport: _Transport) -> KubernetesDirectApiExecutor:
    return KubernetesDirectApiExecutor(
        config=KubernetesDirectApiConfig(
            api_server="https://kubernetes.default.svc",
            cluster_ref="cluster:one",
            token_path=Path("/var/run/secrets/token"),
            ca_path=Path("/var/run/secrets/ca.crt"),
            allowed_namespaces=frozenset({"fdai-runtime"}),
        ),
        transport=transport,
    )


async def test_enforce_scale_applies_only_after_server_dry_run() -> None:
    transport = _Transport()

    receipt = await _executor(transport).execute(_request())

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert receipt.receipt_ref.startswith("kubernetes:")
    assert [(method, dry_run) for method, _, _, dry_run in transport.calls] == [
        ("PUT", True),
        ("PUT", False),
    ]


async def test_restart_uses_uid_and_resource_version_preconditions() -> None:
    transport = _Transport()

    await _executor(transport).execute(_request(action_type="ops.restart-service"))

    method, path, body, dry_run = transport.calls[0]
    assert (method, dry_run) == ("DELETE", True)
    assert path.endswith("/namespaces/fdai-runtime/pods/operator-service-abc")
    assert body["preconditions"] == {"uid": "uid-1", "resourceVersion": "rv-1"}


async def test_rollback_requires_digest_pinned_images() -> None:
    request = _request(action_type="ops.rollback-kubernetes-rollout")
    arguments = {**request.arguments, "container_images": {"operator-service": "latest"}}

    with pytest.raises(DirectApiPreconditionError, match="digest-pinned"):
        await _executor(_Transport()).execute(replace(request, arguments=arguments))


async def test_namespace_outside_allowlist_fails_before_transport() -> None:
    request = _request()
    transport = _Transport()

    with pytest.raises(DirectApiPreconditionError, match="allowlist"):
        await _executor(transport).execute(
            replace(request, arguments={**request.arguments, "namespace": "other"})
        )
    assert transport.calls == []


async def test_enforce_requires_explicit_promotion_label() -> None:
    request = _request()

    with pytest.raises(DirectApiPromotionError, match="enforce label"):
        await _executor(_Transport()).execute(replace(request, labels=()))


async def test_router_uses_fallback_only_for_non_kubernetes_actions() -> None:
    transport = _Transport()
    fallback = _Fallback()
    router = KubernetesDirectApiRouter(_executor(transport), fallback)
    request = _request(action_type="ops.flush-cache")

    receipt = await router.execute(request)

    assert receipt.receipt_ref == "fallback:one"
    assert fallback.calls == [request]
    assert transport.calls == []
