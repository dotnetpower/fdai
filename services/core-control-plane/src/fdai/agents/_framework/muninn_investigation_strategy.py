"""Muninn-owned durable cohort sink for adaptive strategy comparisons."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.operational_learning import InvestigationStrategyComparisonEvidence
from fdai.core.rca.discrimination_shadow import (
    ChallengerComparisonOutcome,
    DiscriminationShadowComparison,
)
from fdai.shared.providers.state_store import StateStore

from .bus import PantheonBus

_PREFIX = "operational-learning:investigation-strategy:"
_MAX_COMPARISONS = 100


class MuninnInvestigationStrategyCohortSink:
    """Persist exact comparisons and publish balanced cohorts as Muninn."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        bus: PantheonBus,
        clock: Callable[[], datetime] | None = None,
        claim_lease_seconds: int = 30,
    ) -> None:
        if not 1 <= claim_lease_seconds <= 300:
            raise ValueError("claim_lease_seconds MUST be in [1, 300]")
        self._state_store = state_store
        self._bus = bus
        self._clock = clock or (lambda: datetime.now(UTC))
        self._claim_lease = timedelta(seconds=claim_lease_seconds)

    async def record(self, comparison: DiscriminationShadowComparison) -> None:
        """Deduplicate one comparison and publish its complete balanced cohort."""

        evidence = InvestigationStrategyComparisonEvidence.from_shadow(comparison)
        pair_digest = content_digest(
            {
                "active_strategy_digest": evidence.active_strategy_digest,
                "challenger_strategy_digest": evidence.challenger_strategy_digest,
            }
        )
        prefix = f"{_PREFIX}{pair_digest}:comparison:"
        key = f"{prefix}{evidence.comparison_digest}"
        mapping = evidence.to_mapping()
        created = await self._state_store.write_state_if_absent(key, mapping)
        if not created:
            existing = await self._state_store.read_state(key)
            if existing is None or dict(existing) != mapping:
                raise ValueError("investigation strategy comparison idempotency conflict")
        await self._state_store.delete_states_beyond(
            prefix,
            retain_newest=_MAX_COMPARISONS,
        )
        rows = await self._state_store.read_states(prefix, limit=_MAX_COMPARISONS)
        cohort = tuple(
            sorted(
                (InvestigationStrategyComparisonEvidence.from_mapping(row) for row in rows),
                key=lambda item: item.comparison_digest,
            )
        )
        outcomes = {item.challenger_outcome for item in cohort}
        if ChallengerComparisonOutcome.IMPROVEMENT not in outcomes or not outcomes.intersection(
            {
                ChallengerComparisonOutcome.NON_IMPROVEMENT,
                ChallengerComparisonOutcome.CONTROL,
            }
        ):
            return
        cohort_mappings = [item.to_mapping() for item in cohort]
        cohort_digest = content_digest(
            {
                "pair_digest": pair_digest,
                "comparison_digests": [item.comparison_digest for item in cohort],
            }
        )
        published_key = f"{_PREFIX}{pair_digest}:published:{cohort_digest}"
        claim_revision = await self._claim_publication(
            key=published_key,
            cohort_digest=cohort_digest,
            pair_digest=pair_digest,
            comparison_count=len(cohort),
        )
        if claim_revision is None:
            return
        await self._bus.publish(
            "Muninn",
            "object.context-index",
            {
                "producer_principal": "Muninn",
                "kind": "investigation_strategy_comparison_cohort",
                "correlation_id": pair_digest,
                "idempotency_key": f"investigation-strategy:{cohort_digest}",
                "cohort_digest": cohort_digest,
                "comparisons": cohort_mappings,
            },
        )
        published = await self._state_store.compare_and_set_state_with_audit(
            published_key,
            {
                "cohort_digest": cohort_digest,
                "pair_digest": pair_digest,
                "comparison_count": len(cohort),
                "state": "published",
                "revision": claim_revision + 1,
                "claimed_at": self._clock().isoformat(),
                "execution_authority": False,
                "promotion_authority": False,
            },
            expected_revision=claim_revision,
            audit_entry={
                "kind": "investigation_strategy_cohort_published",
                "principal": "Muninn",
                "cohort_digest": cohort_digest,
                "revision": claim_revision + 1,
            },
        )
        if not published:
            raise RuntimeError("investigation strategy publication claim changed")
        await self._state_store.delete_states_beyond(
            f"{_PREFIX}{pair_digest}:published:",
            retain_newest=_MAX_COMPARISONS,
        )

    async def _claim_publication(
        self,
        *,
        key: str,
        cohort_digest: str,
        pair_digest: str,
        comparison_count: int,
    ) -> int | None:
        now = self._clock()
        claim = self._claim_record(
            cohort_digest=cohort_digest,
            pair_digest=pair_digest,
            comparison_count=comparison_count,
            revision=0,
            claimed_at=now,
        )
        created = await self._state_store.write_state_with_audit_if_absent(
            key,
            claim,
            {
                "kind": "investigation_strategy_cohort_claimed",
                "principal": "Muninn",
                "cohort_digest": cohort_digest,
                "revision": 0,
            },
        )
        if created:
            return 0
        existing = await self._state_store.read_state(key)
        if existing is None:
            raise RuntimeError("investigation strategy publication claim disappeared")
        if existing.get("state") == "published":
            return None
        if (
            existing.get("cohort_digest") != cohort_digest
            or existing.get("pair_digest") != pair_digest
        ):
            raise ValueError("investigation strategy publication claim conflicts")
        revision = _integer(existing, "revision")
        claimed_at = _timestamp(existing, "claimed_at")
        if now - claimed_at < self._claim_lease:
            return None
        replacement = self._claim_record(
            cohort_digest=cohort_digest,
            pair_digest=pair_digest,
            comparison_count=comparison_count,
            revision=revision + 1,
            claimed_at=now,
        )
        reclaimed = await self._state_store.compare_and_set_state_with_audit(
            key,
            replacement,
            expected_revision=revision,
            audit_entry={
                "kind": "investigation_strategy_cohort_reclaimed",
                "principal": "Muninn",
                "cohort_digest": cohort_digest,
                "revision": revision + 1,
            },
        )
        return revision + 1 if reclaimed else None

    @staticmethod
    def _claim_record(
        *,
        cohort_digest: str,
        pair_digest: str,
        comparison_count: int,
        revision: int,
        claimed_at: datetime,
    ) -> dict[str, object]:
        return {
            "cohort_digest": cohort_digest,
            "pair_digest": pair_digest,
            "comparison_count": comparison_count,
            "state": "claimed",
            "revision": revision,
            "claimed_at": claimed_at.isoformat(),
            "execution_authority": False,
            "promotion_authority": False,
        }


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if type(item) is not int or item < 0:
        raise ValueError(f"investigation strategy {key} MUST be non-negative")
    return item


def _timestamp(value: Mapping[str, object], key: str) -> datetime:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"investigation strategy {key} MUST be text")
    parsed = datetime.fromisoformat(item)
    if parsed.tzinfo is None:
        raise ValueError(f"investigation strategy {key} MUST be timezone-aware")
    return parsed


__all__ = ["MuninnInvestigationStrategyCohortSink"]
