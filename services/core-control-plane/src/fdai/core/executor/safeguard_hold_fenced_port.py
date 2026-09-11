"""Hold-fenced dispatch port used inside the held logical-target lock.

Dispatch is fenced immediately before the provider is invoked, so an
automation hold that was reissued or re-released between authorization and
invocation denies the dispatch instead of racing it (#640).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from fdai.core.executor.hold_dispatch_fence import (
    HoldFenceAuditResult,
    HoldFenceCheckResult,
    HoldLineage,
    recheck_hold_fence,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
    SafeguardDispatchEvidenceRecord,
)
from fdai.core.executor.safeguard_evidence_lifecycle import DispatchPort
from fdai.shared.providers.automation_hold_state import (
    AutomationHoldStateReader,
    HoldReleaseAuthorizationReader,
)
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)


class HoldFencedDispatchPort:
    """Recheck automation-hold state inside the held lock before invocation.

    The expected release lineage comes from the immutable authorization bound
    when the hold was released for this exact action, so a hold reissued and
    re-released between authorization and provider invocation denies dispatch
    instead of racing it (#640). Deriving lineage from the current hold record
    would make the fence agree with whatever release happens to be newest.
    """

    __slots__ = (
        "_inner",
        "_hold_state_reader",
        "_lineage_reader",
        "_workflow_lineage",
        "_target_ref",
        "_target_digest",
        "_lock_ownership_token",
        "_denial_audit_store",
        "_actor",
        "_action_id",
        "_clock",
    )

    def __init__(
        self,
        *,
        inner: DispatchPort,
        hold_state_reader: AutomationHoldStateReader | None,
        lineage_reader: HoldReleaseAuthorizationReader | None,
        workflow_lineage: tuple[str, str] | None,
        target_ref: str,
        target_digest: str,
        lock_ownership_token: str,
        denial_audit_store: StateStore,
        actor: str,
        action_id: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._inner = inner
        self._hold_state_reader = hold_state_reader
        self._lineage_reader = lineage_reader
        self._workflow_lineage = workflow_lineage
        self._target_ref = target_ref
        self._target_digest = target_digest
        self._lock_ownership_token = lock_ownership_token
        self._denial_audit_store = denial_audit_store
        self._actor = actor
        self._action_id = action_id
        self._clock = clock

    async def dispatch(
        self,
        *,
        evidence_record: SafeguardDispatchEvidenceRecord,
        started_at: datetime,
    ) -> tuple[
        DispatchTransportState,
        AuthoritativeSinkState,
        str | None,
        str | None,
    ]:
        """Fence the target, then delegate exactly once when it stays eligible."""

        check = await self._recheck()
        if check is not None and not check.eligible:
            audit = HoldFenceAuditResult.create(
                check_result=check,
                recorded_at=self._clock(),
            )
            await self._denial_audit_store.append_audit_entry(
                {
                    "action_id": self._action_id,
                    "actor": self._actor,
                    "action_kind": "executor.hold_dispatch_fence.denied",
                    "audit_phase": "pre-dispatch",
                    "outcome": "not_invoked",
                    "target_digest": audit.target_digest,
                    "hold_state": audit.hold_state.value,
                    "rejection_reasons": [reason.value for reason in audit.rejection_reasons],
                    "audit_digest": audit.audit_digest,
                    "recorded_at": audit.recorded_at.isoformat(),
                    "execution_authority": False,
                    "effect_verified": False,
                }
            )
            return (
                DispatchTransportState.FAILED,
                AuthoritativeSinkState.NOT_ACCEPTED,
                None,
                audit.audit_digest,
            )
        return await self._inner.dispatch(
            evidence_record=evidence_record,
            started_at=started_at,
        )

    async def _recheck(self) -> HoldFenceCheckResult | None:
        reader = self._hold_state_reader
        if reader is None:
            return None
        try:
            authorization = await self._authorization()
        except Exception:  # noqa: BLE001 - an unreadable authorization fails closed
            _LOGGER.exception(
                "hold_dispatch_fence_authorization_read_failed",
                extra={"action_id": self._action_id},
            )
            return self._unreadable_check()
        expected_lineage = _released_lineage(authorization)
        authorized_hold_revision = _authorized_hold_revision(authorization)
        if (
            authorization is not None
            and expected_lineage is None
            and (authorized_hold_revision is None)
        ):
            # An authorization exists but cannot be reconstructed: never treat
            # unusable evidence as "no authorization".
            return self._unreadable_check()
        record: Mapping[str, Any] | None
        try:
            record = await reader.read_hold_record(target_ref=self._target_ref)
        except Exception:  # noqa: BLE001 - an unreadable hold fails dispatch closed
            _LOGGER.exception(
                "hold_dispatch_fence_read_failed",
                extra={"action_id": self._action_id},
            )
            return self._unreadable_check()
        if record is None and authorization is None:
            return None
        return recheck_hold_fence(
            target_digest=self._target_digest,
            hold_record=dict(record) if record is not None else None,
            expected_lineage=expected_lineage,
            lock_ownership_token=self._lock_ownership_token,
            checked_at=self._clock(),
            authorized_hold_revision=authorized_hold_revision,
        )

    def _unreadable_check(self) -> HoldFenceCheckResult:
        return recheck_hold_fence(
            target_digest=self._target_digest,
            hold_record=_UNREADABLE_HOLD,
            expected_lineage=None,
            lock_ownership_token=self._lock_ownership_token,
            checked_at=self._clock(),
        )

    async def _authorization(self) -> Mapping[str, Any] | None:
        reader = self._lineage_reader
        lineage = self._workflow_lineage
        if reader is None or lineage is None:
            return None
        process_id, step_id = lineage
        return await reader.read_dispatch_authorization(
            target_ref=self._target_ref,
            process_id=process_id,
            step_id=step_id,
        )


_UNREADABLE_HOLD = object()
_HOLD_SCOPED_AUTHORIZATION = "hold_scoped"
_RELEASED_AUTHORIZATION = "released"


def _authorized_hold_revision(record: object) -> int | None:
    """Return the exact active hold revision one step may dispatch under."""

    if not isinstance(record, Mapping):
        return None
    if record.get("authorization_kind") != _HOLD_SCOPED_AUTHORIZATION:
        return None
    revision = record.get("authorized_hold_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        return None
    return revision


def _released_lineage(record: object) -> HoldLineage | None:
    """Rebuild the release lineage one step was explicitly authorized under.

    The reader owns the target and step binding, so this helper only
    reconstructs the content-addressed lineage the authorization recorded.
    """

    if not isinstance(record, Mapping):
        return None
    if record.get("authorization_kind") != _RELEASED_AUTHORIZATION:
        return None
    receipt_digest = record.get("release_receipt_digest")
    released_hold_revision = record.get("released_hold_revision")
    fencing_generation = record.get("fencing_generation")
    if (
        not isinstance(receipt_digest, str)
        or not isinstance(fencing_generation, int)
        or isinstance(fencing_generation, bool)
        or not isinstance(released_hold_revision, int)
        or isinstance(released_hold_revision, bool)
    ):
        return None
    try:
        return HoldLineage.create(
            release_receipt_digest=receipt_digest,
            released_hold_revision=released_hold_revision,
            fencing_generation=fencing_generation,
        )
    except ValueError:
        return None


__all__ = ["HoldFencedDispatchPort"]
