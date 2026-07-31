"""PostgreSQL append-only storage for conversation assurance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.core.conversation_assurance import (
    AssessmentRecord,
    AssessmentState,
    AssuranceCriterion,
    AssuranceDecision,
    AssuranceVerdict,
    CriterionScore,
    DisputeReason,
    DisputeRecord,
)
from fdai.core.conversation_assurance.ledger import same_dispute_request

_ASSESSMENT_COLUMNS: Final = (
    "assessment_id, turn_id, conversation_id, principal_scope, question_digest, "
    "answer_digest, evidence_manifest_digest, rubric_version, model_set_digest, state, "
    "decision, assessed_at"
)
_DISPUTE_COLUMNS: Final = (
    "dispute_id, assessment_id, principal_scope, reported_by, reason, detail, "
    "evidence_refs, reported_at"
)


@dataclass(frozen=True, slots=True)
class PostgresConversationAssuranceLedgerConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresConversationAssuranceLedgerConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("conversation assurance database timeouts MUST be positive")


class PostgresConversationAssuranceLedger:
    """Persist immutable assessments and disputes across replicas."""

    def __init__(self, *, config: PostgresConversationAssuranceLedgerConfig) -> None:
        self._config = config

    async def append_assessment(self, record: AssessmentRecord) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                INSERT INTO conversation_assurance_assessment ({_ASSESSMENT_COLUMNS})
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (assessment_id) DO NOTHING
                RETURNING assessment_id
                """,  # noqa: S608 - columns are module constants
                (
                    record.assessment_id,
                    record.turn_id,
                    record.conversation_id,
                    record.principal_scope,
                    record.question_digest,
                    record.answer_digest,
                    record.evidence_manifest_digest,
                    record.rubric_version,
                    record.model_set_digest,
                    record.state.value,
                    Jsonb(_decision_mapping(record.decision)),
                    record.assessed_at,
                ),
            )
            created = await cursor.fetchone() is not None
            if not created:
                existing = await self.get_assessment(
                    principal_scope=record.principal_scope,
                    assessment_id=record.assessment_id,
                )
                if existing is None or existing != record:
                    raise ValueError("assessment id already belongs to different content")
            return created

    async def append_dispute(self, record: DisputeRecord) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"""
                INSERT INTO conversation_assurance_dispute ({_DISPUTE_COLUMNS})
                SELECT %s, assessment_id, %s, %s, %s, %s, %s, %s
                  FROM conversation_assurance_assessment
                 WHERE assessment_id = %s AND principal_scope = %s
                ON CONFLICT (dispute_id) DO NOTHING
                RETURNING dispute_id
                """,  # noqa: S608 - columns are module constants
                (
                    record.dispute_id,
                    record.principal_scope,
                    record.reported_by,
                    record.reason.value,
                    record.detail,
                    list(record.evidence_refs),
                    record.reported_at,
                    record.assessment_id,
                    record.principal_scope,
                ),
            )
            created = await cursor.fetchone() is not None
            if created:
                return True
            existing = await self.get_dispute(
                principal_scope=record.principal_scope,
                dispute_id=record.dispute_id,
            )
            if existing is not None:
                if not same_dispute_request(existing, record):
                    raise ValueError("dispute id already belongs to different content")
                return False
            raise LookupError("assessment is unavailable in the principal scope")

    async def get_assessment(
        self,
        *,
        principal_scope: str,
        assessment_id: str,
    ) -> AssessmentRecord | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_ASSESSMENT_COLUMNS} FROM conversation_assurance_assessment "  # noqa: S608
                "WHERE principal_scope = %s AND assessment_id = %s",
                (principal_scope, assessment_id),
            )
            row = await cursor.fetchone()
        return _assessment(row) if row is not None else None

    async def get_dispute(
        self,
        *,
        principal_scope: str,
        dispute_id: str,
    ) -> DisputeRecord | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_DISPUTE_COLUMNS} FROM conversation_assurance_dispute "  # noqa: S608
                "WHERE principal_scope = %s AND dispute_id = %s",
                (principal_scope, dispute_id),
            )
            row = await cursor.fetchone()
        return _dispute(row) if row is not None else None

    async def list_assessments(
        self,
        *,
        principal_scope: str,
        limit: int = 100,
    ) -> tuple[AssessmentRecord, ...]:
        _require_limit(limit)
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                f"SELECT {_ASSESSMENT_COLUMNS} FROM conversation_assurance_assessment "  # noqa: S608
                "WHERE principal_scope = %s ORDER BY assessed_at DESC, assessment_id LIMIT %s",
                (principal_scope, limit),
            )
            rows = await cursor.fetchall()
        return tuple(_assessment(row) for row in rows)

    async def list_disputes(
        self,
        *,
        principal_scope: str,
        assessment_id: str | None = None,
        limit: int = 100,
    ) -> tuple[DisputeRecord, ...]:
        _require_limit(limit)
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            if assessment_id is None:
                cursor = await connection.execute(
                    f"SELECT {_DISPUTE_COLUMNS} FROM conversation_assurance_dispute "  # noqa: S608
                    "WHERE principal_scope = %s "
                    "ORDER BY reported_at DESC, dispute_id LIMIT %s",
                    (principal_scope, limit),
                )
            else:
                cursor = await connection.execute(
                    f"SELECT {_DISPUTE_COLUMNS} FROM conversation_assurance_dispute "  # noqa: S608
                    "WHERE principal_scope = %s AND assessment_id = %s "
                    "ORDER BY reported_at DESC, dispute_id LIMIT %s",
                    (principal_scope, assessment_id, limit),
                )
            rows = await cursor.fetchall()
        return tuple(_dispute(row) for row in rows)

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        )

    async def _set_timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._config.statement_timeout_ms),),
        )


