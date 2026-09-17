from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

import pytest
from fdai.delivery.kubernetes_direct_api import (
    KubernetesApiResponse,
    KubernetesDirectApiConfig,
    KubernetesDirectApiExecutor,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import (
    DirectApiOutcome,
    DirectApiPreconditionError,
    DirectApiRequest,
)


class _Ledger:
    def __init__(self) -> None:
        self.values: dict[str, Mapping[str, object]] = {}

    async def read(self, key: str) -> Mapping[str, object] | None:
        return self.values.get(key)

    async def reserve(self, key: str, fingerprint: str) -> Mapping[str, object] | None:
        if key in self.values:
            return self.values[key]
        self.values[key] = {"fingerprint": fingerprint, "state": "reserved"}
        return None

    async def complete(self, key: str, value: Mapping[str, object]) -> None:
        self.values[key] = dict(value)


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


def _request(
    *,
    action_type: str = "ops.scale-out",
    mode: Mode = Mode.SHADOW,
    resource_version: str = "rv-1",
) -> DirectApiRequest:
    arguments: dict[str, object] = {
        "target_resource_ref": "resource:deployment",
        "reason": "Order backlog exceeded the reviewed operating band.",
        "target_platform": "kubernetes",
        "cluster_ref": "cluster:one",
        "target_kind": "Deployment",
        "namespace": "pets",
        "resource_name": "makeline-service",
        "target_uid": "uid-1",
        "resource_version": resource_version,
        "replica_count": 2,
    }
    if action_type == "ops.restart-service":
        arguments["target_resource_ref"] = "resource:pod"
        arguments["target_kind"] = "Pod"
        arguments["resource_name"] = "makeline-service-abc"
        arguments["restart_reason"] = arguments.pop("reason")
        arguments["grace_period_seconds"] = 30
        arguments.pop("replica_count")
    if action_type == "ops.rollback-kubernetes-rollout":
        arguments.pop("replica_count")
        arguments["container_images"] = {
            "makeline-service": "example.invalid/makeline@sha256:" + ("a" * 64)
        }
    return DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key="operation:kubernetes-one",
        action_type_name=action_type,
        rule_ids=("rule:aks-commerce",),
        resource_ref=str(arguments["target_resource_ref"]),
        arguments=arguments,
        labels=("enforce",) if mode is Mode.ENFORCE else ("shadow",),
        mode=mode,
    )


def _executor(transport: _Transport, ledger: _Ledger) -> KubernetesDirectApiExecutor:
    return KubernetesDirectApiExecutor(
        config=KubernetesDirectApiConfig(
            api_server="https://aks.example.com",
            cluster_ref="cluster:one",
            token_path=Path("/var/run/secrets/token"),
            ca_path=Path("/var/run/secrets/ca.crt"),
            allowed_namespaces=frozenset({"pets"}),
        ),
        ledger=ledger,
        transport=transport,
    )


async def test_shadow_scale_runs_server_dry_run_only() -> None:
    transport = _Transport()
    receipt = await _executor(transport, _Ledger()).execute(_request())

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert receipt.receipt_ref.startswith("kubernetes-dry-run:")
    assert [(method, dry_run) for method, _, _, dry_run in transport.calls] == [("PUT", True)]


async def test_enforce_scale_applies_after_dry_run_and_deduplicates() -> None:
    transport = _Transport()
    ledger = _Ledger()
    executor = _executor(transport, ledger)

    first = await executor.execute(_request(mode=Mode.ENFORCE))
    duplicate = await executor.execute(_request(mode=Mode.ENFORCE))

    assert first.outcome is DirectApiOutcome.SUCCEEDED
    assert duplicate.outcome is DirectApiOutcome.ALREADY_APPLIED
    assert [(method, dry_run) for method, _, _, dry_run in transport.calls] == [
        ("PUT", True),
        ("PUT", False),
    ]


async def test_restart_uses_uid_and_resource_version_preconditions() -> None:
    transport = _Transport()
    await _executor(transport, _Ledger()).execute(_request(action_type="ops.restart-service"))

    method, path, body, dry_run = transport.calls[0]
    assert (method, dry_run) == ("DELETE", True)
    assert path.endswith("/namespaces/pets/pods/makeline-service-abc")
    assert body["preconditions"] == {"uid": "uid-1", "resourceVersion": "rv-1"}


async def test_rollback_requires_digest_pinned_images() -> None:
    request = _request(action_type="ops.rollback-kubernetes-rollout")
    arguments = dict(request.arguments)
    arguments["container_images"] = {"makeline-service": "example.invalid/latest"}
    invalid = DirectApiRequest(
        action_id=request.action_id,
        idempotency_key=request.idempotency_key,
        action_type_name=request.action_type_name,
        rule_ids=request.rule_ids,
        resource_ref=request.resource_ref,
        arguments=arguments,
        labels=request.labels,
        mode=request.mode,
    )

    with pytest.raises(DirectApiPreconditionError, match="digest-pinned"):
        await _executor(_Transport(), _Ledger()).execute(invalid)


async def test_namespace_outside_allowlist_fails_before_transport() -> None:
    request = _request()
    arguments = dict(request.arguments)
    arguments["namespace"] = "other"
    invalid = DirectApiRequest(
        action_id=request.action_id,
        idempotency_key=request.idempotency_key,
        action_type_name=request.action_type_name,
        rule_ids=request.rule_ids,
        resource_ref=request.resource_ref,
        arguments=arguments,
        labels=request.labels,
        mode=request.mode,
    )
    transport = _Transport()

    with pytest.raises(DirectApiPreconditionError, match="allowlist"):
        await _executor(transport, _Ledger()).execute(invalid)
    assert transport.calls == []


async def test_unresolved_reservation_blocks_redispatch() -> None:
    transport = _Transport()
    ledger = _Ledger()
    executor = _executor(transport, ledger)
    request = _request(mode=Mode.ENFORCE)
    ledger.values[request.idempotency_key] = {
        "fingerprint": "different",
        "state": "reserved",
    }

    with pytest.raises(DirectApiPreconditionError, match="different request"):
        await executor.execute(request)
    assert transport.calls == []

    ledger.values.clear()
    await executor.execute(_request())
    fingerprint = (await executor.execute(_request())).receipt_ref.removeprefix(
        "kubernetes-dry-run:"
    )
    ledger.values[request.idempotency_key] = {
        "fingerprint": fingerprint,
        "state": "reserved",
    }
    with pytest.raises(DirectApiPreconditionError, match="reconcile"):
        await executor.execute(request)
