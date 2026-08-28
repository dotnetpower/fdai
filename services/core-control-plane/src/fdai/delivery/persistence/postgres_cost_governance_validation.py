"""PostgreSQL adapter for append-only Cost Governance W7 evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fdai.shared.providers.cost_governance_campaign import (
    CostCampaignEpisode,
    CostCampaignOutcome,
    CostCampaignSettlement,
)
from fdai.shared.providers.cost_governance_lifecycle import (
    CostEvidenceKind,
    CostLifecycleOperation,
    CostLifecycleOutcome,
    CostLifecycleReceipt,
    CostRevisionPin,
)


class PostgresCostGovernanceValidationStore:
    """Append evidence and manage only its revisioned retention envelope."""

    def __init__(
        self,
        *,
        dsn: str,
        statement_timeout_ms: int = 15_000,
        connect_timeout_s: int = 10,
    ) -> None:
        if not dsn or statement_timeout_ms < 1 or connect_timeout_s < 1:
            raise ValueError("cost validation store configuration MUST be valid")
        self._dsn = dsn
        self._statement_timeout_ms = statement_timeout_ms
        self._connect_timeout_s = connect_timeout_s

    async def append_cost_lifecycle_receipt(
        self,
        receipt: CostLifecycleReceipt,
        *,
        expected_receipt_digest: str,
    ) -> bool:
        """Append one digest-verified lifecycle receipt and retention record."""

        if not receipt.verify_digest(expected_receipt_digest):
            raise ValueError("lifecycle receipt digest verification failed")
        async with await self._connect() as conn:
            async with conn.transaction():
                await self._timeout(conn)
                inserted = await conn.execute(
                    """
                    INSERT INTO cost_governance_lifecycle_receipt (
                        receipt_id, package_id, activation_revision, operation,
                        outcome, receipt_digest, revision_pin_digest, evidence_kind,
                        payload, evidence_refs, occurred_at, idempotency_key
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        receipt.receipt_id,
                        receipt.revision_pin.package_id,
                        receipt.revision_pin.activation_revision,
                        receipt.operation.value,
                        receipt.outcome.value,
                        receipt.digest,
                        receipt.revision_pin.digest,
                        receipt.evidence_kind.value,
                        Jsonb(receipt.to_mapping()),
                        Jsonb(list(receipt.evidence_refs)),
                        receipt.occurred_at,
                        receipt.idempotency_key,
                    ),
                )
                if inserted.rowcount != 1:
                    return False
                await self._initialize_retention(
                    conn,
                    evidence_kind="lifecycle-receipt",
                    evidence_id=receipt.receipt_id,
                    retention_until=receipt.retention_until,
                    recorded_at=receipt.occurred_at,
                    legal_hold=receipt.legal_hold,
                    legal_hold_ref=receipt.legal_hold_ref,
                    idempotency_key=f"retention:{receipt.idempotency_key}",
                )
                return True

    async def read_cost_lifecycle_receipts(
        self,
        package_id: str,
        *,
        limit: int,
    ) -> tuple[CostLifecycleReceipt, ...]:
        """Read a bounded newest-first package receipt history."""

        _limit(limit)
        async with await self._connect() as conn:
            await self._timeout(conn)
            cursor = await conn.execute(
                """
                SELECT receipt.payload, receipt.receipt_digest
                  FROM cost_governance_lifecycle_receipt AS receipt
                  JOIN cost_governance_validation_retention AS retention
                    ON retention.evidence_kind = 'lifecycle-receipt'
                   AND retention.evidence_id = receipt.receipt_id
                 WHERE receipt.package_id = %s
                   AND retention.purged_at IS NULL
                 ORDER BY activation_revision DESC, occurred_at DESC
                 LIMIT %s
                """,
                (package_id, limit),
            )
            rows = await cursor.fetchall()
        receipts = tuple(
            _receipt_from_payload(cast(dict[str, Any], row["payload"])) for row in rows
        )
        for receipt, row in zip(receipts, rows, strict=True):
            if not receipt.verify_digest(cast(str, row["receipt_digest"])):
                raise RuntimeError("persisted lifecycle receipt failed digest verification")
        return receipts

    async def append_cost_campaign_episode(
        self,
        episode: CostCampaignEpisode,
        *,
        expected_revision: int,
    ) -> bool:
        """Append one CAS-ordered immutable campaign episode revision."""

        if episode.revision != expected_revision + 1:
            raise ValueError("campaign episode revision MUST follow expected revision")
        async with await self._connect() as conn:
            async with conn.transaction():
                await self._timeout(conn)
                cursor = await conn.execute(
                    """
                    SELECT episode.revision, retention.purged_at
                      FROM cost_governance_campaign_episode AS episode
                      JOIN cost_governance_validation_retention AS retention
                        ON retention.evidence_kind = 'campaign-episode'
                       AND retention.evidence_id = episode.episode_id
                     WHERE episode.episode_id = %s
                     ORDER BY episode.revision DESC
                     LIMIT 1
                     FOR UPDATE
                    """,
                    (episode.episode_id,),
                )
                row = await cursor.fetchone()
                if row is not None and row["purged_at"] is not None:
                    return False
                actual = cast(int, row["revision"]) if row is not None else 0
                if actual != expected_revision:
                    return False
                inserted = await conn.execute(
                    """
                    INSERT INTO cost_governance_campaign_episode (
                        campaign_id, episode_id, revision, idempotency_key,
                        revision_pin_digest, outcome, evidence_kind, payload,
                        evidence_refs, observed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        episode.campaign_id,
                        episode.episode_id,
                        episode.revision,
                        episode.idempotency_key,
                        episode.revision_pin_digest,
                        episode.outcome.value,
                        episode.evidence_kind.value,
                        Jsonb(episode.to_mapping()),
                        Jsonb(list(episode.evidence_refs)),
                        episode.observed_at,
                    ),
                )
                if inserted.rowcount != 1:
                    return False
                if expected_revision == 0:
                    await self._initialize_retention(
                        conn,
                        evidence_kind="campaign-episode",
                        evidence_id=episode.episode_id,
                        retention_until=episode.retention_until,
                        recorded_at=episode.observed_at,
                        legal_hold=episode.legal_hold,
                        legal_hold_ref=episode.legal_hold_ref,
                        idempotency_key=f"retention:{episode.idempotency_key}",
                    )
                return True

    async def read_cost_campaign_episodes(
        self,
        campaign_id: str,
        revision_pin_digest: str,
        *,
        limit: int,
    ) -> tuple[CostCampaignEpisode, ...]:
        """Read one bounded exact-revision campaign in deterministic order."""

        _limit(limit)
        async with await self._connect() as conn:
            await self._timeout(conn)
            cursor = await conn.execute(
                """
                SELECT episode.payload
                  FROM cost_governance_campaign_episode AS episode
                  JOIN cost_governance_validation_retention AS retention
                    ON retention.evidence_kind = 'campaign-episode'
                   AND retention.evidence_id = episode.episode_id
                 WHERE episode.campaign_id = %s
                   AND episode.revision_pin_digest = %s
                   AND retention.purged_at IS NULL
                 ORDER BY observed_at, episode_id, revision
                 LIMIT %s
                """,
                (campaign_id, revision_pin_digest, limit),
            )
            rows = await cursor.fetchall()
        return tuple(_episode_from_payload(cast(dict[str, Any], row["payload"])) for row in rows)

    async def set_validation_legal_hold(
        self,
        *,
        evidence_kind: str,
        evidence_id: str,
        expected_revision: int,
        legal_hold_ref: str | None,
        recorded_at: datetime,
        idempotency_key: str,
    ) -> bool:
        """CAS-update only retention metadata and append the corresponding event."""

        async with await self._connect() as conn:
            async with conn.transaction():
                await self._timeout(conn)
                replay_cursor = await conn.execute(
                    """
                    SELECT event_kind, legal_hold_ref
                      FROM cost_governance_validation_retention_event
                     WHERE evidence_kind = %s
                       AND evidence_id = %s
                       AND idempotency_key = %s
                    """,
                    (evidence_kind, evidence_id, idempotency_key),
                )
                replay = await replay_cursor.fetchone()
                expected_event = "hold-applied" if legal_hold_ref is not None else "hold-released"
                if replay is not None:
                    if (
                        cast(str, replay["event_kind"]) == expected_event
                        and cast(str | None, replay["legal_hold_ref"]) == legal_hold_ref
                    ):
                        return True
                    raise ValueError("legal-hold idempotency key conflicts with prior transition")
                updated = await conn.execute(
                    """
                    UPDATE cost_governance_validation_retention
                       SET revision = revision + 1,
                           legal_hold = %s,
                           legal_hold_ref = %s,
                           updated_at = %s
                     WHERE evidence_kind = %s
                       AND evidence_id = %s
                       AND revision = %s
                       AND purged_at IS NULL
                    """,
                    (
                        legal_hold_ref is not None,
                        legal_hold_ref,
                        recorded_at,
                        evidence_kind,
                        evidence_id,
                        expected_revision,
                    ),
                )
                if updated.rowcount != 1:
                    return False
                await conn.execute(
                    """
                    INSERT INTO cost_governance_validation_retention_event (
                        evidence_kind, evidence_id, revision, event_kind,
                        legal_hold_ref, recorded_at, idempotency_key
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        evidence_kind,
                        evidence_id,
                        expected_revision + 1,
                        expected_event,
                        legal_hold_ref,
                        recorded_at,
                        idempotency_key,
                    ),
                )
                return True

    async def purge_validation_evidence(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[tuple[str, str], ...]:
        """Tombstone at most ``limit`` expired records without deleting audit evidence."""

        _limit(limit)
        purged: list[tuple[str, str]] = []
        async with await self._connect() as conn:
            async with conn.transaction():
                await self._timeout(conn)
                cursor = await conn.execute(
                    """
                    SELECT evidence_kind, evidence_id, revision
                      FROM cost_governance_validation_retention
                     WHERE purge_after <= %s
                       AND purged_at IS NULL
                       AND NOT legal_hold
                     ORDER BY purge_after, evidence_kind, evidence_id
                     LIMIT %s
                     FOR UPDATE SKIP LOCKED
                    """,
                    (now, limit),
                )
                for row in await cursor.fetchall():
                    kind = cast(str, row["evidence_kind"])
                    evidence_id = cast(str, row["evidence_id"])
                    revision = cast(int, row["revision"])
                    await conn.execute(
                        """
                        UPDATE cost_governance_validation_retention
                           SET revision = revision + 1, purged_at = %s, updated_at = %s
                         WHERE evidence_kind = %s AND evidence_id = %s AND revision = %s
                        """,
                        (now, now, kind, evidence_id, revision),
                    )
                    await conn.execute(
                        """
                        INSERT INTO cost_governance_validation_retention_event (
                            evidence_kind, evidence_id, revision, event_kind,
                            legal_hold_ref, recorded_at, idempotency_key
                        )
                        VALUES (%s, %s, %s, 'purged', NULL, %s, %s)
                        """,
                        (kind, evidence_id, revision + 1, now, f"purged:{kind}:{evidence_id}"),
                    )
                    purged.append((kind, evidence_id))
        return tuple(purged)

    async def _initialize_retention(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        evidence_kind: str,
        evidence_id: str,
        retention_until: datetime,
        recorded_at: datetime,
        legal_hold: bool,
        legal_hold_ref: str | None,
        idempotency_key: str,
    ) -> None:
        inserted = await conn.execute(
            """
            INSERT INTO cost_governance_validation_retention (
                evidence_kind, evidence_id, revision, retention_until, purge_after,
                legal_hold, legal_hold_ref, updated_at
            )
            VALUES (%s, %s, 1, %s, %s, %s, %s, %s)
            """,
            (
                evidence_kind,
                evidence_id,
                retention_until,
                retention_until,
                legal_hold,
                legal_hold_ref,
                recorded_at,
            ),
        )
        if inserted.rowcount != 1:
            raise RuntimeError("validation retention initialization conflicted")
        await conn.execute(
            """
            INSERT INTO cost_governance_validation_retention_event (
                evidence_kind, evidence_id, revision, event_kind,
                legal_hold_ref, recorded_at, idempotency_key
            )
            VALUES (%s, %s, 1, 'created', %s, %s, %s)
            """,
            (
                evidence_kind,
                evidence_id,
                legal_hold_ref,
                recorded_at,
                idempotency_key,
            ),
        )

    async def _connect(self) -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(
            self._dsn.replace("postgresql+psycopg://", "postgresql://", 1),
            row_factory=dict_row,
            connect_timeout=self._connect_timeout_s,
        )

    async def _timeout(self, conn: psycopg.AsyncConnection[Any]) -> None:
        await conn.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self._statement_timeout_ms),),
        )


