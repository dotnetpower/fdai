"""Audited runner for immutable operational promotion evidence batches."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.providers.state_store import StateStore

from .operational_promotion import (
    OperationalPromotionBatch,
    OperationalPromotionEvaluator,
    OperationalPromotionReceipt,
)


class OperationalPromotionEvidenceSource(Protocol):
    async def load_batch(
        self,
        *,
        action_type_name: str,
        fdai_revision: str,
        scenario_set_version: str,
    ) -> OperationalPromotionBatch: ...


@dataclass(frozen=True, slots=True)
class OperationalPromotionRunResult:
    action_type_name: str
    receipt: OperationalPromotionReceipt | None
    aborted_reason: str | None = None


class OperationalPromotionMeasurementRunner:
    """Measure and audit readiness; never mutate promotion state."""

    def __init__(
        self,
        *,
        source: OperationalPromotionEvidenceSource,
        evaluator: OperationalPromotionEvaluator,
        audit_store: StateStore,
        fdai_revision: str,
        scenario_set_version: str,
    ) -> None:
        if not fdai_revision or not scenario_set_version:
            raise ValueError("operational promotion runner identity MUST be non-empty")
        self._source = source
        self._evaluator = evaluator
        self._audit_store = audit_store
        self._revision = fdai_revision
        self._scenario = scenario_set_version

    async def run(
        self,
        action_types: Sequence[OntologyActionType],
    ) -> tuple[OperationalPromotionRunResult, ...]:
        results: list[OperationalPromotionRunResult] = []
        for action_type in sorted(action_types, key=lambda item: item.name):
            try:
                batch = await self._source.load_batch(
                    action_type_name=action_type.name,
                    fdai_revision=self._revision,
                    scenario_set_version=self._scenario,
                )
                receipt = self._evaluator.evaluate(action_type, batch)
            except Exception as exc:  # noqa: BLE001 - source boundary, audited fail-closed
                reason = f"evidence_load_failed:{type(exc).__name__}"
                await self._audit_store.append_audit_entry(
                    self._audit_entry(
                        action_type_name=action_type.name,
                        ready=False,
                        evidence_digest=None,
                        gaps=(reason,),
                        metrics={},
                    )
                )
                results.append(
                    OperationalPromotionRunResult(
                        action_type_name=action_type.name,
                        receipt=None,
                        aborted_reason=reason,
                    )
                )
                continue
            await self._audit_store.append_audit_entry(
                self._audit_entry(
                    action_type_name=action_type.name,
                    ready=receipt.ready,
                    evidence_digest=receipt.evidence_digest,
                    gaps=receipt.gaps,
                    metrics={
                        "sample_count": receipt.sample_count,
                        "accuracy": receipt.accuracy,
                        "accuracy_ci_lower": receipt.accuracy_ci_lower,
                        "accuracy_ci_upper": receipt.accuracy_ci_upper,
                        "policy_escapes": receipt.policy_escapes,
                        "rollback_rate": receipt.rollback_rate,
                        "recurrence_rate": receipt.recurrence_rate,
                        "simulation_review_rate": receipt.simulation_review_rate,
                    },
                )
            )
            results.append(
                OperationalPromotionRunResult(
                    action_type_name=action_type.name,
                    receipt=receipt,
                )
            )
        return tuple(results)

    def _audit_entry(
        self,
        *,
        action_type_name: str,
        ready: bool,
        evidence_digest: str | None,
        gaps: tuple[str, ...],
        metrics: dict[str, object],
    ) -> dict[str, object]:
        return {
            "actor": "fdai.core.measurement",
            "action_kind": "operational_promotion.measured",
            "mode": "shadow",
            "fdai_revision": self._revision,
            "scenario_set_version": self._scenario,
            "action_type_name": action_type_name,
            "ready": ready,
            "evidence_digest": evidence_digest,
            "gaps": list(gaps),
            **metrics,
            "recorded_at": datetime.now(tz=UTC).isoformat(),
        }


__all__ = [
    "OperationalPromotionEvidenceSource",
    "OperationalPromotionMeasurementRunner",
    "OperationalPromotionRunResult",
]
