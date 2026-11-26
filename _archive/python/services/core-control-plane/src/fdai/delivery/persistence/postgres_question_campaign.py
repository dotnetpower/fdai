"""PostgreSQL append-only storage for bounded question campaigns."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.core.conversation.question_campaign import (
    QuestionCampaignCompletionRecord,
    QuestionCampaignHardZeroCounters,
    QuestionCampaignIdentity,
    QuestionCampaignState,
    QuestionCampaignTrigger,
    QuestionCaseAttemptRecord,
)


@dataclass(frozen=True, slots=True)
class PostgresQuestionCampaignLedgerConfig:
    """Connection and statement bounds for the campaign ledger."""

    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn:
            raise ValueError("PostgresQuestionCampaignLedgerConfig.dsn MUST NOT be empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("question campaign database timeouts MUST be positive")


class PostgresQuestionCampaignLedger:
    """Persist immutable campaign identities and attempts across replicas."""

    def __init__(self, *, config: PostgresQuestionCampaignLedgerConfig) -> None:
        self._config = config

    async def create_campaign(self, identity: QuestionCampaignIdentity) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                """
                INSERT INTO question_campaign (
                    campaign_id, source_revision, ontology_release_digest,
                    question_universe_digest, started_at, trigger_kind, identity
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (campaign_id) DO NOTHING
                RETURNING campaign_id
                """,
                (
                    identity.campaign_id,
                    identity.source_revision,
                    identity.ontology_release_digest,
                    identity.question_universe_digest,
                    identity.started_at,
                    identity.trigger.value,
                    Jsonb(_identity_mapping(identity)),
                ),
            )
            created = await cursor.fetchone() is not None
            if created:
                return True
            existing = await self.get_campaign(identity.campaign_id)
            if existing != identity:
                raise ValueError("question campaign id already belongs to different content")
            return False

    async def append_attempt(self, record: QuestionCaseAttemptRecord) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                """
                INSERT INTO question_campaign_attempt (
                    campaign_id, case_id, attempt_number, terminal_disposition,
                    terminal_reason, failure_kind, record
                )
                SELECT %s, %s, %s, %s, %s, %s, %s
                 WHERE EXISTS (
                    SELECT 1 FROM question_campaign WHERE campaign_id = %s
                 )
                ON CONFLICT (campaign_id, case_id, attempt_number) DO NOTHING
                RETURNING campaign_id
                """,
                (
                    record.campaign_id,
                    record.case_id,
                    record.attempt_number,
                    record.terminal_disposition,
                    record.terminal_reason,
                    record.failure_kind,
                    Jsonb(_attempt_mapping(record)),
                    record.campaign_id,
                ),
            )
            created = await cursor.fetchone() is not None
            if created:
                return True
            existing = await self._get_attempt(
                campaign_id=record.campaign_id,
                case_id=record.case_id,
                attempt_number=record.attempt_number,
            )
            if existing is None:
                raise LookupError("question campaign is unavailable")
            if existing != record:
                raise ValueError("question attempt id already belongs to different content")
            return False

    async def get_campaign(self, campaign_id: str) -> QuestionCampaignIdentity | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT identity FROM question_campaign WHERE campaign_id = %s",
                (campaign_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else _identity_from_mapping(row["identity"])

    async def list_attempts(self, campaign_id: str) -> tuple[QuestionCaseAttemptRecord, ...]:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT record FROM question_campaign_attempt "
                "WHERE campaign_id = %s ORDER BY case_id, attempt_number",
                (campaign_id,),
            )
            rows = await cursor.fetchall()
        return tuple(_attempt_from_mapping(row["record"]) for row in rows)

    async def finalize_campaign(self, record: QuestionCampaignCompletionRecord) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                """
                INSERT INTO question_campaign_completion (
                    campaign_id, completed_at, terminal_state, terminal_reason,
                    evaluation_receipt_digest, selected_case_ids_digest, record
                )
                SELECT %s, %s, %s, %s, %s, %s, %s
                 WHERE EXISTS (
                    SELECT 1 FROM question_campaign WHERE campaign_id = %s
                 )
                ON CONFLICT (campaign_id) DO NOTHING
                RETURNING campaign_id
                """,
                (
                    record.campaign_id,
                    record.completed_at,
                    record.state.value,
                    record.reason,
                    record.evaluation_receipt_digest,
                    record.selected_case_ids_digest,
                    Jsonb(_completion_mapping(record)),
                    record.campaign_id,
                ),
            )
            created = await cursor.fetchone() is not None
            if created:
                return True
            existing = await self.get_completion(record.campaign_id)
            if existing is None:
                raise LookupError("question campaign is unavailable")
            if existing != record:
                raise ValueError("question campaign completion conflicts with terminal content")
            return False

    async def get_completion(self, campaign_id: str) -> QuestionCampaignCompletionRecord | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT record FROM question_campaign_completion WHERE campaign_id = %s",
                (campaign_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else _completion_from_mapping(row["record"])

    async def claim_case(
        self,
        *,
        campaign_id: str,
        case_id: str,
        owner_id: str,
        claimed_at: datetime,
        lease_seconds: int,
    ) -> bool:
        if not owner_id or claimed_at.tzinfo is None or lease_seconds < 1:
            raise ValueError("question campaign case claim is invalid")
        expires_at = claimed_at + timedelta(seconds=lease_seconds)
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                """
                INSERT INTO question_campaign_case_claim (
                    campaign_id, case_id, owner_id, claimed_at, expires_at
                )
                SELECT %s, %s, %s, %s, %s
                 WHERE EXISTS (
                    SELECT 1 FROM question_campaign WHERE campaign_id = %s
                 )
                ON CONFLICT (campaign_id, case_id) DO UPDATE
                    SET owner_id = EXCLUDED.owner_id,
                        claimed_at = EXCLUDED.claimed_at,
                        expires_at = EXCLUDED.expires_at
                  WHERE question_campaign_case_claim.expires_at <= EXCLUDED.claimed_at
                     OR question_campaign_case_claim.owner_id = EXCLUDED.owner_id
                RETURNING campaign_id
                """,
                (
                    campaign_id,
                    case_id,
                    owner_id,
                    claimed_at,
                    expires_at,
                    campaign_id,
                ),
            )
            if await cursor.fetchone() is not None:
                return True
            campaign = await connection.execute(
                "SELECT 1 FROM question_campaign WHERE campaign_id = %s",
                (campaign_id,),
            )
            if await campaign.fetchone() is None:
                raise LookupError("question campaign is unavailable")
            return False

    async def release_case_claim(self, *, campaign_id: str, case_id: str, owner_id: str) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "DELETE FROM question_campaign_case_claim "
                "WHERE campaign_id = %s AND case_id = %s AND owner_id = %s "
                "RETURNING campaign_id",
                (campaign_id, case_id, owner_id),
            )
            return await cursor.fetchone() is not None

    async def _get_attempt(
        self,
        *,
        campaign_id: str,
        case_id: str,
        attempt_number: int,
    ) -> QuestionCaseAttemptRecord | None:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT record FROM question_campaign_attempt "
                "WHERE campaign_id = %s AND case_id = %s AND attempt_number = %s",
                (campaign_id, case_id, attempt_number),
            )
            row = await cursor.fetchone()
        return None if row is None else _attempt_from_mapping(row["record"])

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


def _identity_mapping(identity: QuestionCampaignIdentity) -> dict[str, object]:
    values = asdict(identity)
    values["started_at"] = identity.started_at.isoformat()
    values["trigger"] = identity.trigger.value
    return values


def _identity_from_mapping(raw: dict[str, Any]) -> QuestionCampaignIdentity:
    return QuestionCampaignIdentity(
        campaign_id=str(raw["campaign_id"]),
        source_revision=str(raw["source_revision"]),
        ontology_release_digest=str(raw["ontology_release_digest"]),
        principal_manifest_digests=tuple(str(item) for item in raw["principal_manifest_digests"]),
        question_universe_digest=str(raw["question_universe_digest"]),
        generation_profile_digest=str(raw["generation_profile_digest"]),
        model_set_digest=str(raw["model_set_digest"]),
        scope_digest=str(raw["scope_digest"]),
        started_at=datetime.fromisoformat(str(raw["started_at"])),
        question_budget=int(raw["question_budget"]),
        time_budget_seconds=int(raw["time_budget_seconds"]),
        no_progress_seconds=int(raw["no_progress_seconds"]),
        token_budget=int(raw["token_budget"]),
        cost_budget_microusd=int(raw["cost_budget_microusd"]),
        trigger=QuestionCampaignTrigger(str(raw["trigger"])),
        mode=str(raw["mode"]),
    )


def _attempt_mapping(record: QuestionCaseAttemptRecord) -> dict[str, object]:
    return asdict(record)


def _attempt_from_mapping(raw: dict[str, Any]) -> QuestionCaseAttemptRecord:
    return QuestionCaseAttemptRecord(
        campaign_id=str(raw["campaign_id"]),
        case_id=str(raw["case_id"]),
        validated_question_digest=str(raw["validated_question_digest"]),
        semantic_turn_id=str(raw["semantic_turn_id"]),
        attempt_number=int(raw["attempt_number"]),
        terminal_disposition=(
            None if raw["terminal_disposition"] is None else str(raw["terminal_disposition"])
        ),
        terminal_reason=(None if raw["terminal_reason"] is None else str(raw["terminal_reason"])),
        failure_kind=None if raw["failure_kind"] is None else str(raw["failure_kind"]),
        assessment_id=None if raw["assessment_id"] is None else str(raw["assessment_id"]),
        epistemic_record_digest=(
            None if raw["epistemic_record_digest"] is None else str(raw["epistemic_record_digest"])
        ),
        latency_ms=int(raw["latency_ms"]),
        model_calls=int(raw["model_calls"]),
        prompt_tokens=int(raw["prompt_tokens"]),
        completion_tokens=int(raw["completion_tokens"]),
        cost_microusd=int(raw["cost_microusd"]),
        hard_zero=QuestionCampaignHardZeroCounters(
            **{key: int(value) for key, value in raw["hard_zero"].items()}
        ),
        execution_authority=bool(raw["execution_authority"]),
    )


def _completion_mapping(record: QuestionCampaignCompletionRecord) -> dict[str, object]:
    values = asdict(record)
    values["completed_at"] = record.completed_at.isoformat()
    values["state"] = record.state.value
    return values


def _completion_from_mapping(raw: dict[str, Any]) -> QuestionCampaignCompletionRecord:
    return QuestionCampaignCompletionRecord(
        campaign_id=str(raw["campaign_id"]),
        completed_at=datetime.fromisoformat(str(raw["completed_at"])),
        state=QuestionCampaignState(str(raw["state"])),
        reason=str(raw["reason"]),
        evaluation_receipt_digest=str(raw["evaluation_receipt_digest"]),
        selected_case_ids_digest=str(raw["selected_case_ids_digest"]),
        selected_case_count=int(raw["selected_case_count"]),
        terminal_case_count=int(raw["terminal_case_count"]),
        full_universe_case_count=int(raw["full_universe_case_count"]),
        model_calls=int(raw["model_calls"]),
        prompt_tokens=int(raw["prompt_tokens"]),
        completion_tokens=int(raw["completion_tokens"]),
        cost_microusd=int(raw["cost_microusd"]),
        hard_zero=QuestionCampaignHardZeroCounters(
            **{key: int(value) for key, value in raw["hard_zero"].items()}
        ),
        execution_authority=bool(raw["execution_authority"]),
    )


__all__ = [
    "PostgresQuestionCampaignLedger",
    "PostgresQuestionCampaignLedgerConfig",
]