def _receipt_from_payload(value: dict[str, Any]) -> CostLifecycleReceipt:
    pin = _pin_from_payload(cast(dict[str, Any], value["revision_pin"]))
    return CostLifecycleReceipt(
        schema_version=cast(str, value["schema_version"]),
        receipt_id=cast(str, value["receipt_id"]),
        idempotency_key=cast(str, value["idempotency_key"]),
        operation=CostLifecycleOperation(cast(str, value["operation"])),
        outcome=CostLifecycleOutcome(cast(str, value["outcome"])),
        revision_pin=pin,
        available=cast(bool, value["available"]),
        enabled=cast(bool, value["enabled"]),
        occurred_at=datetime.fromisoformat(cast(str, value["occurred_at"])),
        evidence_kind=CostEvidenceKind(cast(str, value["evidence_kind"])),
        evidence_refs=tuple(cast(list[str], value["evidence_refs"])),
        retention_until=datetime.fromisoformat(cast(str, value["retention_until"])),
        legal_hold=cast(bool, value["legal_hold"]),
        legal_hold_ref=cast(str | None, value["legal_hold_ref"]),
    )


def _pin_from_payload(value: dict[str, Any]) -> CostRevisionPin:
    return CostRevisionPin(
        package_id=cast(str, value["package_id"]),
        package_version=cast(str, value["package_version"]),
        source_revision=cast(str, value["source_revision"]),
        wheel_digest=cast(str, value["wheel_digest"]),
        image_digest=cast(str, value["image_digest"]),
        asset_manifest_digest=cast(str, value["asset_manifest_digest"]),
        semantic_profile_digest=cast(str, value["semantic_profile_digest"]),
        ontology_release_digest=cast(str, value["ontology_release_digest"]),
        runtime_config_digest=cast(str, value["runtime_config_digest"]),
        activation_revision=cast(int, value["activation_revision"]),
    )


