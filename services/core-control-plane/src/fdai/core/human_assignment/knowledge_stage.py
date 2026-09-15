"""Owner-local durable handover dispositions; typed events alone connect independent owners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai_service_contracts.handover_knowledge import (
    HandoverKnowledgeDecision,
    HandoverKnowledgeNotice,
)

from fdai.core.human_assignment.knowledge_source import HandoverKnowledgeSourceCheck
from fdai.shared.providers.state_store import StateStore

_OWNERS = frozenset({"Forseti", "Muninn", "Norns", "Mimir"})


@dataclass(frozen=True, slots=True)
class HandoverKnowledgeStage:
    """One owner's source check plus its own monotonic CAS/audit projection, never peer state."""

    owner: str
    store: StateStore
    source: HandoverKnowledgeSourceCheck
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def __post_init__(self) -> None:
        if self.owner not in _OWNERS:
            raise ValueError("handover stage owner is unsupported")

    async def check(self, notice: HandoverKnowledgeNotice) -> HandoverKnowledgeDecision:
        """Revalidate before each owner acts; source failures become explicit held outcomes."""
        try:
            notice.require_current(self.clock())
        except ValueError:
            return HandoverKnowledgeDecision(
                notice=notice,
                disposition="held",
                reason="check_expired",
            )
        try:
            return await self.source.check(notice)
        except Exception:  # noqa: BLE001 - no exception values enter the owned event
            return HandoverKnowledgeDecision(
                notice=notice,
                disposition="held",
                reason="source_unavailable",
            )

    async def already_recorded(self, decision: HandoverKnowledgeDecision) -> bool:
        """Read only this owner's exact prior receipt after independent source revalidation."""
        current = await self.store.read_state(
            f"human_assignment:knowledge:{self.owner}:{decision.notice.source_id}"
        )
        if current is None:
            return False
        prior = HandoverKnowledgeDecision.model_validate(current.get("decision"))
        return (
            prior.disposition == decision.disposition
            and prior.notice.goal_revision == decision.notice.goal_revision
            and prior.notice.source_digest == decision.notice.source_digest
            and prior.evidence_refs == decision.evidence_refs
            and prior.evidence_digests == decision.evidence_digests
        )

    async def record(self, decision: HandoverKnowledgeDecision) -> HandoverKnowledgeDecision:
        """Persist before publication; withdrawal is irreversible for that source revision.

        Exact repeated delivery may republish the same event after a bus interruption. Every
        consumer rechecks its source and deduplicates its own materialization independently.
        """
        notice = decision.notice
        key = f"human_assignment:knowledge:{self.owner}:{notice.source_id}"
        for _attempt in range(4):
            current = await self.store.read_state(key)
            revision = 0
            if current is not None:
                stored_revision = current.get("revision")
                if type(stored_revision) is not int or stored_revision < 1:
                    raise ValueError("handover owner stage revision is malformed")
                revision = stored_revision
                prior = HandoverKnowledgeDecision.model_validate(current.get("decision"))
                if (
                    prior.disposition == "withdrawn"
                    and prior.notice.goal_revision >= notice.goal_revision
                ):
                    return HandoverKnowledgeDecision(
                        notice=notice,
                        disposition="withdrawn",
                        reason="source_withdrawn",
                    )
                old_order = (prior.notice.goal_revision, prior.notice.check_epoch)
                new_order = (notice.goal_revision, notice.check_epoch)
                if old_order > new_order:
                    return HandoverKnowledgeDecision(
                        notice=notice,
                        disposition="held",
                        reason="source_changed",
                    )
                if old_order == new_order and prior.notice.source_digest != notice.source_digest:
                    decision = HandoverKnowledgeDecision(
                        notice=notice,
                        disposition="conflict",
                        reason="evidence_conflict",
                    )
                if current.get("decision") == decision.model_dump(mode="json"):
                    return decision
            value = {"revision": revision + 1, "decision": decision.model_dump(mode="json")}
            audit = {
                "actor": self.owner,
                "action_kind": "handover.knowledge.owner_disposition",
                "source_id": notice.source_id,
                "goal_revision": notice.goal_revision,
                "disposition": decision.disposition,
                "execution_authority": False,
                "idempotency_key": f"{self.owner}:{notice.notice_id}:{decision.disposition}",
                "recorded_at": self.clock().isoformat(),
            }
            if current is None:
                applied = await self.store.write_state_with_audit_if_absent(key, value, audit)
            else:
                applied = await self.store.compare_and_set_state_with_audit(
                    key, value, expected_revision=revision, audit_entry=audit
                )
            if applied:
                return decision
        raise RuntimeError("handover owner stage changed concurrently")


__all__ = ["HandoverKnowledgeStage"]
