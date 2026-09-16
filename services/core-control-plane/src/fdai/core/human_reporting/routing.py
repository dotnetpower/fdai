"""Deterministic nearest-eligible-ancestor approval routing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.hil_escalation import EscalationDuty, EscalationRung
from fdai.core.human_reporting.graph import ReportingGraphSnapshot
from fdai.core.human_reporting.model import (
    ReportingLineModelError,
    normalize_principal,
    reporting_instant,
)


class ReportLineRouteUnavailableError(PermissionError):
    """Raised when a current reporting path cannot satisfy the approval quorum."""


class ReportingGraphReader(Protocol):
    """Read the complete current reviewed graph."""

    async def current_graph(self, *, at: datetime | None = None) -> ReportingGraphSnapshot: ...


class ReportingLineEligibility(Protocol):
    """Recheck one ancestor against current role and action policy evidence."""

    async def is_eligible(
        self,
        *,
        subject_ref: str,
        minimum_role: str,
        action_type: str,
        scope_ref: str,
        at: datetime,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class ReportLineRoutePlan:
    """One immutable report-line route proposal with no approval authority."""

    requester_ref: str
    action_type: str
    scope_ref: str
    minimum_role: str
    quorum: int
    graph_revision: str
    path_case_ids: tuple[str, ...]
    rungs: tuple[EscalationRung, ...]
    planned_at: datetime

    @property
    def digest(self) -> str:
        material = {
            "requester_ref": self.requester_ref,
            "action_type": self.action_type,
            "scope_ref": self.scope_ref,
            "minimum_role": self.minimum_role,
            "quorum": self.quorum,
            "graph_revision": self.graph_revision,
            "path_case_ids": list(self.path_case_ids),
            "rungs": [
                {
                    "subject_ref": rung.subject_ref,
                    "duty": rung.duty.value,
                    "minimum_role": rung.minimum_role,
                }
                for rung in self.rungs
            ],
        }
        return hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "requester_ref": self.requester_ref,
            "action_type": self.action_type,
            "scope_ref": self.scope_ref,
            "minimum_role": self.minimum_role,
            "quorum": self.quorum,
            "graph_revision": self.graph_revision,
            "path_case_ids": list(self.path_case_ids),
            "rungs": [
                {
                    "subject_ref": rung.subject_ref,
                    "duty": rung.duty.value,
                    "minimum_role": rung.minimum_role,
                }
                for rung in self.rungs
            ],
            "planned_at": self.planned_at.isoformat(),
            "route_digest": self.digest,
            "approval_authority": False,
        }


@dataclass(frozen=True, slots=True)
class ReportLineRoutingPolicy:
    """ActionType allowlist for report-line routing; absence preserves existing routes."""

    action_types: frozenset[str]
    quorum_by_action: Mapping[str, int]

    def __post_init__(self) -> None:
        if any(not item or item != item.strip() for item in self.action_types):
            raise ValueError("report-line ActionType ids MUST be exact")
        if set(self.quorum_by_action) - set(self.action_types):
            raise ValueError("report-line quorum policy references an unselected ActionType")
        if any(
            isinstance(value, bool) or not 1 <= value <= 4
            for value in self.quorum_by_action.values()
        ):
            raise ValueError("report-line quorum MUST be in [1, 4]")

    def selects(self, action_type: str) -> bool:
        return action_type in self.action_types

    def quorum_for(self, action_type: str) -> int:
        return self.quorum_by_action.get(action_type, 1)


@dataclass(frozen=True, slots=True)
class ReportLineApprovalRouter:
    """Resolve only current eligible ancestors and never broaden implicitly."""

    graphs: ReportingGraphReader
    eligibility: ReportingLineEligibility
    policy: ReportLineRoutingPolicy
    maximum_depth: int = 8

    async def plan(
        self,
        *,
        requester_ref: str,
        action_type: str,
        scope_ref: str,
        minimum_role: str,
        at: datetime,
    ) -> ReportLineRoutePlan | None:
        """Return ``None`` when the ActionType does not select report-line routing."""

        if not self.policy.selects(action_type):
            return None
        planned_at = reporting_instant(at)
        requester = normalize_principal(requester_ref)
        try:
            graph = await self.graphs.current_graph(at=planned_at)
            path = graph.manager_chain(requester, maximum_depth=self.maximum_depth)
        except ReportingLineModelError as exc:
            raise ReportLineRouteUnavailableError(
                "current reporting line is invalid or exceeds its traversal bound"
            ) from exc
        quorum = self.policy.quorum_for(action_type)
        rungs: list[EscalationRung] = []
        for edge in path:
            if await self.eligibility.is_eligible(
                subject_ref=edge.manager_ref,
                minimum_role=minimum_role,
                action_type=action_type,
                scope_ref=scope_ref,
                at=planned_at,
            ):
                rungs.append(
                    EscalationRung(
                        subject_ref=edge.manager_ref,
                        duty=(EscalationDuty.PRIMARY if not rungs else EscalationDuty.ESCALATION),
                        minimum_role=minimum_role,
                    )
                )
        if len(rungs) < quorum:
            raise ReportLineRouteUnavailableError(
                "current reporting line cannot satisfy the required approval quorum"
            )
        return ReportLineRoutePlan(
            requester_ref=requester,
            action_type=action_type,
            scope_ref=scope_ref,
            minimum_role=minimum_role,
            quorum=quorum,
            graph_revision=graph.revision,
            path_case_ids=tuple(edge.case_id for edge in path),
            rungs=tuple(rungs),
            planned_at=planned_at,
        )


__all__ = [
    "ReportLineApprovalRouter",
    "ReportLineRoutePlan",
    "ReportLineRouteUnavailableError",
    "ReportLineRoutingPolicy",
    "ReportingGraphReader",
    "ReportingLineEligibility",
]