def _episode_from_payload(value: dict[str, Any]) -> CostCampaignEpisode:
    return CostCampaignEpisode(
        schema_version=cast(str, value["schema_version"]),
        campaign_id=cast(str, value["campaign_id"]),
        episode_id=cast(str, value["episode_id"]),
        revision=cast(int, value["revision"]),
        idempotency_key=cast(str, value["idempotency_key"]),
        revision_pin_digest=cast(str, value["revision_pin_digest"]),
        evidence_kind=CostEvidenceKind(cast(str, value["evidence_kind"])),
        outcome=CostCampaignOutcome(cast(str, value["outcome"])),
        reason=cast(str, value["reason"]),
        target_refs=tuple(cast(list[str], value["target_refs"])),
        settlement_statuses=tuple(
            CostCampaignSettlement(item) for item in cast(list[str], value["settlement_statuses"])
        ),
        recovery_attempts=cast(int, value["recovery_attempts"]),
        policy_excluded=cast(bool, value["policy_excluded"]),
        policy_escape=cast(bool, value["policy_escape"]),
        objective_regression=cast(bool, value["objective_regression"]),
        audit_complete=cast(bool, value["audit_complete"]),
        hard_dependencies_complete=cast(bool, value["hard_dependencies_complete"]),
        unauthorized_disclosure=cast(bool, value["unauthorized_disclosure"]),
        ontology_competency_passed=cast(bool, value["ontology_competency_passed"]),
        topic_owner_correct=cast(bool, value["topic_owner_correct"]),
        protected_objectives_complete=cast(bool, value["protected_objectives_complete"]),
        safeguards_complete=cast(bool, value["safeguards_complete"]),
        effect_path_complete=cast(bool, value["effect_path_complete"]),
        parity_explained=cast(bool, value["parity_explained"]),
        rollback_evidence_complete=cast(bool, value["rollback_evidence_complete"]),
        decision_correct=cast(bool, value["decision_correct"]),
        observed_at=datetime.fromisoformat(cast(str, value["observed_at"])),
        evidence_refs=tuple(cast(list[str], value["evidence_refs"])),
        retention_until=datetime.fromisoformat(cast(str, value["retention_until"])),
        legal_hold=cast(bool, value["legal_hold"]),
        legal_hold_ref=cast(str | None, value["legal_hold_ref"]),
    )


def _limit(value: int) -> None:
    if not 1 <= value <= 10_000:
        raise ValueError("validation store limit MUST be in [1, 10000]")


__all__ = ["PostgresCostGovernanceValidationStore"]
