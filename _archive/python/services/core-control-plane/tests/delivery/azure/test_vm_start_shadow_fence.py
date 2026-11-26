"""Tests for the no-effect Azure VM start shadow fence probe."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.standing_authority.lease import (
    LeaseOutcome,
    ProviderCommitFenceRequest,
    ProviderCommitFenceResult,
    StandingAuthorizationLease,
    provider_idempotency_key,
)
from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.lifecycle_codec import AuthorizationLifecycleError
from fdai.delivery.azure.vm_start_shadow_fence import (
    AzureVmStartShadowFenceProbe,
    azure_vm_target_digest,
    build_azure_vm_start_shadow_binding,
)
from fdai.shared.providers.standing_authority import StandingAuthorizationStoreError

from tests.delivery.azure.vm_power_state_fixtures import RESOURCE_REF

NOW = datetime(2026, 9, 12, 4, 0, tzinfo=UTC)
REVISION = "a" * 40
ACTION_DIGEST = "sha256:" + "b" * 64
FENCE = LifecycleFence(
    family_id="family:example",
    revision_id="sha256:" + "c" * 64,
    fencing_generation=3,
    transition_digest="sha256:" + "d" * 64,
)
SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "fdai"


class _FenceStore:
    def __init__(
        self,
        result: ProviderCommitFenceResult | None = None,
        *,
        fail: bool = False,
    ) -> None:
        self.result = result or ProviderCommitFenceResult(
            allowed=True,
            outcome=LeaseOutcome.ACQUIRED,
        )
        self.fail = fail
        self.requests: list[ProviderCommitFenceRequest] = []

    async def check_commit_fence(
        self,
        request: ProviderCommitFenceRequest,
    ) -> ProviderCommitFenceResult:
        self.requests.append(request)
        if self.fail:
            raise StandingAuthorizationStoreError("store unavailable")
        return self.result


def _binding():
    return build_azure_vm_start_shadow_binding(
        resource_ref=RESOURCE_REF,
        resource_group="rg-example",
        vm_name="vm-example",
        action_digest=ACTION_DIGEST,
        executor_identity="identity:thor:resilience",
        source_revision_id=REVISION,
    )


def _lease(*, valid_until: datetime = NOW + timedelta(minutes=5)):
    binding = _binding()
    return StandingAuthorizationLease(
        lease_id=provider_idempotency_key(
            revision_id=FENCE.revision_id,
            action_digest=binding.action_digest,
            target_digest=binding.target_digest,
        ),
        family_id=FENCE.family_id,
        revision_id=FENCE.revision_id,
        fencing_generation=FENCE.fencing_generation,
        transition_digest=FENCE.transition_digest,
        action_digest=binding.action_digest,
        target_digest=binding.target_digest,
        executor_identity=binding.executor_identity,
        source_revision_id=binding.source_revision_id,
        acquired_at=NOW,
        valid_until=valid_until,
        lease_generation=1,
    )


async def test_current_fence_remains_provider_ineligible_and_effect_free() -> None:
    store = _FenceStore()
    receipt = await AzureVmStartShadowFenceProbe(store).probe(
        binding=_binding(),
        lease=_lease(),
        observed_at=NOW + timedelta(seconds=1),
    )

    assert receipt.fence_outcome is LeaseOutcome.ACQUIRED
    assert receipt.fence_current is True
    assert receipt.complete is True
    assert receipt.provider_capability_outcome is LeaseOutcome.INELIGIBLE_CAPABILITY
    assert receipt.provider_commit_attempted is False
    assert receipt.effect_applied is False
    assert receipt.effect_verified is False
    assert receipt.execution_authority is False
    assert receipt.promotion_authority is False
    assert receipt.receipt_id.startswith("sha256:")
    assert len(store.requests) == 1


@pytest.mark.parametrize(
    "outcome",
    [
        LeaseOutcome.REVOKED_BEFORE_COMMIT,
        LeaseOutcome.STALE_GENERATION,
        LeaseOutcome.LEASE_LOSS,
        LeaseOutcome.INELIGIBLE_CAPABILITY,
    ],
)
async def test_denied_fence_never_attempts_a_provider_commit(
    outcome: LeaseOutcome,
) -> None:
    receipt = await AzureVmStartShadowFenceProbe(
        _FenceStore(ProviderCommitFenceResult(allowed=False, outcome=outcome))
    ).probe(
        binding=_binding(),
        lease=_lease(),
        observed_at=NOW + timedelta(seconds=1),
    )

    assert receipt.fence_outcome is outcome
    assert receipt.fence_current is False
    assert receipt.provider_commit_attempted is False
    assert receipt.effect_applied is False


async def test_expired_lease_is_rejected_without_store_access() -> None:
    store = _FenceStore()
    receipt = await AzureVmStartShadowFenceProbe(store).probe(
        binding=_binding(),
        lease=_lease(valid_until=NOW + timedelta(seconds=10)),
        observed_at=NOW + timedelta(seconds=10),
    )

    assert receipt.fence_outcome is LeaseOutcome.EXPIRED
    assert receipt.fence_current is False
    assert store.requests == []


async def test_store_failure_is_explicit_and_incomplete() -> None:
    receipt = await AzureVmStartShadowFenceProbe(_FenceStore(fail=True)).probe(
        binding=_binding(),
        lease=_lease(),
        observed_at=NOW + timedelta(seconds=1),
    )

    assert receipt.fence_outcome is LeaseOutcome.PERSISTENCE_FAILURE
    assert receipt.complete is False
    assert receipt.provider_commit_attempted is False


def test_binding_rejects_scope_or_lease_substitution() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="match resource_ref"):
        build_azure_vm_start_shadow_binding(
            resource_ref=RESOURCE_REF,
            resource_group="rg-other",
            vm_name="vm-example",
            action_digest=ACTION_DIGEST,
            executor_identity="identity:thor:resilience",
            source_revision_id=REVISION,
        )
    with pytest.raises(AuthorizationLifecycleError, match="canonical UUID"):
        build_azure_vm_start_shadow_binding(
            resource_ref=RESOURCE_REF.replace(
                "00000000-0000-0000-0000-000000000000",
                "sub#fragment",
            ),
            resource_group="rg-example",
            vm_name="vm-example",
            action_digest=ACTION_DIGEST,
            executor_identity="identity:thor:resilience",
            source_revision_id=REVISION,
        )

    lease = _lease()
    substituted = StandingAuthorizationLease(
        lease_id=provider_idempotency_key(
            revision_id=lease.revision_id,
            action_digest=lease.action_digest,
            target_digest="sha256:" + "e" * 64,
        ),
        family_id=lease.family_id,
        revision_id=lease.revision_id,
        fencing_generation=lease.fencing_generation,
        transition_digest=lease.transition_digest,
        action_digest=lease.action_digest,
        target_digest="sha256:" + "e" * 64,
        executor_identity=lease.executor_identity,
        source_revision_id=lease.source_revision_id,
        acquired_at=lease.acquired_at,
        valid_until=lease.valid_until,
        lease_generation=lease.lease_generation,
    )
    with pytest.raises(AuthorizationLifecycleError, match="does not match"):
        import asyncio

        asyncio.run(
            AzureVmStartShadowFenceProbe(_FenceStore()).probe(
                binding=_binding(),
                lease=substituted,
                observed_at=NOW + timedelta(seconds=1),
            )
        )


def test_target_digest_is_case_insensitive_and_single_resource_bound() -> None:
    assert azure_vm_target_digest(RESOURCE_REF) == azure_vm_target_digest(RESOURCE_REF.upper())


def test_shadow_fence_probe_is_not_imported_by_authority_paths() -> None:
    forbidden = "fdai.delivery.azure.vm_start_shadow_fence"
    roots = (
        "agents",
        "composition",
        "core/control_loop",
        "core/executor",
        "core/hil_resume",
        "core/risk_gate",
        "core/workflow",
        "runtime",
    )
    violations: list[str] = []
    for root in roots:
        path = SOURCE_ROOT / root
        candidates = (path,) if path.is_file() else path.rglob("*.py")
        for candidate in candidates:
            tree = ast.parse(candidate.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    modules = (node.module,)
                else:
                    modules = ()
                if any(module.startswith(forbidden) for module in modules):
                    violations.append(str(candidate.relative_to(SOURCE_ROOT)))
    assert violations == []
