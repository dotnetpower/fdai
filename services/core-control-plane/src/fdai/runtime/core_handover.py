"""Current Core goal and search bindings over service-owned admission contracts.

Responsibility: Connect Core goal admission and current reviewer checks to actual source readers.
Boundary: No Operator implementation imports, raw document SELECT grants, or provider writes.
Authority and state: Goals remain Core-owned; source checks can hold but never self-approve.
Dependencies: Core StateStore, read workload identity, restricted SQL and current Entra directory.
Deployment: Same construction in every Core venue; no synthetic default or constructor network I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import yaml
from fdai_service_contracts import KnowledgeChunk
from fdai_service_contracts.handover_knowledge import HandoverKnowledgeNotice

from fdai.core.human_assignment.goals import HandoverGoalService
from fdai.core.human_assignment.knowledge_handover import (
    HandoverKnowledgeAccessContext,
    HandoverKnowledgeRetrieval,
)
from fdai.core.human_assignment.service import AssignmentCaseService
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.rbac.roles import Role
from fdai.delivery.identity.entra_directory import EntraHumanIdentityDirectory
from fdai.delivery.identity.handover_review_identity import CurrentHandoverIdentityReader
from fdai.delivery.identity.scoped_duty_directory import EntraDutySubjectResolver
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_core_handover_review import PostgresCoreHandoverReview
from fdai.delivery.persistence.postgres_core_handover_search import PostgresCoreHandoverSearch
from fdai.delivery.persistence.postgres_handover_admission import PostgresHandoverSourceReader
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity


@dataclass(frozen=True, slots=True)
class CoreHandoverServices:
    """Source-consumed Core goal service and exact-goal retrieval factory, not another runtime."""

    goals: HandoverGoalService
    admission: PostgresCoreHandoverReview
    source: PostgresHandoverSourceReader

    async def search(
        self,
        *,
        goal_id: str,
        question: str,
        access: HandoverKnowledgeAccessContext,
    ) -> tuple[KnowledgeChunk, ...]:
        """Use the actual current goal, restricted SQL query, and read-time ACL verifier."""
        goal = await self.goals.get_goal(goal_id)
        return await HandoverKnowledgeRetrieval(
            query=PostgresCoreHandoverSearch(self.source, self.goals, goal),
            admission=self.admission,
        ).search(goal=goal, question=question, access=access)


@dataclass(frozen=True, slots=True)
class CurrentCoreHandoverSource:
    """Preserve source namespaces while requiring bound Core goal checks for Core observations."""

    source: PostgresHandoverSourceReader
    core: CoreHandoverServices | None

    async def read(self, notice: HandoverKnowledgeNotice) -> Mapping[str, Any] | None:
        """Read the exact source unchanged; never rewrite legacy acceptance during observation."""
        return await self.source.read(notice)

    async def document_admitted(
        self,
        notice: HandoverKnowledgeNotice,
        *,
        evidence_ref: str,
        digest: str,
    ) -> bool:
        """Keep the existing source-bound boolean and its independent withdrawal semantics."""
        return await self.source.document_admitted(notice, evidence_ref=evidence_ref, digest=digest)

    async def contribution_current(self, notice: HandoverKnowledgeNotice) -> bool:
        """Actual knowledge-owner source consumption invokes the bound Core service after
        identity checks.
        """
        if not await self.source.contribution_current(notice):
            return False
        if notice.source == "core":
            if self.core is None:
                raise ValueError(
                    "current Core handover admission and reviewer bindings are unavailable"
                )
            goal = await self.core.goals.get_goal(notice.goal_id)
            if goal.revision != notice.goal_revision:
                return False
            await self.core.goals.require_current_evidence(goal)
        return True


def build_core_handover_services(
    *,
    store: StateStore,
    environment: Mapping[str, str],
    catalog_root: Path | None,
    http_client: httpx.AsyncClient | None,
    identity: WorkloadIdentity | None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CoreHandoverServices | None:
    """Bind only the current Core read identity and same-venue SQL; missing prerequisites hold."""
    dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn or catalog_root is None or http_client is None or identity is None:
        return None
    mapping = GroupMapping.from_config(
        yaml.safe_load(
            (catalog_root.parent / "config/rbac-groups.yaml").read_text(encoding="utf-8")
        ),
        environ=environment,
    )
    subjects = EntraDutySubjectResolver(
        http_client, identity, None, clock, timedelta(minutes=5), 5.0
    )
    identities = CurrentHandoverIdentityReader(
        subjects,
        EntraHumanIdentityDirectory(
            http_client,
            identity,
            application_id=environment.get("FDAI_API_AUDIENCE") or None,
            max_attempts=1,
            roster_cache_seconds=0,
        ),
        {
            role.value: group
            for group, role in mapping.as_dict().items()
            if role is not Role.BREAK_GLASS
        },
        clock,
    )
    source = PostgresHandoverSourceReader(PostgresStateStoreConfig(dsn=dsn))
    admission = PostgresCoreHandoverReview(source, identities, clock)
    return CoreHandoverServices(
        HandoverGoalService(
            store=store,
            assignments=AssignmentCaseService(store),
            evidence_admission=admission,
            review_eligibility=admission,
            clock=clock,
        ),
        admission,
        source,
    )


__all__ = ["CoreHandoverServices", "CurrentCoreHandoverSource", "build_core_handover_services"]
