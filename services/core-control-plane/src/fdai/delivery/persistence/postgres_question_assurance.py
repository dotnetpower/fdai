"""PostgreSQL append-only storage for question assurance evidence."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.core.conversation.question_governance import (
    ManualQuestionCampaignReview,
    QuestionFailureDecisionKind,
    QuestionFailureReviewDecision,
    QuestionFailureReviewItem,
)
from fdai.core.conversation.question_novelty import (
    QuestionEmbeddingIdentity,
    QuestionNoveltyDuplicateError,
    QuestionNoveltyRecord,
)
from fdai.core.conversation.question_release_assurance import QuestionReleaseAssuranceReceipt
from fdai.core.conversation.question_review_artifact import RepositorySafeQuestionReview
from fdai.core.conversation_assurance.models import AssuranceCriterion, AssuranceVerdict
from fdai.delivery.persistence.postgres_question_campaign import (
    PostgresQuestionCampaignLedgerConfig,
)


class PostgresQuestionAssuranceLedger:
    """Persist digest-only records with idempotent append semantics."""

    def __init__(self, *, config: PostgresQuestionCampaignLedgerConfig) -> None:
        self._config = config

    async def append_novelty(self, record: QuestionNoveltyRecord) -> bool:
        if record.nearest_question_fingerprint is not None and not await self._fingerprint_exists(
            record.nearest_question_fingerprint
        ):
            raise ValueError("nearest question fingerprint is not an accepted ledger record")
        try:
            created = await self._insert(
                """
                INSERT INTO question_campaign_novelty (
                    campaign_id, case_id, generation_attempt, question_fingerprint,
                    exact_duplicate, semantic_duplicate, semantic_duplicate_threshold,
                    accepted, record, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (campaign_id, case_id, generation_attempt) DO NOTHING
                RETURNING campaign_id
                """,
                (
                    record.campaign_id,
                    record.case_id,
                    record.generation_attempt,
                    record.question_fingerprint,
                    record.exact_duplicate,
                    record.semantic_duplicate,
                    record.semantic_duplicate_threshold,
                    record.accepted,
                    Jsonb(_novelty_mapping(record)),
                    record.recorded_at,
                ),
            )
        except psycopg.errors.UniqueViolation as error:
            raise QuestionNoveltyDuplicateError(
                "accepted question fingerprint already exists"
            ) from error
        if created:
            return True
        raw = await self._get_record(
            "SELECT record FROM question_campaign_novelty "
            "WHERE campaign_id = %s AND case_id = %s AND generation_attempt = %s",
            (record.campaign_id, record.case_id, record.generation_attempt),
        )
        if raw is None:
            raise LookupError("question campaign is unavailable")
        if _novelty_from_mapping(raw) != record:
            raise ValueError("question novelty identity already belongs to different content")
        return False

    async def list_novelty(self, *, limit: int = 10_000) -> tuple[QuestionNoveltyRecord, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 10_000:
            raise ValueError("question novelty limit MUST be in [1, 10000]")
        rows = await self._list_records(
            "SELECT record FROM question_campaign_novelty "
            "ORDER BY recorded_at, campaign_id, case_id, generation_attempt LIMIT %s",
            (limit,),
        )
        return tuple(_novelty_from_mapping(row) for row in rows)

    async def append_review_projection(self, record: RepositorySafeQuestionReview) -> bool:
        created = await self._insert(
            """
            INSERT INTO question_review_projection (
                record_id, campaign_id, case_id, question_digest, answer_digest,
                adequacy_receipt_digest, record, recorded_at, delete_after
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (record_id) DO NOTHING RETURNING record_id
            """,
            (
                record.record_id,
                record.campaign_id,
                record.case_id,
                record.question_digest,
                record.answer_digest,
                record.adequacy_receipt_digest,
                Jsonb(_review_projection_mapping(record)),
                record.recorded_at,
                record.delete_after,
            ),
        )
        if created:
            return True
        raw = await self._get_record(
            "SELECT record FROM question_review_projection WHERE record_id = %s",
            (record.record_id,),
        )
        if raw is None or _review_projection_from_mapping(raw) != record:
            raise ValueError("question review projection conflicts with durable content")
        return False

    async def append_review_item(self, item: QuestionFailureReviewItem) -> bool:
        created = await self._insert(
            """
            INSERT INTO question_failure_review (
                review_id, campaign_id, case_id, semantic_pair_id,
                ontology_release_digest, question_digest, answer_digest,
                adequacy_receipt_digest, record, submitted_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (review_id) DO NOTHING RETURNING review_id
            """,
            (
                item.review_id,
                item.campaign_id,
                item.case_id,
                item.semantic_pair_id,
                item.ontology_release_digest,
                item.question_digest,
                item.answer_digest,
                item.adequacy_receipt_digest,
                Jsonb(_review_item_mapping(item)),
                item.submitted_at,
            ),
        )
        if created:
            return True
        existing = await self.get_review_item(item.review_id)
        if existing != item:
            raise ValueError("question failure review id belongs to different content")
        return False

    async def append_review_decision(self, decision: QuestionFailureReviewDecision) -> bool:
        created = await self._insert(
            """
            INSERT INTO question_failure_review_decision (
                review_id, decision, human_principal_digest,
                human_authorization_receipt_digest, authorization_expires_at,
                reason_code, target_corpus_version, record, decided_at
            )
            SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s
             WHERE EXISTS (SELECT 1 FROM question_failure_review WHERE review_id = %s)
            ON CONFLICT (review_id) DO NOTHING RETURNING review_id
            """,
            (
                decision.review_id,
                decision.decision.value,
                decision.human_principal_digest,
                decision.human_authorization_receipt_digest,
                decision.authorization_expires_at,
                decision.reason_code,
                decision.target_corpus_version,
                Jsonb(_review_decision_mapping(decision)),
                decision.decided_at,
                decision.review_id,
            ),
        )
        if created:
            return True
        existing = await self.get_review_decision(decision.review_id)
        if existing is None:
            raise LookupError("question failure review item is unavailable")
        if existing != decision:
            raise ValueError("question failure decision is immutable")
        return False

    async def get_review_item(self, review_id: str) -> QuestionFailureReviewItem | None:
        raw = await self._get_record(
            "SELECT record FROM question_failure_review WHERE review_id = %s", (review_id,)
        )
        return None if raw is None else _review_item_from_mapping(raw)

    async def get_review_decision(self, review_id: str) -> QuestionFailureReviewDecision | None:
        raw = await self._get_record(
            "SELECT record FROM question_failure_review_decision WHERE review_id = %s",
            (review_id,),
        )
        return None if raw is None else _review_decision_from_mapping(raw)

    async def append_manual_review(self, record: ManualQuestionCampaignReview) -> bool:
        created = await self._insert(
            """
            INSERT INTO question_manual_campaign_review (
                campaign_id, ontology_release_digest, novelty_rate,
                new_failure_count, coverage_delta_count, human_principal_digest,
                human_review_receipt_digest, record, reviewed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (campaign_id) DO NOTHING RETURNING campaign_id
            """,
            (
                record.campaign_id,
                record.ontology_release_digest,
                record.novelty_rate,
                record.new_failure_count,
                record.coverage_delta_count,
                record.human_principal_digest,
                record.human_review_receipt_digest,
                Jsonb(_manual_review_mapping(record)),
                record.reviewed_at,
            ),
        )
        if created:
            return True
        raw = await self._get_record(
            "SELECT record FROM question_manual_campaign_review WHERE campaign_id = %s",
            (record.campaign_id,),
        )
        if raw is None or _manual_review_from_mapping(raw) != record:
            raise ValueError("manual question campaign review conflicts with durable content")
        return False

    async def list_manual_reviews(self) -> tuple[ManualQuestionCampaignReview, ...]:
        rows = await self._list_records(
            "SELECT record FROM question_manual_campaign_review ORDER BY reviewed_at, campaign_id",
            (),
        )
        return tuple(_manual_review_from_mapping(row) for row in rows)

    async def append_release_assurance(
        self,
        *,
        source_revision: str,
        golden_corpus_digest: str,
        receipt: QuestionReleaseAssuranceReceipt,
    ) -> bool:
        created = await self._insert(
            """
            INSERT INTO question_release_assurance (
                receipt_digest, source_revision, ontology_release_digest, golden_corpus_digest,
                generated_campaign_id, passed, record
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (receipt_digest) DO NOTHING RETURNING receipt_digest
            """,
            (
                receipt.receipt_digest,
                source_revision,
                receipt.ontology_release_digest,
                golden_corpus_digest,
                receipt.generated_campaign_id,
                receipt.passed,
                Jsonb(_release_mapping(receipt)),
            ),
        )
        if created:
            return True
        raw = await self._get_record(
            "SELECT record FROM question_release_assurance WHERE receipt_digest = %s",
            (receipt.receipt_digest,),
        )
        if raw != _release_mapping(receipt):
            raise ValueError("question release assurance digest conflicts with durable content")
        return False

    async def get_release_assurance(
        self,
        receipt_digest: str,
    ) -> QuestionReleaseAssuranceReceipt | None:
        raw = await self._get_record(
            "SELECT record FROM question_release_assurance WHERE receipt_digest = %s",
            (receipt_digest,),
        )
        return None if raw is None else _release_from_mapping(raw)

    async def _insert(self, query: str, parameters: tuple[object, ...]) -> bool:
        async with await self._connect() as connection, connection.transaction():
            await self._set_timeout(connection)
            cursor = await connection.execute(query, parameters)
            return await cursor.fetchone() is not None

    async def _fingerprint_exists(self, fingerprint: str) -> bool:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(
                "SELECT 1 FROM question_campaign_novelty "
                "WHERE question_fingerprint = %s AND accepted LIMIT 1",
                (fingerprint,),
            )
            return await cursor.fetchone() is not None

    async def _get_record(
        self, query: str, parameters: tuple[object, ...]
    ) -> dict[str, Any] | None:
        rows = await self._list_records(query, parameters)
        return None if not rows else rows[0]

    async def _list_records(
        self, query: str, parameters: tuple[object, ...]
    ) -> tuple[dict[str, Any], ...]:
        async with await self._connect() as connection:
            await self._set_timeout(connection)
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
        return tuple(row["record"] for row in rows)

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


def _novelty_mapping(record: QuestionNoveltyRecord) -> dict[str, object]:
    values = asdict(record)
    values["recorded_at"] = record.recorded_at.isoformat()
    return values


def _novelty_from_mapping(raw: dict[str, Any]) -> QuestionNoveltyRecord:
    embedding = raw["embedding"]
    return QuestionNoveltyRecord(
        campaign_id=str(raw["campaign_id"]),
        case_id=str(raw["case_id"]),
        generation_attempt=int(raw["generation_attempt"]),
        perspective=str(raw["perspective"]),
        locale=str(raw["locale"]),
        ontology_release_digest=str(raw["ontology_release_digest"]),
        question_fingerprint=str(raw["question_fingerprint"]),
        embedding=None if embedding is None else QuestionEmbeddingIdentity(**embedding),
        nearest_question_fingerprint=raw["nearest_question_fingerprint"],
        max_embedding_similarity=raw["max_embedding_similarity"],
        exact_duplicate=bool(raw["exact_duplicate"]),
        semantic_duplicate=bool(raw["semantic_duplicate"]),
        accepted=bool(raw["accepted"]),
        recorded_at=datetime.fromisoformat(str(raw["recorded_at"])),
        semantic_duplicate_threshold=float(raw.get("semantic_duplicate_threshold", 0.92)),
    )


def _review_projection_mapping(record: RepositorySafeQuestionReview) -> dict[str, object]:
    return {
        "record_id": record.record_id,
        "campaign_id": record.campaign_id,
        "case_id": record.case_id,
        "question_digest": record.question_digest,
        "answer_digest": record.answer_digest,
        "rationale_digests": record.rationale_digests,
        "criterion_scores": [
            [criterion.value, score] for criterion, score in record.criterion_scores
        ],
        "adequacy_verdict": record.adequacy_verdict.value,
        "adequacy_receipt_digest": record.adequacy_receipt_digest,
        "retention_policy_digest": record.retention_policy_digest,
        "recorded_at": record.recorded_at.isoformat(),
        "delete_after": record.delete_after.isoformat(),
    }


def _review_projection_from_mapping(raw: dict[str, Any]) -> RepositorySafeQuestionReview:
    return RepositorySafeQuestionReview(
        record_id=str(raw["record_id"]),
        campaign_id=str(raw["campaign_id"]),
        case_id=str(raw["case_id"]),
        question_digest=str(raw["question_digest"]),
        answer_digest=str(raw["answer_digest"]),
        rationale_digests=tuple(str(item) for item in raw["rationale_digests"]),
        criterion_scores=tuple(
            (AssuranceCriterion(str(item[0])), int(item[1])) for item in raw["criterion_scores"]
        ),
        adequacy_verdict=AssuranceVerdict(str(raw["adequacy_verdict"])),
        adequacy_receipt_digest=str(raw["adequacy_receipt_digest"]),
        retention_policy_digest=str(raw["retention_policy_digest"]),
        recorded_at=datetime.fromisoformat(str(raw["recorded_at"])),
        delete_after=datetime.fromisoformat(str(raw["delete_after"])),
    )


def _review_item_mapping(item: QuestionFailureReviewItem) -> dict[str, object]:
    values = asdict(item)
    values["submitted_at"] = item.submitted_at.isoformat()
    return values


def _review_item_from_mapping(raw: dict[str, Any]) -> QuestionFailureReviewItem:
    values = dict(raw)
    values["submitted_at"] = datetime.fromisoformat(str(values["submitted_at"]))
    return QuestionFailureReviewItem(**values)


def _review_decision_mapping(decision: QuestionFailureReviewDecision) -> dict[str, object]:
    values = asdict(decision)
    values["decision"] = decision.decision.value
    values["decided_at"] = decision.decided_at.isoformat()
    values["authorization_expires_at"] = decision.authorization_expires_at.isoformat()
    return values


def _review_decision_from_mapping(raw: dict[str, Any]) -> QuestionFailureReviewDecision:
    values = dict(raw)
    values["decision"] = QuestionFailureDecisionKind(str(values["decision"]))
    values["decided_at"] = datetime.fromisoformat(str(values["decided_at"]))
    values["authorization_expires_at"] = datetime.fromisoformat(
        str(values["authorization_expires_at"])
    )
    return QuestionFailureReviewDecision(**values)


def _manual_review_mapping(record: ManualQuestionCampaignReview) -> dict[str, object]:
    values = asdict(record)
    values["reviewed_at"] = record.reviewed_at.isoformat()
    return values


def _manual_review_from_mapping(raw: dict[str, Any]) -> ManualQuestionCampaignReview:
    values = dict(raw)
    values["reviewed_at"] = datetime.fromisoformat(str(values["reviewed_at"]))
    return ManualQuestionCampaignReview(**values)


def _release_mapping(receipt: QuestionReleaseAssuranceReceipt) -> dict[str, object]:
    values = asdict(receipt)
    values["adequacy_receipt_digests"] = list(receipt.adequacy_receipt_digests)
    values["metamorphic_receipt_digests"] = list(receipt.metamorphic_receipt_digests)
    return values


def _release_from_mapping(raw: dict[str, Any]) -> QuestionReleaseAssuranceReceipt:
    values = dict(raw)
    values["adequacy_receipt_digests"] = tuple(values["adequacy_receipt_digests"])
    values["metamorphic_receipt_digests"] = tuple(values["metamorphic_receipt_digests"])
    return QuestionReleaseAssuranceReceipt(**values)


__all__ = ["PostgresQuestionAssuranceLedger"]
