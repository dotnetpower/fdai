"""Core-only current handover source and reviewer reads with no document-table privileges."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from fdai.core.human_assignment.model import AssignmentCase, AssignmentState
from fdai.core.stewardship import Duty
from fdai.delivery.identity.handover_review_identity import HandoverIdentityReader
from fdai.delivery.persistence.postgres_handover_admission import PostgresHandoverSourceReader


@dataclass(frozen=True, slots=True)
class PostgresCoreHandoverReview:
    """Bind Core goal admission and current reviewer eligibility to independently read facts.

    Owner or backup duty never supplies document access by itself. Reader backups need
    observed current role-group membership matching the exact document ACL. A subject
    may retrieve its own admitted document, but cannot review its own goal.
    """

    source: PostgresHandoverSourceReader
    identities: HandoverIdentityReader
    clock: Callable[[], datetime]

    async def verify_subject(self, *, subject_ref: str, assignment_case_id: str) -> bool:
        """Keep the provider namespace and active source-case fence through the human read."""
        async with asyncio.timeout(10):
            async with await self.source._connect() as connection:
                row = await (
                    await connection.execute(
                        "SELECT value FROM state_kv WHERE key=%s",
                        ("human_assignment:case:" + assignment_case_id,),
                    )
                ).fetchone()
            if row is None:
                return False
            case = AssignmentCase.from_dict(dict(row["value"]))
            if (
                case.case_id != assignment_case_id
                or case.state is not AssignmentState.ACTIVE
                or case.intent.revocation is not None
                or case.intent.subject.provider != "entra"
                or case.intent.subject.subject_id != subject_ref
            ):
                return False
            human = await self.identities.read(subject_ref)
            async with await self.source._connect() as connection:
                latest = await (
                    await connection.execute(
                        "SELECT value FROM state_kv WHERE key=%s",
                        ("human_assignment:case:" + assignment_case_id,),
                    )
                ).fetchone()
            return (
                human is not None
                and human.subject_ref == subject_ref
                and human.current(self.clock())
                and latest == row
            )

    async def verify(
        self,
        *,
        subject_ref: str,
        evidence_ref: str,
        digest: str,
        reviewer_ref: str,
    ) -> bool:
        """Return a restricted current-source/access boolean; errors remain unavailable."""
        identity = _document_identity(evidence_ref, digest)
        if identity is None:
            return False
        async with asyncio.timeout(10):
            subject = await self.identities.read(subject_ref)
            if subject is None or subject.subject_ref != subject_ref:
                return False
            reviewer = (
                subject if reviewer_ref == subject_ref else await self.identities.read(reviewer_ref)
            )
            if reviewer is None or reviewer.subject_ref != reviewer_ref:
                return False
            async with await self.source._connect() as connection:
                row = await (
                    await connection.execute(
                        "SELECT fdai_verify_core_handover_document_access("
                        "%s,%s,%s,%s,%s,%s,%s) AS admitted",
                        (
                            subject_ref,
                            *identity,
                            digest,
                            reviewer_ref,
                            list(reviewer.roles),
                            list(reviewer.group_ids),
                        ),
                    )
                ).fetchone()
            at = self.clock()
            return (
                row is not None
                and row["admitted"] is True
                and subject.current(at)
                and reviewer.current(at)
            )

    async def may_review(
        self,
        *,
        reviewer_ref: str,
        agent_name: str,
        scope_ref: str,
        role: Literal["owner", "backup"],
    ) -> bool:
        """Require a current ordinary role and, for backups, exact active unheld Core duties."""
        async with asyncio.timeout(10):
            human = await self.identities.read(reviewer_ref)
            if (
                human is None
                or human.subject_ref != reviewer_ref
                or not human.current(self.clock())
            ):
                return False
            if role == "owner":
                return "Owner" in human.roles
            if role != "backup":
                return False
            async with await self.source._connect() as connection:
                rows = await (
                    await connection.execute(
                        "SELECT value FROM state_kv "
                        "WHERE starts_with(key, 'human_assignment:case:') "
                        "AND lower(value #>> '{intent,subject,subject_id}') = %s LIMIT 101",
                        (reviewer_ref.casefold(),),
                    )
                ).fetchall()
            if len(rows) > 100:
                return False
            relevant = [
                case
                for row in rows
                if (case := AssignmentCase.from_dict(dict(row["value"]))).intent.revocation is None
                and case.intent.subject.provider == "entra"
                and case.intent.subject.subject_id == reviewer_ref
                and any(
                    binding.agent_name == agent_name
                    and binding.scope_ref == scope_ref
                    and binding.duty in {Duty.BACKUP, Duty.ESCALATION}
                    for binding in case.intent.duty_bindings
                )
            ]
            if any(
                case.revocation_case_id is not None and case.state is AssignmentState.DEGRADED
                for case in relevant
            ):
                return False
            return human.current(self.clock()) and any(
                case.state is AssignmentState.ACTIVE for case in relevant
            )


def _document_identity(reference: str, digest: str) -> tuple[UUID, UUID] | None:
    if not isinstance(reference, str) or not isinstance(digest, str):
        return None
    parts = reference.split(":")
    if len(parts) != 3 or parts[0] != "doc" or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
        return None
    try:
        identity = UUID(parts[1]), UUID(parts[2])
    except ValueError:
        return None
    return identity if reference == f"doc:{identity[0]}:{identity[1]}" else None


__all__ = ["PostgresCoreHandoverReview"]
