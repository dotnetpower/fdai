"""Server-prepared development action bindings: the trusted source for the development profile.

Core prepares one exact binding from its own built Action, deterministic dry-run receipt, and the
selected profile, then records it once with an audit entry. ``verify`` returns only a current
recorded binding; it never accepts a caller-supplied binding. The synchronous index is warmed from
durable state at startup, so a record missing from this process fails closed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from fdai.core.executor.direct_api import _build_direct_api_request, _direct_api_plan_digest
from fdai.core.executor.safeguards import SafeguardRefusal, evaluate_pre_dispatch
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.shared.contracts.development_authority import (
    authority_text_digest,
    canonical_authority_digest,
)
from fdai.shared.contracts.models import (
    Action,
    DevelopmentActionBinding,
    DevelopmentActionSafeguards,
    DevelopmentAuthorityScope,
    DevelopmentBindingVerification,
    ExecutionPath,
    FullAuthorityDevelopmentProfile,
    OntologyActionType,
)
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingRequest
from fdai.shared.providers.state_store import StateStore

BINDING_PREFIX = "development-binding:"
SOURCE_ID = "fdai-core-prepared-bindings"
# Matches the default HIL park approval window, so a parked binding outlives its approval.
DEFAULT_BINDING_TTL = timedelta(minutes=30)
AUDIT_CONTRACT = "fdai.saga.two-phase-audit@1"
# Constitution Article 7: inside the development profile, disposable-resource recreation or
# teardown is the bounded recovery path for every bound resource.
DISPOSABLE_RECOVERY_CONTRACT = "fdai.development.disposable-recreation@1"


def azure_scope_value_digest(value: str) -> str:
    """Digest one Azure tenant, subscription, or resource-group identifier case-insensitively."""
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("development scope identifier MUST be non-empty")
    return authority_text_digest(normalized)


def target_scope(
    profile: FullAuthorityDevelopmentProfile, target_ref: str
) -> DevelopmentAuthorityScope:
    """Derive the exact requested scope of one Azure resource ID inside the profile tenant."""
    parts = [part for part in target_ref.split("/") if part]
    lowered = [part.lower() for part in parts]
    try:
        subscription = parts[lowered.index("subscriptions") + 1]
    except (ValueError, IndexError):
        raise ValueError("development target MUST be an Azure resource ID") from None
    groups: tuple[str, ...] = ()
    if "resourcegroups" in lowered:
        index = lowered.index("resourcegroups") + 1
        if index >= len(parts):
            raise ValueError("development target resource group is missing")
        groups = (azure_scope_value_digest(parts[index]),)
    return DevelopmentAuthorityScope(
        tenant_digest=profile.scope.tenant_digest,
        subscription_digest=azure_scope_value_digest(subscription),
        resource_group_digests=groups,
    )


def _registered(profile: FullAuthorityDevelopmentProfile, action_type: OntologyActionType) -> bool:
    identity = (action_type.name, action_type.version, "sha256:" + action_type_digest(action_type))
    return identity in {
        (item.action_type, item.version, item.action_type_digest)
        for item in profile.registered_actions
    }


def direct_api_dry_run_digest(action: Action) -> str:
    """Return the digest of the deterministic direct-API dry-run receipt for ``action``."""
    request = _build_direct_api_request(action)
    receipt = evaluate_pre_dispatch(
        action,
        execution_path=ExecutionPath.DIRECT_API,
        plan_digest=_direct_api_plan_digest(request),
        plan_kind="direct_api_request",
    )
    if isinstance(receipt, SafeguardRefusal):
        raise ValueError(f"development dry-run refused: {receipt.reason}")
    return authority_text_digest(receipt.dry_run_receipt)


class PreparedDevelopmentBindingRegistry:
    """Record and verify exact server-prepared bindings for one selected profile."""

    def __init__(
        self,
        *,
        profile: FullAuthorityDevelopmentProfile,
        store: StateStore,
        clock: Callable[[], datetime],
        observer_principal: str = "agent:heimdall",
        ttl: timedelta = DEFAULT_BINDING_TTL,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("development binding TTL MUST be positive")
        self._profile = profile
        self._store = store
        self._clock = clock
        self._observer = observer_principal
        self._ttl = ttl
        self._index: dict[str, DevelopmentBindingVerification] = {}

    async def prepare(
        self,
        *,
        action: Action,
        action_type: OntologyActionType,
        target_revision: str,
        dry_run_digest: str,
    ) -> DevelopmentBindingVerification:
        """Record one exact binding, or return the identical binding already recorded."""
        profile = self._profile
        if action.action_type != action_type.name or not _registered(profile, action_type):
            raise ValueError("development action type is not registered in the profile")
        scope = target_scope(profile, action.target_resource_ref)
        if not profile.scope.covers(scope):
            raise ValueError("development target is outside the profile scope")
        target_digest = authority_text_digest(action.target_resource_ref)
        binding = DevelopmentActionBinding.build(
            action_type=action_type.name,
            action_type_version=action_type.version,
            action_type_digest="sha256:" + action_type_digest(action_type),
            action_id=str(action.action_id),
            target_digest=target_digest,
            target_revision=target_revision,
            scope=scope,
            source_revision=profile.source_revision,
            catalog_revision=profile.catalog_revision,
            policy_revision=profile.policy_revision,
            params_digest=canonical_authority_digest(action.params),
            dry_run_digest=dry_run_digest,
            requester_principal=profile.owner_principal,
            executor_principal=profile.executor_principal,
            safeguards=DevelopmentActionSafeguards(
                stop_condition_digest=canonical_authority_digest(
                    {
                        "stop_condition": action.stop_condition,
                        "stop_conditions": [
                            item.model_dump(mode="json") for item in action.stop_conditions
                        ],
                    }
                ),
                rollback_contract_digest=authority_text_digest(action.rollback_ref.kind.value),
                rollback_test_digest=canonical_authority_digest(
                    {
                        "recovery_contract": DISPOSABLE_RECOVERY_CONTRACT,
                        "scope": scope.model_dump(mode="json"),
                        "rollback_ref": action.rollback_ref.model_dump(mode="json"),
                    }
                ),
                blast_radius_digest=canonical_authority_digest(
                    action.blast_radius.model_dump(mode="json")
                ),
                logical_target_lock_digest=target_digest,
                idempotency_key=action.idempotency_key,
                two_phase_audit=True,
                audit_contract_digest=authority_text_digest(AUDIT_CONTRACT),
                observer_principal=self._observer,
                observer_source_digest=authority_text_digest(f"{self._observer}:{SOURCE_ID}"),
            ),
        )
        now = self._clock()
        verification = DevelopmentBindingVerification(
            binding=binding,
            source_id=SOURCE_ID,
            source_revision=profile.source_revision,
            verification_receipt_digest=canonical_authority_digest(
                {
                    "binding_digest": binding.digest,
                    "profile_digest": profile.digest,
                    "verified_at": now.isoformat(),
                }
            ),
            verified_at=now,
            expires_at=min(profile.valid_until, now + self._ttl),
            authoritative=True,
        )
        key = BINDING_PREFIX + binding.action_id
        record = verification.model_dump(mode="json")
        created = await self._store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "actor": "Var",
                "action_kind": "development_authority.binding_prepared",
                "correlation_id": binding.action_id,
                "profile_digest": profile.digest,
                "binding_digest": binding.digest,
                "execution_authority": False,
            },
        )
        if not created:
            existing = DevelopmentBindingVerification.model_validate(
                await self._store.read_state(key)
            )
            if existing.binding != binding:
                raise ValueError("a different development binding is already prepared")
            verification = existing
        self._index[binding.action_id] = verification
        return verification

    async def prepare_park_binding(
        self,
        *,
        action: Action,
        action_type: OntologyActionType,
        target_revision: str,
    ) -> DevelopmentBindingVerification:
        """Record the binding of one exact direct-API action about to be parked for approval."""
        if action_type.execution_path is not ExecutionPath.DIRECT_API:
            raise ValueError("development parking supports only direct-API actions")
        return await self.prepare(
            action=action,
            action_type=action_type,
            target_revision=target_revision,
            dry_run_digest=direct_api_dry_run_digest(action),
        )

    async def read_verification(self, action_id: str) -> DevelopmentBindingVerification | None:
        """Read the durable binding of ``action_id`` for this profile, bypassing the index."""
        row = await self._store.read_state(BINDING_PREFIX + action_id)
        verification = _verification_or_none(row)
        if (
            verification is None
            or verification.binding.action_id != action_id
            or verification.source_revision != self._profile.source_revision
        ):
            return None
        return verification

    def verify(
        self,
        request: DevelopmentAuthorityBindingRequest,
        *,
        now: datetime,
    ) -> DevelopmentBindingVerification | None:
        """Return the current recorded binding for this action, or ``None`` without authority."""
        verification = self._index.get(request.action_id)
        if verification is None or not verification.verified_at <= now < verification.expires_at:
            return None
        return verification

    async def load(self, *, limit: int = 200) -> int:
        """Warm the synchronous index with current recorded bindings of this profile."""
        rows, _ = await self._store.read_state_page(BINDING_PREFIX, limit=limit)
        now = self._clock()
        loaded = 0
        for row in rows:
            verification = _verification_or_none(row)
            if (
                verification is None
                or verification.source_revision != self._profile.source_revision
                or not verification.verified_at <= now < verification.expires_at
            ):
                continue
            self._index[verification.binding.action_id] = verification
            loaded += 1
        return loaded


def _verification_or_none(row: Any) -> DevelopmentBindingVerification | None:
    try:
        return DevelopmentBindingVerification.model_validate(row)
    except (TypeError, ValueError):
        return None


__all__ = [
    "AUDIT_CONTRACT",
    "BINDING_PREFIX",
    "DEFAULT_BINDING_TTL",
    "DISPOSABLE_RECOVERY_CONTRACT",
    "SOURCE_ID",
    "PreparedDevelopmentBindingRegistry",
    "azure_scope_value_digest",
    "direct_api_dry_run_digest",
    "target_scope",
]
