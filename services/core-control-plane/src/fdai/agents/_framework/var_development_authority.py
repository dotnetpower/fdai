"""Development Owner admission behind Var's existing approval role."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework.development_authority import (
    admit_development_authority,
    development_grant,
)
from fdai.agents._framework.var_decisions import PendingHilTicket
from fdai.shared.contracts.models.development_authority import (
    FullAuthorityDevelopmentProfile,
    normalized_principal,
)
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingSource

DevelopmentOwnerAuthorizer = Callable[[str], bool | Awaitable[bool]]


class VarDevelopmentAuthorityMixin:
    """Validate exact profile evidence without changing Var's AgentSpec."""

    _development_profile: FullAuthorityDevelopmentProfile | None
    _development_executor_principal: str | None
    _development_owner_authorizer: DevelopmentOwnerAuthorizer | None
    _development_binding_source: DevelopmentAuthorityBindingSource | None
    _clock: Callable[[], datetime]
    _record_blocked_attempt: Callable[[str, str, str], None]

    def _initialize_development_authority(
        self,
        *,
        profile: FullAuthorityDevelopmentProfile | None,
        executor_principal: str | None,
        owner_authorizer: DevelopmentOwnerAuthorizer | None,
        binding_source: DevelopmentAuthorityBindingSource | None,
        clock: Callable[[], datetime] | None,
    ) -> None:
        self._development_profile = profile
        self._development_executor_principal = executor_principal
        self._development_owner_authorizer = owner_authorizer
        self._development_binding_source = binding_source
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    def _admit_development_ticket(
        self,
        payload: Mapping[str, Any],
        *,
        quorum: int,
    ) -> tuple[int, int, dict[str, Any] | None]:
        original = payload.get("original_quorum_required", quorum)
        effective = payload.get("effective_quorum_required", quorum)
        if (
            isinstance(original, bool)
            or not isinstance(original, int)
            or original < 1
            or isinstance(effective, bool)
            or not isinstance(effective, int)
            or effective != quorum
        ):
            raise ValueError("development approval quorum is malformed")
        admitted = admit_development_authority(
            profile=self._development_profile,
            binding_source=self._development_binding_source,
            evidence=payload.get("development_authority"),
            action=payload,
            executor_principal=self._development_executor_principal,
            original_quorum=original,
            now=self._clock(),
        )
        grant = development_grant(admitted)
        if admitted is not None and (
            grant is None
            or quorum != grant.effective_quorum
            or effective != grant.effective_quorum
            or original != grant.original_quorum
        ):
            raise ValueError("development approval quorum does not match its grant")
        return original, effective, admitted

    async def _development_owner_eligible(
        self,
        ticket: PendingHilTicket,
        *,
        approver: str,
        correlation_id: str,
    ) -> bool:
        if ticket.development_authority is None:
            return False
        try:
            admitted = admit_development_authority(
                profile=self._development_profile,
                binding_source=self._development_binding_source,
                evidence=ticket.development_authority,
                action={
                    "action_type": ticket.action_type,
                    "action_id": ticket.action_id,
                    "resource_id": ticket.resource_id,
                    "params": ticket.params,
                    "idempotency_key": ticket.idempotency_key,
                    "rollback_contract": ticket.rollback_contract,
                    "initiator_principal": ticket.initiator_principal,
                },
                executor_principal=self._development_executor_principal,
                original_quorum=ticket.original_quorum_required or ticket.quorum_required,
                now=self._clock(),
            )
        except ValueError as exc:
            self._record_blocked_attempt(
                "development_authority_stale",
                correlation_id,
                approver,
            )
            raise PermissionError("development authority is no longer current") from exc
        grant = development_grant(admitted)
        authorizer = self._development_owner_authorizer
        result = authorizer(approver) if grant is not None and authorizer is not None else False
        authorized = await result if inspect.isawaitable(result) else result
        eligible = bool(
            grant is not None
            and authorized is True
            and normalized_principal(grant.owner_principal) == approver
        )
        if not eligible:
            self._record_blocked_attempt(
                "development_owner_unauthorized",
                correlation_id,
                approver,
            )
            raise PermissionError(
                f"principal {approver!r} is not the authenticated development Owner"
            )
        return True


__all__ = ["DevelopmentOwnerAuthorizer", "VarDevelopmentAuthorityMixin"]
