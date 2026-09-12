"""Shadow-only provider-boundary fence probe for one Azure VM start target."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from fdai.core.standing_authority.lease import (
    LeaseOutcome,
    ProviderCommitFenceResult,
    StandingAuthorizationLease,
    build_provider_commit_fence_request,
)
from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    aware_utc,
    content_digest,
    instant,
    require_aware,
    require_digest,
    require_text,
)
from fdai.shared.providers.standing_authority import (
    StandingAuthorizationLeaseStore,
    StandingAuthorizationStoreError,
)

_ACTION_TYPE = "ops.start-vm"
_ACTION_TYPE_VERSION = "1.0.0"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}$")
_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_VM_RESOURCE = re.compile(
    r"^/subscriptions/(?P<subscription>[^/]+)/resourceGroups/"
    r"(?P<resource_group>[^/]+)/providers/Microsoft\.Compute/"
    r"virtualMachines/(?P<vm_name>[^/]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AzureVmStartShadowFenceBinding:
    """Bind one shadow fence probe to one ActionType, resource group, and VM."""

    resource_ref: str
    resource_group: str
    vm_name: str
    action_digest: str
    target_digest: str
    executor_identity: str
    source_revision_id: str
    action_type_name: Literal["ops.start-vm"] = "ops.start-vm"
    action_type_version: Literal["1.0.0"] = "1.0.0"
    resource_group_count: Literal[1] = 1
    resource_count: Literal[1] = 1

    def __post_init__(self) -> None:
        match = _VM_RESOURCE.fullmatch(self.resource_ref)
        if match is None:
            raise AuthorizationLifecycleError(
                "shadow fence resource_ref MUST identify one Azure virtual machine"
            )
        if (
            _NAME.fullmatch(self.resource_group) is None
            or _NAME.fullmatch(self.vm_name) is None
            or match.group("resource_group").casefold() != self.resource_group.casefold()
            or match.group("vm_name").casefold() != self.vm_name.casefold()
        ):
            raise AuthorizationLifecycleError(
                "shadow fence resource group and VM MUST match resource_ref"
            )
        _require_canonical_subscription(match.group("subscription"))
        require_digest("action_digest", self.action_digest)
        require_digest("target_digest", self.target_digest)
        require_text("executor_identity", self.executor_identity)
        if _REVISION.fullmatch(self.source_revision_id) is None:
            raise AuthorizationLifecycleError(
                "source_revision_id MUST be a full immutable revision"
            )
        if self.action_type_name != _ACTION_TYPE:
            raise AuthorizationLifecycleError("shadow fence supports only ops.start-vm")
        if self.action_type_version != _ACTION_TYPE_VERSION:
            raise AuthorizationLifecycleError("shadow fence supports only ops.start-vm@1.0.0")
        if self.target_digest != azure_vm_target_digest(self.resource_ref):
            raise AuthorizationLifecycleError("shadow fence target_digest mismatch")
        if self.resource_group_count != 1 or self.resource_count != 1:
            raise AuthorizationLifecycleError(
                "shadow fence scope MUST contain one resource group and one VM"
            )


@dataclass(frozen=True, slots=True)
class ProviderFenceShadowReceipt:
    """Content-addressed observation that never permits a provider commit."""

    action_type_name: str
    action_type_version: str
    resource_ref: str
    resource_group: str
    vm_name: str
    lease_id: str
    family_id: str
    authorization_revision_id: str
    lease_generation: int
    fencing_generation: int
    transition_digest: str
    action_digest: str
    target_digest: str
    executor_identity: str
    source_revision_id: str
    observed_at: datetime
    fence_outcome: LeaseOutcome
    fence_current: bool
    complete: bool
    provider_capability_outcome: Literal[LeaseOutcome.INELIGIBLE_CAPABILITY] = (
        LeaseOutcome.INELIGIBLE_CAPABILITY
    )
    provider_commit_attempted: Literal[False] = False
    effect_applied: Literal[False] = False
    effect_verified: Literal[False] = False
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False
    receipt_id: str = field(init=False)

    def __post_init__(self) -> None:
        match = _VM_RESOURCE.fullmatch(self.resource_ref)
        if (
            match is None
            or match.group("resource_group").casefold() != self.resource_group.casefold()
            or match.group("vm_name").casefold() != self.vm_name.casefold()
        ):
            raise AuthorizationLifecycleError("shadow fence receipt scope MUST match one Azure VM")
        if (
            self.action_type_name != _ACTION_TYPE
            or self.action_type_version != _ACTION_TYPE_VERSION
        ):
            raise AuthorizationLifecycleError("shadow fence receipt MUST bind ops.start-vm@1.0.0")
        require_digest("lease_id", self.lease_id)
        require_text("family_id", self.family_id)
        require_digest("authorization_revision_id", self.authorization_revision_id)
        require_digest("transition_digest", self.transition_digest)
        require_digest("action_digest", self.action_digest)
        require_digest("target_digest", self.target_digest)
        require_text("executor_identity", self.executor_identity)
        if _REVISION.fullmatch(self.source_revision_id) is None:
            raise AuthorizationLifecycleError(
                "shadow fence receipt source revision MUST be immutable"
            )
        if self.target_digest != azure_vm_target_digest(self.resource_ref):
            raise AuthorizationLifecycleError("shadow fence receipt target_digest mismatch")
        require_aware("observed_at", self.observed_at)
        if self.lease_generation < 1 or self.fencing_generation < 1:
            raise AuthorizationLifecycleError("shadow fence generations MUST be positive")
        if self.fence_current != (self.fence_outcome is LeaseOutcome.ACQUIRED):
            raise AuthorizationLifecycleError("fence_current MUST match the acquired fence outcome")
        if self.complete != (self.fence_outcome is not LeaseOutcome.PERSISTENCE_FAILURE):
            raise AuthorizationLifecycleError(
                "shadow fence completeness MUST reflect persistence availability"
            )
        if self.provider_capability_outcome is not LeaseOutcome.INELIGIBLE_CAPABILITY:
            raise AuthorizationLifecycleError(
                "shadow fence provider capability MUST remain ineligible"
            )
        if any(
            (
                self.provider_commit_attempted,
                self.effect_applied,
                self.effect_verified,
                self.execution_authority,
                self.promotion_authority,
            )
        ):
            raise AuthorizationLifecycleError(
                "shadow fence receipt MUST NOT carry authority or effect claims"
            )
        object.__setattr__(self, "receipt_id", content_digest(_receipt_body(self)))


class AzureVmStartShadowFenceProbe:
    """Observe the current lease fence without submitting an Azure operation."""

    def __init__(self, store: StandingAuthorizationLeaseStore) -> None:
        self._store = store

    async def probe(
        self,
        *,
        binding: AzureVmStartShadowFenceBinding,
        lease: StandingAuthorizationLease,
        observed_at: datetime,
    ) -> ProviderFenceShadowReceipt:
        """Return a no-authority receipt for one exact shadow fence check."""

        observed_at = aware_utc(observed_at)
        _validate_lease(binding, lease)
        if lease.is_expired(observed_at):
            result = ProviderCommitFenceResult(
                allowed=False,
                outcome=LeaseOutcome.EXPIRED,
            )
        else:
            try:
                result = await self._store.check_commit_fence(
                    build_provider_commit_fence_request(lease)
                )
            except StandingAuthorizationStoreError:
                result = ProviderCommitFenceResult(
                    allowed=False,
                    outcome=LeaseOutcome.PERSISTENCE_FAILURE,
                )
        return ProviderFenceShadowReceipt(
            action_type_name=binding.action_type_name,
            action_type_version=binding.action_type_version,
            resource_ref=binding.resource_ref.casefold(),
            resource_group=binding.resource_group.casefold(),
            vm_name=binding.vm_name.casefold(),
            lease_id=lease.lease_id,
            family_id=lease.family_id,
            authorization_revision_id=lease.revision_id,
            lease_generation=lease.lease_generation,
            fencing_generation=lease.fencing_generation,
            transition_digest=lease.transition_digest,
            action_digest=lease.action_digest,
            target_digest=lease.target_digest,
            executor_identity=lease.executor_identity,
            source_revision_id=binding.source_revision_id,
            observed_at=observed_at,
            fence_outcome=result.outcome,
            fence_current=result.allowed,
            complete=result.outcome is not LeaseOutcome.PERSISTENCE_FAILURE,
        )


def build_azure_vm_start_shadow_binding(
    *,
    resource_ref: str,
    resource_group: str,
    vm_name: str,
    action_digest: str,
    executor_identity: str,
    source_revision_id: str,
) -> AzureVmStartShadowFenceBinding:
    """Build the exact one-resource binding used by a shadow fence probe."""

    return AzureVmStartShadowFenceBinding(
        resource_ref=resource_ref,
        resource_group=resource_group,
        vm_name=vm_name,
        action_digest=action_digest,
        target_digest=azure_vm_target_digest(resource_ref),
        executor_identity=executor_identity,
        source_revision_id=source_revision_id,
    )


def azure_vm_target_digest(resource_ref: str) -> str:
    """Return the canonical target digest for one Azure VM resource id."""

    match = _VM_RESOURCE.fullmatch(resource_ref)
    if match is None:
        raise AuthorizationLifecycleError(
            "target resource_ref MUST identify one Azure virtual machine"
        )
    _require_canonical_subscription(match.group("subscription"))
    return content_digest(
        {
            "provider": "azure",
            "resource_ref": resource_ref.casefold(),
            "resource_count": 1,
            "resource_group_count": 1,
        }
    )


def _validate_lease(
    binding: AzureVmStartShadowFenceBinding,
    lease: StandingAuthorizationLease,
) -> None:
    if (
        lease.action_digest != binding.action_digest
        or lease.target_digest != binding.target_digest
        or lease.executor_identity != binding.executor_identity
        or lease.source_revision_id != binding.source_revision_id
    ):
        raise AuthorizationLifecycleError("shadow fence binding does not match the acquired lease")


def _require_canonical_subscription(subscription: str) -> None:
    try:
        canonical_subscription = str(UUID(subscription))
    except (AttributeError, ValueError) as exc:
        raise AuthorizationLifecycleError(
            "shadow fence subscription MUST be a canonical UUID"
        ) from exc
    if canonical_subscription != subscription.casefold():
        raise AuthorizationLifecycleError("shadow fence subscription MUST be a canonical UUID")


def _receipt_body(receipt: ProviderFenceShadowReceipt) -> dict[str, object]:
    return {
        "action_type_name": receipt.action_type_name,
        "action_type_version": receipt.action_type_version,
        "resource_ref": receipt.resource_ref,
        "resource_group": receipt.resource_group,
        "vm_name": receipt.vm_name,
        "lease_id": receipt.lease_id,
        "family_id": receipt.family_id,
        "authorization_revision_id": receipt.authorization_revision_id,
        "lease_generation": receipt.lease_generation,
        "fencing_generation": receipt.fencing_generation,
        "transition_digest": receipt.transition_digest,
        "action_digest": receipt.action_digest,
        "target_digest": receipt.target_digest,
        "executor_identity": receipt.executor_identity,
        "source_revision_id": receipt.source_revision_id,
        "observed_at": instant(receipt.observed_at),
        "fence_outcome": receipt.fence_outcome.value,
        "fence_current": receipt.fence_current,
        "complete": receipt.complete,
        "provider_capability_outcome": receipt.provider_capability_outcome.value,
        "provider_commit_attempted": False,
        "effect_applied": False,
        "effect_verified": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


__all__ = [
    "AzureVmStartShadowFenceBinding",
    "AzureVmStartShadowFenceProbe",
    "ProviderFenceShadowReceipt",
    "azure_vm_target_digest",
    "build_azure_vm_start_shadow_binding",
]
