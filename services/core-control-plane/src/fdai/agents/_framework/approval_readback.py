"""Read-only admission of Var-owned durable approvals; no peer agent calls or decisions."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from fdai.agents._framework.action_run_identity import (
    action_run_identity_digest,
    approval_matches_action_run,
)
from fdai.agents._framework.development_authority import (
    admit_development_authority,
    development_grant,
)
from fdai.agents._framework.pantheon import PANTHEON_NAMES
from fdai.agents._framework.var_ticket_identity import approval_state_key
from fdai.shared.contracts.development_authority import normalized_principal
from fdai.shared.contracts.models import (
    FullAuthorityDevelopmentProfile,
)
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingSource
from fdai.shared.providers.state_store import StateStore


async def read_current_action_approval(
    *,
    store: StateStore,
    action_run: Mapping[str, Any],
    can_approve: Callable[[str, str], bool | Awaitable[bool]],
    clock: Callable[[], datetime],
    development_profile: FullAuthorityDevelopmentProfile | None = None,
    development_executor_principal: str | None = None,
    development_binding_source: DevelopmentAuthorityBindingSource | None = None,
    can_own: Callable[[str], bool | Awaitable[bool]] | None = None,
) -> tuple[str, ...]:
    """Require exact durable approval, current distinct human eligibility and the original TTL."""
    run = dict(action_run)
    correlation = str(run.get("correlation_id") or "")
    identity = action_run_identity_digest(run)
    expiry = run.get("approval_expires_at")
    expires_at = datetime.fromisoformat(expiry) if isinstance(expiry, str) else None
    now = clock()
    if (
        expires_at is None
        or expires_at.tzinfo is None
        or now.tzinfo is None
        or not now < expires_at
    ):
        raise ValueError("original ActionRun approval window is unavailable or expired")
    async with asyncio.timeout(5):
        stored = await store.read_state(approval_state_key(correlation, "final", identity))
        approval = stored.get("approval") if stored is not None else None
        if (
            stored is None
            or stored.get("schema_version") != "1.0.0"
            or stored.get("record_kind") != "final_approval"
            or stored.get("correlation_id") != correlation
            or stored.get("publication_status") not in {"pending", "published"}
            or not isinstance(approval, Mapping)
            or approval.get("producer_principal") != "Var"
            or approval.get("kind") != "action"
            or approval.get("state") != "approved"
            or approval.get("correlation_id") != correlation
            or not approval_matches_action_run(approval, run)
            or approval.get("params") != run.get("params")
        ):
            raise ValueError("current Var approval does not bind the original ActionRun")
        people = approval.get("approvers")
        quorum = run.get("quorum_required")
        development = admit_development_authority(
            profile=development_profile,
            binding_source=development_binding_source,
            evidence=run.get("development_authority"),
            action=run,
            executor_principal=development_executor_principal,
            original_quorum=int(run.get("original_quorum_required", quorum or 1)),
            now=clock(),
        )
        grant = development_grant(development)
        initiator = str(run.get("initiator_principal") or "").casefold()
        if (
            not isinstance(people, list)
            or not 1 <= len(people) <= 10
            or any(
                not isinstance(person, str) or not person or person != person.strip().casefold()
                for person in people
            )
            or len(set(people)) != len(people)
            or type(quorum) is not int
            or not 1 <= quorum <= len(people)
            or any(
                person in {name.casefold() for name in PANTHEON_NAMES}
                or person == initiator
                and (grant is None or normalized_principal(grant.owner_principal) != person)
                for person in people
            )
        ):
            raise ValueError("current Var approval lacks an independent human quorum")
        for person in people:
            authorized = can_approve(person, str(run["action_type"]))
            admitted = await authorized if inspect.isawaitable(authorized) else authorized
            if admitted is not True:
                raise PermissionError("human approval is no longer eligible for this ActionType")
            if grant is not None:
                current_owner = can_own(person) if can_own is not None else False
                owner_admitted = (
                    await current_owner if inspect.isawaitable(current_owner) else current_owner
                )
                if (
                    owner_admitted is not True
                    or len(people) != grant.effective_quorum
                    or normalized_principal(grant.owner_principal) != person
                ):
                    raise PermissionError(
                        "development approval is not a current sole-Owner decision"
                    )
        if not clock() < expires_at:
            raise ValueError("original approval expired during current role verification")
        if await store.read_state(approval_state_key(correlation, "final", identity)) != stored:
            raise ValueError("Var approval changed during current role verification")
        return tuple(people)
