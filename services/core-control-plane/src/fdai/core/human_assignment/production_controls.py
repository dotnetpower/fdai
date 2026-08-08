"""Production capability status and observation-only assignment reconciliation."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.human_assignment.model import (
    AssignmentCase,
    AssignmentState,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.state_store import StateStore

_CASE_PREFIX = "human_assignment:case:"
_RECONCILIATION_PREFIX = "human_assignment:reconciliation:"
_LOGGER = logging.getLogger("fdai.human_assignment.reconciliation")


@dataclass(frozen=True, slots=True)
class AssignmentCapabilityStatus:
    available: bool
    enabled: bool
    mode: Mode
    unavailable_reason: str | None = None
    kill_switch_engaged: bool = False

    @property
    def can_mutate(self) -> bool:
        return (
            self.available
            and self.enabled
            and self.mode is Mode.ENFORCE
            and not self.kill_switch_engaged
        )


@dataclass(frozen=True, slots=True)
class AssignmentReconciliationItem:
    case_id: str
    state: AssignmentState
    revision: int
    next_step: str
    reason: str | None


class AssignmentReconciler:
    """Project held work for operator recovery without invoking a provider."""

    def __init__(self, *, store: StateStore, scan_limit: int = 500) -> None:
        if not 1 <= scan_limit <= 10_000:
            raise ValueError("assignment reconciliation scan_limit is invalid")
        self._store = store
        self._scan_limit = scan_limit

    async def plan(self, *, at: datetime | None = None) -> tuple[AssignmentReconciliationItem, ...]:
        timestamp = at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("assignment reconciliation timestamp MUST be timezone-aware")
        values, total = await self._store.read_state_page(
            _CASE_PREFIX,
            limit=self._scan_limit,
        )
        if total > len(values):
            _LOGGER.warning(
                "assignment_reconciliation_scan_truncated",
                extra={"limit": self._scan_limit, "observed": len(values), "total": total},
            )
        items: list[AssignmentReconciliationItem] = []
        for value in values:
            try:
                case = AssignmentCase.from_dict(dict(value))
            except ValueError as exc:
                _LOGGER.error(
                    "assignment_reconciliation_case_malformed",
                    extra={"exception_type": type(exc).__name__},
                )
                continue
            next_step = _next_step(case)
            if next_step is None:
                continue
            item = AssignmentReconciliationItem(
                case_id=case.case_id,
                state=case.state,
                revision=case.revision,
                next_step=next_step,
                reason=case.degraded_reason,
            )
            items.append(item)
            recorded_at = timestamp.astimezone(UTC).isoformat()
            await self._store.write_state_with_audit_if_absent(
                f"{_RECONCILIATION_PREFIX}{case.case_id}:{case.revision}",
                {
                    "case_id": case.case_id,
                    "revision": case.revision,
                    "state": case.state.value,
                    "next_step": next_step,
                    "observed_at": recorded_at,
                },
                {
                    "actor": "fdai.core.human_assignment.reconciler",
                    "action_kind": "human.assignment.reconciliation_observed",
                    "idempotency_key": f"assignment-reconcile:{case.case_id}:{case.revision}",
                    "case_id": case.case_id,
                    "state": case.state.value,
                    "next_step": next_step,
                    "mode": Mode.SHADOW.value,
                    "recorded_at": recorded_at,
                },
            )
        return tuple(items)


def assignment_capability_status(
    environment: Mapping[str, str],
    *,
    enabled: bool = True,
    mode: Mode = Mode.SHADOW,
    kill_switch_engaged: bool = False,
) -> AssignmentCapabilityStatus:
    required = (
        "FDAI_HUMAN_ACCESS_MI_CLIENT_ID",
        "FDAI_HUMAN_ACCESS_ROLE_GROUPS_JSON",
        "FDAI_STATE_STORE_DSN",
    )
    missing = [key for key in required if not environment.get(key, "").strip()]
    return AssignmentCapabilityStatus(
        available=not missing,
        enabled=enabled,
        mode=mode,
        unavailable_reason=("missing deployment prerequisites" if missing else None),
        kill_switch_engaged=kill_switch_engaged,
    )


def _next_step(case: AssignmentCase) -> str | None:
    if case.state is AssignmentState.OWNERSHIP_MERGED:
        return "request_iam_apply"
    if case.state is AssignmentState.IAM_APPLYING:
        return "verify_iam_membership"
    if case.state is AssignmentState.DEGRADED:
        return "operator_repair"
    return None


__all__ = [
    "AssignmentCapabilityStatus",
    "AssignmentReconciler",
    "AssignmentReconciliationItem",
    "assignment_capability_status",
]
