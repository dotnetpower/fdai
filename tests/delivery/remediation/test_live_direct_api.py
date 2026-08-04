"""Unit tests for the live (enforce) DirectApiExecutor remediation adapter.

Subprocess is fully mocked (``_run`` monkeypatched), so these never touch a
real cluster - they lock the command shape, the promotion gate, idempotency,
and the shadow no-mutation posture.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

import fdai.delivery.remediation.live_direct_api as lda
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import (
    DirectApiOutcome,
    DirectApiPromotionError,
    DirectApiRequest,
)


def _req(
    *,
    action_type: str = "ops.scale-out",
    mode: Mode = Mode.ENFORCE,
    labels: tuple[str, ...] = ("shadow", "enforce"),
    key: str = "k1",
    arguments: dict[str, object] | None = None,
) -> DirectApiRequest:
    return DirectApiRequest(
        action_id=uuid4(),
        idempotency_key=key,
        action_type_name=action_type,
        rule_ids=("r1",),
        resource_ref="demo/nginx-demo",
        arguments=arguments
        if arguments is not None
        else {"target_resource_ref": "nginx-demo", "replica_count": 3, "reason": "x"},
        labels=labels,
        mode=mode,
    )


def _fake_run(rc: int = 0, out: str = "ok", err: str = ""):  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    async def runner(cmd, *, timeout=90.0, drop_azure_config_dir=False):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return (rc, out, err)

    return runner, calls


def _exec() -> lda.KubectlDirectApiExecutor:
    return lda.KubectlDirectApiExecutor(context="ctx", namespace="demo")


# --------------------------------------------------------------------------
# Promotion gate
# --------------------------------------------------------------------------


async def test_enforce_without_label_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, calls = _fake_run()
    monkeypatch.setattr(lda, "_run", runner)
    with pytest.raises(DirectApiPromotionError):
        await _exec().execute(_req(labels=("shadow",), mode=Mode.ENFORCE))
    assert calls == []  # never touched the substrate


# --------------------------------------------------------------------------
# Shadow never mutates
# --------------------------------------------------------------------------


async def test_shadow_records_intent_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _fake_run()
    monkeypatch.setattr(lda, "_run", runner)
    r = await _exec().execute(_req(mode=Mode.SHADOW, labels=("shadow",)))
    assert r.outcome is DirectApiOutcome.SUCCEEDED
    assert "no mutation" in (r.detail or "")
    assert calls == []


async def test_shadow_does_not_block_later_enforce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _fake_run(out="scaled")
    monkeypatch.setattr(lda, "_run", runner)
    executor = _exec()
    shadow = await executor.execute(_req(mode=Mode.SHADOW, labels=("shadow",), key="k-same"))
    assert shadow.outcome is DirectApiOutcome.SUCCEEDED
    assert calls == []
    # A later ENFORCE with the same idempotency key MUST still mutate; the
    # shadow run must not have populated the ledger to short-circuit it.
    enforce = await executor.execute(
        _req(mode=Mode.ENFORCE, labels=("shadow", "enforce"), key="k-same")
    )
    assert enforce.outcome is DirectApiOutcome.SUCCEEDED
    assert not enforce.already_existed
    assert calls != []


# --------------------------------------------------------------------------
# scale-out
# --------------------------------------------------------------------------


async def test_scale_out_enforce_runs_kubectl_scale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _fake_run(out="scaled")
    monkeypatch.setattr(lda, "_run", runner)
    r = await _exec().execute(_req(action_type="ops.scale-out"))
    assert r.outcome is DirectApiOutcome.SUCCEEDED
    assert any("scale" in c and "--replicas=3" in c for c in calls)
    assert any("deployment/nginx-demo" in c for c in calls)


async def test_scale_out_missing_replica_count_precondition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _fake_run()
    monkeypatch.setattr(lda, "_run", runner)
    r = await _exec().execute(
        _req(
            action_type="ops.scale-out",
            arguments={"target_resource_ref": "nginx-demo", "reason": "x"},
        )
    )
    assert r.outcome is DirectApiOutcome.PRECONDITION_FAILED
    assert calls == []


async def test_scale_out_kubectl_failure_returns_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, _ = _fake_run(rc=1, err="boom")
    monkeypatch.setattr(lda, "_run", runner)
    r = await _exec().execute(_req(action_type="ops.scale-out"))
    assert r.outcome is DirectApiOutcome.FAILED


# --------------------------------------------------------------------------
# restart-service
# --------------------------------------------------------------------------


async def test_restart_enforce_runs_rollout_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _fake_run(out="deployment.apps/nginx-demo restarted")
    monkeypatch.setattr(lda, "_run", runner)
    r = await _exec().execute(
        _req(
            action_type="ops.restart-service",
            arguments={
                "target_resource_ref": "nginx-demo",
                "restart_reason": "health fault recovery",
            },
        )
    )
    assert r.outcome is DirectApiOutcome.SUCCEEDED
    assert any("rollout" in c and "restart" in c and "deployment/nginx-demo" in c for c in calls)


# --------------------------------------------------------------------------
# Idempotency + unknown action type
# --------------------------------------------------------------------------


async def test_idempotent_replay_returns_already_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _fake_run(out="scaled")
    monkeypatch.setattr(lda, "_run", runner)
    ex = _exec()
    r1 = await ex.execute(_req(key="same"))
    r2 = await ex.execute(_req(key="same"))
    assert r1.outcome is DirectApiOutcome.SUCCEEDED
    assert r2.outcome is DirectApiOutcome.ALREADY_APPLIED
    assert r2.already_existed is True
    # Only the first call touched the substrate.
    assert sum(1 for c in calls if "scale" in c) == 1


async def test_unknown_action_type_returns_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _fake_run()
    monkeypatch.setattr(lda, "_run", runner)
    r = await _exec().execute(_req(action_type="ops.does-not-exist"))
    assert r.outcome is DirectApiOutcome.FAILED
    assert "no_handler_for_action_type" in (r.detail or "")
    assert calls == []


async def test_custom_resource_patch_remains_unregistered_without_full_safeguards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _fake_run()
    monkeypatch.setattr(lda, "_run", runner)

    result = await _exec().execute(
        _req(
            action_type="remediate.kubernetes-patch",
            arguments={
                "api_version": "database.example.io/v1",
                "kind": "Database",
                "namespace": "demo",
                "name": "catalog",
                "expected_resource_version": "10",
                "expected_generation": 4,
                "patch": [{"op": "replace", "path": "/spec/replicas", "value": 1}],
            },
        )
    )

    assert result.outcome is DirectApiOutcome.FAILED
    assert "no_handler_for_action_type" in (result.detail or "")
    assert calls == []


async def test_pod_security_patch_remains_unregistered_without_outcome_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _fake_run()
    monkeypatch.setattr(lda, "_run", runner)

    result = await _exec().execute(
        _req(
            action_type="remediate.kubernetes-patch",
            arguments={
                "api_version": "apps/v1",
                "kind": "Deployment",
                "namespace": "demo",
                "name": "api",
                "expected_resource_version": "10",
                "expected_generation": 4,
                "patch": [
                    {
                        "op": "add",
                        "path": "/spec/template/spec/containers/0/securityContext",
                        "value": {"allowPrivilegeEscalation": False},
                    }
                ],
            },
        )
    )

    assert result.outcome is DirectApiOutcome.FAILED
    assert "no_handler_for_action_type" in (result.detail or "")
    assert calls == []


# --------------------------------------------------------------------------
# resource-ref parsing + env hygiene
# --------------------------------------------------------------------------


async def test_deployment_parsed_from_ns_slash_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, calls = _fake_run(out="scaled")
    monkeypatch.setattr(lda, "_run", runner)
    req = _req(arguments={"replica_count": 2})  # no target_resource_ref -> use resource_ref
    r = await _exec().execute(req)
    assert r.outcome is DirectApiOutcome.SUCCEEDED
    # resource_ref "demo/nginx-demo" -> deployment "nginx-demo"
    assert any("deployment/nginx-demo" in c for c in calls)
