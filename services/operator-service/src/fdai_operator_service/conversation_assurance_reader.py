"""Project principal-scoped conversation assurance records for the Console.

Responsibility: Read assurance assessments and disputes from their durable PostgreSQL ledger.
Boundary: The adapter delegates non-assurance conversation operations unchanged.
Authority and state: Read-only; dispute writes continue through the existing proposal boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

import psycopg
from psycopg.rows import dict_row

from fdai_operator_service.conversation_assurance_diagnostics import pantheon_projection
from fdai_operator_service.families.conversation.contracts import (
    ConversationEventStream,
    ConversationProjectionReader,
    ConversationProposal,
    ConversationProposalOutbox,
    ConversationQuery,
    ConversationResponse,
    ConversationStreamReader,
    ConversationStreamRequest,
    ConversationUnavailableError,
    JsonObject,
    OutboxReceipt,
)


class ConversationAssuranceFallback(
    ConversationProjectionReader,
    ConversationProposalOutbox,
    ConversationStreamReader,
    Protocol,
):
    """Combined conversation dependency delegated by the assurance reader."""


@dataclass(frozen=True, slots=True)
class ConversationAssuranceReaderConfig:
    """Configure bounded assurance-ledger reads."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10


@dataclass(frozen=True, slots=True)
class ConversationAssuranceReader:
    """Add durable assurance reads to an existing conversation adapter."""

    config: ConversationAssuranceReaderConfig
    fallback: ConversationAssuranceFallback

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        """Read assurance list/detail projections or delegate another operation."""
        if query.operation == "assurance.list":
            return ConversationResponse(body=await self._list(query.scope.subject_id))
        if query.operation == "assurance.get":
            assessment_id = str(query.path_params.get("assessment_id", ""))
            detail = await self._detail(query.scope.subject_id, assessment_id)
            if detail is None:
                return ConversationResponse(
                    body={
                        "error": {
                            "status": 404,
                            "message": "conversation assurance assessment was not found",
                        }
                    },
                    status_code=404,
                )
            return ConversationResponse(body=detail)
        return await self.fallback.read(query)

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        """Delegate proposal writes without changing their authority boundary."""
        return await self.fallback.append(proposal)

    async def open(self, request: ConversationStreamRequest) -> ConversationEventStream:
        """Delegate stream operations unchanged."""
        return await self.fallback.open(request)

    async def _list(self, principal_scope: str) -> JsonObject:
        assessment_rows = await self._assessment_rows(principal_scope, limit=1_000)
        disputes = await self._dispute_rows(principal_scope, limit=200)
        summary_rows = await self._summary_rows(principal_scope)
        if len(summary_rows) != 1:
            raise ConversationUnavailableError("conversation assurance summary is unavailable")
        summary = summary_rows[0]
        projected_diagnostics = [_assessment(row, include_pantheon=True) for row in assessment_rows]
        projected = [_assessment(row, include_pantheon=False) for row in assessment_rows[:200]]
        return cast(
            JsonObject,
            {
                "source": "postgresql:conversation_assurance",
                "read_only": True,
                "disputes_available": True,
                "policy_mutations_available": False,
                "summary": {
                    "total": _integer(summary["total"], "conversation assurance total"),
                    "pass": _integer(summary["pass"], "conversation assurance pass count"),
                    "fail": _integer(summary["fail"], "conversation assurance fail count"),
                    "inconclusive": _integer(
                        summary["inconclusive"],
                        "conversation assurance inconclusive count",
                    ),
                    "deferred": _integer(
                        summary["deferred"],
                        "conversation assurance deferred count",
                    ),
                    "disputes": _integer(
                        summary["disputes"],
                        "conversation assurance dispute count",
                    ),
                    "average_content_score": (
                        None
                        if summary["average_content_score"] is None
                        else _number(
                            summary["average_content_score"],
                            "conversation assurance average score",
                        )
                    ),
                    "model_calls": _integer(
                        summary["model_calls"],
                        "conversation assurance model calls",
                    ),
                    "cost_microusd": _integer(
                        summary["cost_microusd"],
                        "conversation assurance cost",
                    ),
                },
                "pantheon": pantheon_projection(projected_diagnostics),
                "assessments": projected,
                "disputes": [_dispute(row) for row in disputes],
            },
        )

    async def _summary_rows(self, principal_scope: str) -> list[dict[str, Any]]:
        return await self._fetch_all(
            "SELECT COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE decision->>'verdict' = 'pass') AS pass, "
            "COUNT(*) FILTER (WHERE decision->>'verdict' = 'fail') AS fail, "
            "COUNT(*) FILTER (WHERE decision->>'verdict' = 'inconclusive') AS inconclusive, "
            "COUNT(*) FILTER (WHERE state = 'deferred') AS deferred, "
            "AVG((decision->>'content_score')::double precision) AS average_content_score, "
            "COALESCE(SUM((decision->>'model_calls')::bigint), 0)::bigint AS model_calls, "
            "COALESCE(SUM((decision->>'cost_microusd')::bigint), 0)::bigint AS cost_microusd, "
            "(SELECT COUNT(*) FROM conversation_assurance_dispute "
            "WHERE principal_scope = %s) AS disputes "
            "FROM conversation_assurance_assessment WHERE principal_scope = %s",
            (principal_scope, principal_scope),
        )

    async def _detail(
        self,
        principal_scope: str,
        assessment_id: str,
    ) -> JsonObject | None:
        rows = await self._assessment_rows(
            principal_scope,
            limit=1,
            assessment_id=assessment_id,
        )
        if not rows:
            return None
        return cast(
            JsonObject,
            {
                "assessment": _assessment(rows[0]),
                "turn": {"available": False, "question": None, "answer": None},
            },
        )

    async def _assessment_rows(
        self,
        principal_scope: str,
        *,
        limit: int,
        assessment_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if assessment_id is None:
            statement = (
                "SELECT assessment_id, turn_id, conversation_id, rubric_version, state, "
                "decision, assessed_at "
                "FROM conversation_assurance_assessment WHERE principal_scope = %s "
                "ORDER BY assessed_at DESC, assessment_id LIMIT %s"
            )
            parameters: tuple[object, ...] = (principal_scope, limit)
        else:
            statement = (
                "SELECT assessment_id, turn_id, conversation_id, rubric_version, state, "
                "decision, assessed_at "
                "FROM conversation_assurance_assessment "
                "WHERE principal_scope = %s AND assessment_id = %s LIMIT 1"
            )
            parameters = (principal_scope, assessment_id)
        return await self._fetch_all(statement, parameters)

    async def _dispute_rows(
        self,
        principal_scope: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        return await self._fetch_all(
            "SELECT dispute_id, assessment_id, reason, detail, evidence_refs, reported_at "
            "FROM conversation_assurance_dispute WHERE principal_scope = %s "
            "ORDER BY reported_at DESC, dispute_id LIMIT %s",
            (principal_scope, limit),
        )

    async def _fetch_all(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> list[dict[str, Any]]:
        try:
            async with await psycopg.AsyncConnection.connect(
                _psycopg_dsn(self.config.dsn),
                row_factory=dict_row,
                connect_timeout=self.config.connect_timeout_s,
            ) as connection:
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(self.config.statement_timeout_ms),),
                )
                cursor = await connection.execute(statement, parameters)
                return list(await cursor.fetchall())
        except psycopg.Error as exc:
            raise ConversationUnavailableError(
                "authoritative conversation assurance projection is unavailable"
            ) from exc


def _assessment(
    row: Mapping[str, object],
    *,
    include_pantheon: bool = True,
) -> dict[str, object]:
    decision = _mapping(row["decision"], "conversation assurance decision")
    required = {
        "verdict",
        "content_score",
        "confidence",
        "criteria",
        "reasons",
        "evaluator_identities",
        "disagreement",
        "model_calls",
        "prompt_tokens",
        "completion_tokens",
        "cost_microusd",
    }
    missing = sorted(required - decision.keys())
    if missing:
        raise ConversationUnavailableError(
            f"conversation assurance decision is missing fields: {', '.join(missing)}"
        )
    projected_decision = dict(decision)
    if not include_pantheon:
        projected_decision.pop("pantheon_diagnostic", None)
    return {
        "assessment_id": str(row["assessment_id"]),
        "turn_id": str(row["turn_id"]),
        "conversation_id": str(row["conversation_id"]),
        "state": str(row["state"]),
        **projected_decision,
        "rubric_version": str(row["rubric_version"]),
        "assessed_at": _timestamp(row["assessed_at"]),
    }


def _dispute(row: Mapping[str, object]) -> dict[str, object]:
    evidence_refs = row["evidence_refs"]
    if not isinstance(evidence_refs, list) or any(
        not isinstance(item, str) for item in evidence_refs
    ):
        raise ConversationUnavailableError("conversation assurance dispute is malformed")
    return {
        "dispute_id": str(row["dispute_id"]),
        "assessment_id": str(row["assessment_id"]),
        "reason": str(row["reason"]),
        "detail": str(row["detail"]),
        "evidence_refs": evidence_refs,
        "reported_at": _timestamp(row["reported_at"]),
    }


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ConversationUnavailableError(f"{label} is malformed")
    return dict(value)


def _number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConversationUnavailableError(f"{label} is malformed")
    return float(value)


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConversationUnavailableError(f"{label} is malformed")
    return value


def _timestamp(value: object) -> str:
    if not isinstance(value, datetime):
        raise ConversationUnavailableError("conversation assurance timestamp is malformed")
    return value.isoformat()


def _psycopg_dsn(value: str) -> str:
    prefix = "postgresql+psycopg://"
    normalized = f"postgresql://{value[len(prefix) :]}" if value.startswith(prefix) else value
    if normalized in {"postgres://", "postgresql://"}:
        raise ValueError("PostgreSQL DSN MUST include a connection target")
    return normalized


__all__ = ["ConversationAssuranceReader", "ConversationAssuranceReaderConfig"]