def _decision_mapping(decision: AssuranceDecision) -> dict[str, object]:
    return {
        "verdict": decision.verdict.value,
        "content_score": decision.content_score,
        "confidence": decision.confidence,
        "criteria": [
            {
                "criterion": item.criterion.value,
                "score": item.score,
                "rationale": item.rationale,
                "evidence_refs": list(item.evidence_refs),
            }
            for item in decision.criteria
        ],
        "reasons": list(decision.reasons),
        "evaluator_identities": list(decision.evaluator_identities),
        "disagreement": decision.disagreement,
        "model_calls": decision.model_calls,
        "prompt_tokens": decision.prompt_tokens,
        "completion_tokens": decision.completion_tokens,
        "cost_microusd": decision.cost_microusd,
    }


def _assessment(row: dict[str, Any]) -> AssessmentRecord:
    raw = row["decision"]
    criteria = tuple(
        CriterionScore(
            criterion=AssuranceCriterion(item["criterion"]),
            score=int(item["score"]),
            rationale=str(item["rationale"]),
            evidence_refs=tuple(str(ref) for ref in item["evidence_refs"]),
        )
        for item in raw["criteria"]
    )
    decision = AssuranceDecision(
        verdict=AssuranceVerdict(raw["verdict"]),
        content_score=float(raw["content_score"]),
        confidence=float(raw["confidence"]),
        criteria=criteria,
        reasons=tuple(str(item) for item in raw["reasons"]),
        evaluator_identities=tuple(str(item) for item in raw["evaluator_identities"]),
        disagreement=bool(raw["disagreement"]),
        model_calls=int(raw["model_calls"]),
        prompt_tokens=int(raw["prompt_tokens"]),
        completion_tokens=int(raw["completion_tokens"]),
        cost_microusd=int(raw["cost_microusd"]),
    )
    return AssessmentRecord(
        assessment_id=str(row["assessment_id"]),
        turn_id=str(row["turn_id"]),
        conversation_id=str(row["conversation_id"]),
        principal_scope=str(row["principal_scope"]),
        question_digest=str(row["question_digest"]),
        answer_digest=str(row["answer_digest"]),
        evidence_manifest_digest=str(row["evidence_manifest_digest"]),
        rubric_version=str(row["rubric_version"]),
        model_set_digest=str(row["model_set_digest"]),
        decision=decision,
        assessed_at=row["assessed_at"],
        state=AssessmentState(str(row["state"])),
    )


def _dispute(row: dict[str, Any]) -> DisputeRecord:
    return DisputeRecord(
        dispute_id=str(row["dispute_id"]),
        assessment_id=str(row["assessment_id"]),
        principal_scope=str(row["principal_scope"]),
        reported_by=str(row["reported_by"]),
        reason=DisputeReason(str(row["reason"])),
        detail=str(row["detail"]),
        evidence_refs=tuple(str(item) for item in row["evidence_refs"]),
        reported_at=row["reported_at"],
    )


def _require_limit(limit: int) -> None:
    if isinstance(limit, bool) or not 1 <= limit <= 1_000:
        raise ValueError("assurance list limit MUST be in [1, 1000]")


__all__ = [
    "PostgresConversationAssuranceLedger",
    "PostgresConversationAssuranceLedgerConfig",
]
