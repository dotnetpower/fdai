"""PostgreSQL persistence for authority-neutral Cost Governance reviews."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.shared.providers.cost_governance_review import (
    CostPromotionReview,
    CostReviewDecision,
    CostReviewTargetKind,
)


class PostgresCostPromotionReviewStore:
    """Append and verify one immutable review record per idempotent request."""

    def __init__(
        self,
        *,
        dsn: str,
        statement_timeout_ms: int = 15_000,
        connect_timeout_s: int = 10,
    ) -> None:
        if not dsn or statement_timeout_ms < 1 or connect_timeout_s < 1:
            raise ValueError("Cost review store configuration MUST be valid")
        self._dsn = dsn
        self._statement_timeout_ms = statement_timeout_ms
        self._connect_timeout_s = connect_timeout_s

    async def append_cost_promotion_review(self, review: CostPromotionReview) -> bool:
        """Append a review, replaying only byte-equivalent request content."""

        async with await self._connect() as connection:
            async with connection.transaction():
                await self._timeout(connection)
                inserted = await connection.execute(
                    """
                    INSERT INTO cost_governance_promotion_review (
                        review_id, request_id, campaign_id, campaign_evidence_digest,
                        revision_pin_digest, campaign_report_digest, target_kind, target_id,
                        reviewer_identity, decision, rationale, reviewed_at,
                        evidence_refs, retention_until, approval_authority,
                        execution_authority, promotion_authority, payload
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, FALSE, FALSE, FALSE, %s
                    )
                    ON CONFLICT (request_id) DO NOTHING
                    """,
                    (
                        review.review_id,
                        review.request_id,
                        review.campaign_id,
                        review.campaign_evidence_digest,
                        review.revision_pin_digest,
                        review.campaign_report_digest,
                        review.target_kind.value,
                        review.target_id,
                        review.reviewer_identity,
                        review.decision.value,
                        review.rationale,
                        review.reviewed_at,
                        Jsonb(list(review.evidence_refs)),
                        review.retention_until,
                        Jsonb(review.to_mapping()),
                    ),
                )
                if inserted.rowcount == 1:
                    return True
                existing_cursor = await connection.execute(
                    """
                    SELECT review_id, request_id, campaign_id, campaign_evidence_digest,
                           revision_pin_digest, campaign_report_digest, target_kind,
                           target_id, reviewer_identity, decision, rationale, reviewed_at,
                           evidence_refs, retention_until, approval_authority,
                           execution_authority, promotion_authority, payload
                      FROM cost_governance_promotion_review
                     WHERE request_id = %s
                    """,
                    (review.request_id,),
                )
                existing = await existing_cursor.fetchone()
                if (
                    existing is not None
                    and existing["review_id"] == review.review_id
                    and existing["payload"] == review.to_mapping()
                    and _columns_match_review(existing, review)
                ):
                    return False
                raise ValueError("Cost review request id conflicts with prior content")

    async def read_cost_promotion_reviews(
        self,
        *,
        campaign_id: str,
        revision_pin_digest: str,
        limit: int,
    ) -> tuple[CostPromotionReview, ...]:
        """Read a bounded exact-campaign review history and verify every digest."""

        if not 1 <= limit <= 1_000:
            raise ValueError("Cost review store limit MUST be in [1, 1000]")
        async with await self._connect() as connection:
            await self._timeout(connection)
            cursor = await connection.execute(
                """
                  SELECT review_id, request_id, campaign_id, campaign_evidence_digest,
                      revision_pin_digest, campaign_report_digest, target_kind,
                      target_id, reviewer_identity, decision, rationale, reviewed_at,
                      evidence_refs, retention_until, approval_authority,
                      execution_authority, promotion_authority, payload
                  FROM cost_governance_promotion_review
                 WHERE campaign_id = %s
                   AND revision_pin_digest = %s
                 ORDER BY reviewed_at, target_kind, target_id, review_id
                 LIMIT %s
                """,
                (campaign_id, revision_pin_digest, limit),
            )
            rows = await cursor.fetchall()
        reviews = tuple(_review_from_payload(cast(dict[str, Any], row["payload"])) for row in rows)
        for review, row in zip(reviews, rows, strict=True):
            if review.review_id != row["review_id"]:
                raise RuntimeError("Persisted Cost review failed digest verification")
            if not _columns_match_review(row, review):
                raise RuntimeError("Persisted Cost review columns do not match payload")
        return reviews

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._dsn.replace("postgresql+psycopg://", "postgresql://", 1),
            row_factory=dict_row,
            connect_timeout=self._connect_timeout_s,
        )

    async def _timeout(self, connection: psycopg.AsyncConnection[Any]) -> None:
        await connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._statement_timeout_ms),),
        )


def _review_from_payload(value: dict[str, Any]) -> CostPromotionReview:
    return CostPromotionReview(
        schema_version=cast(str, value["schema_version"]),
        request_id=cast(str, value["request_id"]),
        campaign_id=cast(str, value["campaign_id"]),
        campaign_evidence_digest=cast(str, value["campaign_evidence_digest"]),
        revision_pin_digest=cast(str, value["revision_pin_digest"]),
        campaign_report_digest=cast(str, value["campaign_report_digest"]),
        target_kind=CostReviewTargetKind(cast(str, value["target_kind"])),
        target_id=cast(str, value["target_id"]),
        reviewer_identity=cast(str, value["reviewer_identity"]),
        decision=CostReviewDecision(cast(str, value["decision"])),
        rationale=cast(str, value["rationale"]),
        reviewed_at=datetime.fromisoformat(cast(str, value["reviewed_at"])),
        evidence_refs=tuple(cast(list[str], value["evidence_refs"])),
        retention_until=datetime.fromisoformat(cast(str, value["retention_until"])),
        approval_authority=cast(Any, value["approval_authority"]),
        execution_authority=cast(Any, value["execution_authority"]),
        promotion_authority=cast(Any, value["promotion_authority"]),
    )


def _columns_match_review(row: dict[str, Any], review: CostPromotionReview) -> bool:
    expected: dict[str, object] = {
        "approval_authority": review.approval_authority,
        "campaign_evidence_digest": review.campaign_evidence_digest,
        "campaign_id": review.campaign_id,
        "campaign_report_digest": review.campaign_report_digest,
        "decision": review.decision.value,
        "evidence_refs": list(review.evidence_refs),
        "execution_authority": review.execution_authority,
        "promotion_authority": review.promotion_authority,
        "rationale": review.rationale,
        "request_id": review.request_id,
        "reviewed_at": review.reviewed_at,
        "reviewer_identity": review.reviewer_identity,
        "retention_until": review.retention_until,
        "revision_pin_digest": review.revision_pin_digest,
        "target_id": review.target_id,
        "target_kind": review.target_kind.value,
    }
    return all(row[name] == value for name, value in expected.items())


__all__ = ["PostgresCostPromotionReviewStore"]
