"""Trusted deployment source for current development-authority bindings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from fdai.shared.contracts.development_authority import (
    authority_text_digest,
    canonical_authority_digest,
    normalized_principal,
)
from fdai.shared.contracts.models import (
    Action,
    DevelopmentBindingVerification,
    OntologyActionType,
)


@dataclass(frozen=True, slots=True)
class DevelopmentAuthorityBindingRequest:
    """Actual immutable operation fields supplied by a server-owned caller."""

    action_type: str
    action_id: str
    target_ref: str
    params_json: str
    requester_principal: str
    executor_principal: str
    idempotency_key: str
    rollback_contract: str

    @classmethod
    def from_action(
        cls,
        *,
        action_type: str,
        action_id: str,
        target_ref: str,
        params: dict[str, Any],
        requester_principal: str,
        executor_principal: str,
        idempotency_key: str,
        rollback_contract: str,
    ) -> DevelopmentAuthorityBindingRequest:
        """Canonicalize actual parameters instead of accepting their digest."""

        params_json = json.dumps(
            params,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        request = cls(
            action_type=action_type,
            action_id=action_id,
            target_ref=target_ref,
            params_json=params_json,
            requester_principal=requester_principal,
            executor_principal=executor_principal,
            idempotency_key=idempotency_key,
            rollback_contract=rollback_contract,
        )
        if any(
            not value or value != value.strip()
            for value in (
                request.action_type,
                request.action_id,
                request.target_ref,
                request.requester_principal,
                request.executor_principal,
                request.idempotency_key,
                request.rollback_contract,
            )
        ):
            raise ValueError("development binding request identity MUST be complete")
        return request

    @property
    def params(self) -> dict[str, Any]:
        loaded = json.loads(self.params_json)
        if not isinstance(loaded, dict):  # pragma: no cover - factory guarantees object
            raise ValueError("development binding params MUST be an object")
        return loaded

    @property
    def digest(self) -> str:
        return canonical_authority_digest(
            {
                "action_type": self.action_type,
                "action_id": self.action_id,
                "target_ref": self.target_ref,
                "params_json": self.params_json,
                "requester_principal": self.requester_principal,
                "executor_principal": self.executor_principal,
                "idempotency_key": self.idempotency_key,
                "rollback_contract": self.rollback_contract,
            }
        )


@runtime_checkable
class DevelopmentAuthorityBindingSource(Protocol):
    """Resolve one current binding from authoritative deployment evidence."""

    def verify(
        self,
        request: DevelopmentAuthorityBindingRequest,
        *,
        now: datetime,
    ) -> DevelopmentBindingVerification | None:
        """Return a current verified binding, or ``None`` without authority."""


@runtime_checkable
class DevelopmentBindingPreparer(Protocol):
    """Record exact Core-prepared bindings and read them back from durable state."""

    async def prepare_park_binding(
        self,
        *,
        action: Action,
        action_type: OntologyActionType,
        target_revision: str,
    ) -> DevelopmentBindingVerification:
        """Record one binding of the exact parked action, or raise without authority."""
        ...

    async def read_verification(self, action_id: str) -> DevelopmentBindingVerification | None:
        """Return the durable recorded binding of one action, never a cached copy."""
        ...


@dataclass(frozen=True, slots=True)
class RecordedDevelopmentBinding:
    """Binding source over one verification the caller just read from durable state."""

    verification: DevelopmentBindingVerification

    def verify(
        self,
        request: DevelopmentAuthorityBindingRequest,
        *,
        now: datetime,
    ) -> DevelopmentBindingVerification | None:
        """Return the recorded binding only for its own action."""
        del now
        binding = self.verification.binding
        return self.verification if binding.action_id == request.action_id else None


def resolve_development_binding(
    source: DevelopmentAuthorityBindingSource | None,
    request: DevelopmentAuthorityBindingRequest,
    *,
    now: datetime,
) -> DevelopmentBindingVerification:
    """Require a current source result matching every actual operation field."""

    if source is None:
        raise ValueError("development authority binding source is unavailable")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("development authority clock is not trusted")
    resolved = source.verify(request, now=now)
    if resolved is None:
        raise ValueError("development authority binding is unavailable")
    verification = DevelopmentBindingVerification.model_validate(resolved.model_dump(mode="python"))
    evaluated_at = now.astimezone(UTC)
    binding = verification.binding
    if not verification.verified_at <= evaluated_at < verification.expires_at:
        raise ValueError("development authority binding verification is stale")
    if (
        binding.action_type != request.action_type
        or binding.action_id != request.action_id
        or binding.target_digest != authority_text_digest(request.target_ref)
        or binding.params_digest != canonical_authority_digest(request.params)
        or normalized_principal(binding.requester_principal)
        != normalized_principal(request.requester_principal)
        or normalized_principal(binding.executor_principal)
        != normalized_principal(request.executor_principal)
        or binding.safeguards.idempotency_key != request.idempotency_key
        or binding.safeguards.rollback_contract_digest
        != authority_text_digest(request.rollback_contract)
    ):
        raise ValueError("trusted development binding does not match current operation")
    return verification


__all__ = [
    "DevelopmentAuthorityBindingRequest",
    "DevelopmentAuthorityBindingSource",
    "DevelopmentBindingPreparer",
    "RecordedDevelopmentBinding",
    "resolve_development_binding",
]
