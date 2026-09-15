"""Exact Core-identity metadata reads for independent handover source checks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg
from fdai_service_contracts.handover_knowledge import (
    HandoverKnowledgeNotice,
    knowledge_source_digest,
)
from psycopg.rows import dict_row

from fdai.core.human_assignment.model import AssignmentCase, AssignmentState
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig


@dataclass(frozen=True, slots=True)
class PostgresHandoverSourceReader:
    """Read exact goal metadata and an opaque source-admission boolean; no document writes."""

    config: PostgresStateStoreConfig

    async def read(self, notice: HandoverKnowledgeNotice) -> Mapping[str, Any] | None:
        """Retain private source attribution inside the reader/checker, not general events."""
        async with await self._connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT value FROM state_kv WHERE key = %s", (notice.source_key,)
                )
            ).fetchone()
        if row is None:
            return None
        if not isinstance(row["value"], Mapping):
            raise ValueError("handover source metadata is malformed")
        return dict(row["value"])

    async def document_admitted(
        self, notice: HandoverKnowledgeNotice, *, evidence_ref: str, digest: str
    ) -> bool:
        """Check the exact source-bound canonical citation without selecting document content."""
        parts = evidence_ref.split(":")
        if len(parts) != 3 or parts[0] != "doc":
            return False
        try:
            document_id, version_id = UUID(parts[1]), UUID(parts[2])
        except ValueError:
            return False
        if evidence_ref != f"doc:{document_id}:{version_id}":
            return False
        async with await self._connect() as connection:
            row = await (
                await connection.execute(
                    "SELECT fdai_verify_handover_source_document(%s, %s, %s, %s, %s) AS admitted",
                    (notice.source_key, notice.goal_revision, document_id, version_id, digest),
                )
            ).fetchone()
        return row is not None and row["admitted"] is True

    async def contribution_current(self, notice: HandoverKnowledgeNotice) -> bool:
        """Require the exact current duty projection and honor Core's negative revocation hold."""
        goal = await self.read(notice)
        if (
            goal is None
            or goal.get("goal_id") != notice.goal_id
            or goal.get("revision") != notice.goal_revision
            or knowledge_source_digest(goal) != notice.source_digest
        ):
            return False
        subject, agent, scope = (
            goal.get("subject_ref"),
            goal.get("agent_name"),
            goal.get("scope_ref"),
        )
        if not isinstance(subject, str) or not isinstance(agent, str) or not isinstance(scope, str):
            raise ValueError("handover source contribution identity is malformed")
        if notice.source == "operator" and scope != "scope:platform":
            return False
        async with await self._connect() as connection:
            rows = await (
                await connection.execute(
                    "SELECT value FROM state_kv WHERE starts_with(key, 'human_assignment:case:') "
                    "AND lower(value #>> '{intent,subject,subject_id}') = %s LIMIT 101",
                    (subject.casefold(),),
                )
            ).fetchall()
            if len(rows) > 100:
                raise ValueError("handover contribution evidence exceeds its read bound")
            cases = [AssignmentCase.from_dict(dict(row["value"])) for row in rows]
            relevant = [
                case
                for case in cases
                if case.intent.revocation is None
                and any(
                    duty.agent_name == agent and duty.scope_ref == scope
                    for duty in case.intent.duty_bindings
                )
            ]
            if any(
                case.revocation_case_id is not None and case.state is AssignmentState.DEGRADED
                for case in relevant
            ):
                return False
            active = [
                case
                for case in relevant
                if case.state is AssignmentState.ACTIVE and case.intent.subject.provider == "entra"
            ]
            if notice.source == "core":
                return any(case.case_id == goal.get("assignment_case_id") for case in active)
            if any(case.revocation_case_id is not None for case in relevant) and not active:
                return False
            row = await (
                await connection.execute(
                    "SELECT value FROM state_kv WHERE key = %s",
                    ("operator-projection:operations:stewardship.coverage",),
                )
            ).fetchone()
        projection = row["value"] if row is not None else None
        if not isinstance(projection, Mapping) or projection.get("_revision") != goal.get(
            "source_revision"
        ):
            return False
        duty_map = projection.get("map")
        if not isinstance(duty_map, Mapping) or not isinstance(duty_map.get("agents"), list):
            raise ValueError("handover current duty projection is malformed")
        return any(
            isinstance(entry, Mapping)
            and entry.get("name") == agent
            and isinstance(entry.get("stewards"), list)
            and any(
                isinstance(steward, Mapping)
                and steward.get("kind") == "user"
                and str(steward.get("id", "")).casefold() == subject.casefold()
                and steward.get("responsibility") == "accountable"
                for steward in entry["stewards"]
            )
            for entry in duty_map["agents"]
        )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        connection = await psycopg.AsyncConnection.connect(
            self.config.dsn,
            row_factory=dict_row,
            connect_timeout=self.config.connect_timeout_s,
        )
        try:
            await connection.set_read_only(True)
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self.config.statement_timeout_ms),),
            )
            role = await (await connection.execute("SELECT current_user AS role")).fetchone()
            if role is None or role["role"] != "fdai_core":
                raise PermissionError("handover source reader requires the Core SQL role")
        except BaseException:
            await connection.close()
            raise
        return connection


__all__ = ["PostgresHandoverSourceReader"]
