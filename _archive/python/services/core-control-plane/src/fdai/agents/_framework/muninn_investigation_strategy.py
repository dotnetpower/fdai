"""Muninn-owned durable cohort sink for adaptive strategy comparisons."""

from __future__ import annotations

import logging
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
from .outbox_publication import (
    PublicationClaim,
    claim_expired,
    claim_matches,
    new_publication_claim_owner,
    publish_claimed_outbox,
)

_PREFIX = "operational-learning:investigation-strategy:"
_MAX_COMPARISONS = 100
_RECORD_RECOVERY_PAGE = 16
_LOGGER = logging.getLogger(__name__)


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

        await self._recover_pending_publications_best_effort()
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
        payload = {
            "producer_principal": "Muninn",
            "kind": "investigation_strategy_comparison_cohort",
            "correlation_id": pair_digest,
            "idempotency_key": f"investigation-strategy:{cohort_digest}",
            "cohort_digest": cohort_digest,
            "comparisons": cohort_mappings,
        }
        claim = await self._claim_publication(
            key=published_key,
            cohort_digest=cohort_digest,
            pair_digest=pair_digest,
            comparison_count=len(cohort),
            payload=payload,
        )
        if claim is None:
            return
        await self._publish_claimed_publication(
            key=published_key,
            payload=payload,
            claim=claim,
        )
        await self._state_store.delete_states_beyond(
            f"{_PREFIX}{pair_digest}:published:",
            retain_newest=_MAX_COMPARISONS,
        )

    async def recover_pending_publications(self, *, limit: int = _MAX_COMPARISONS) -> int:
        """Republish durable cohort rows left pending by a failed broker publish."""

        published = 0
        attempted_keys: set[str] = set()
        pending_rows, pending_total = await self._state_store.read_state_page(
            _PREFIX,
            limit=limit,
            field="state",
            value="pending",
        )
        publishing_rows, publishing_total = await self._state_store.read_state_page(
            _PREFIX,
            limit=limit,
            field="state",
            value="publishing",
        )
        for row in (*pending_rows, *publishing_rows)[
            : min(limit, pending_total + publishing_total)
        ]:
            key = str(row.get("publication_key") or "")
            payload = row.get("payload")
            if not key or key in attempted_keys or not isinstance(payload, Mapping):
                continue
            attempted_keys.add(key)
            try:
                claim = await self._claim_existing_publication(key)
                if claim is None:
                    continue
                if await self._publish_claimed_publication(
                    key=key,
                    payload=payload,
                    claim=claim,
                ):
                    published += 1
            except Exception as exc:
                _LOGGER.warning(
                    "muninn_investigation_strategy_publication_recovery_deferred",
                    extra={"error_type": type(exc).__name__, "publication_key": key},
                )
                continue
        return published

    async def _recover_pending_publications_best_effort(self) -> None:
        try:
            await self.recover_pending_publications(limit=_RECORD_RECOVERY_PAGE)
        except Exception as exc:
            _LOGGER.warning(
                "muninn_investigation_strategy_publication_recovery_unavailable",
                extra={"error_type": type(exc).__name__},
            )

    async def _claim_publication(
        self,
        *,
        key: str,
        cohort_digest: str,
        pair_digest: str,
        comparison_count: int,
        payload: Mapping[str, object],
    ) -> PublicationClaim | None:
        pending = self._publication_record(
            key=key,
            cohort_digest=cohort_digest,
            pair_digest=pair_digest,
            comparison_count=comparison_count,
            payload=payload,
            revision=0,
            state="pending",
            claim_owner="",
            claimed_at="",
        )
        created = await self._state_store.write_state_with_audit_if_absent(
            key,
            pending,
            {
                "kind": "investigation_strategy_cohort_pending",
                "principal": "Muninn",
                "cohort_digest": cohort_digest,
                "revision": 0,
            },
        )
        if not created:
            existing = await self._state_store.read_state(key)
            if existing is None:
                raise RuntimeError("investigation strategy publication claim disappeared")
            if existing.get("state") == "published":
                return None
            if (
                existing.get("cohort_digest") != cohort_digest
                or existing.get("pair_digest") != pair_digest
                or existing.get("payload") != dict(payload)
            ):
                raise ValueError("investigation strategy publication claim conflicts")
        return await self._claim_existing_publication(key)

    async def _claim_existing_publication(self, key: str) -> PublicationClaim | None:
        existing = await self._state_store.read_state(key)
        if existing is None:
            raise RuntimeError("investigation strategy publication claim disappeared")
        if existing.get("state") == "published":
            return None
        if existing.get("state") == "publishing" and not claim_expired(
            claimed_at=existing.get("claimed_at"),
            now=self._clock(),
            lease=self._claim_lease,
        ):
            return None
        if existing.get("state") not in {"pending", "publishing"}:
            raise ValueError("investigation strategy publication claim state is invalid")
        revision = _integer(existing, "revision")
        claimed_at = self._clock().isoformat()
        claim_owner = new_publication_claim_owner("Muninn")
        advanced = await self._state_store.compare_and_set_state_with_audit(
            key,
            {
                **dict(existing),
                "state": "publishing",
                "revision": revision + 1,
                "claim_owner": claim_owner,
                "claimed_at": claimed_at,
            },
            expected_revision=revision,
            audit_entry={
                "kind": "investigation_strategy_cohort_claimed",
                "principal": "Muninn",
                "cohort_digest": str(existing.get("cohort_digest") or ""),
                "revision": revision + 1,
            },
        )
        return PublicationClaim(owner=claim_owner, claimed_at=claimed_at) if advanced else None

    async def _publish_claimed_publication(
        self,
        *,
        key: str,
        payload: Mapping[str, object],
        claim: PublicationClaim,
    ) -> bool:
        return await publish_claimed_outbox(
            claim,
            publish=lambda: self._bus.publish("Muninn", "object.context-index", dict(payload)),
            mark_published=lambda active_claim: self._mark_publication_published(
                key,
                active_claim,
            ),
            release=lambda active_claim: self._release_publication_claim(key, active_claim),
            lease=self._claim_lease,
        )

    @staticmethod
    def _publication_record(
        *,
        key: str,
        cohort_digest: str,
        pair_digest: str,
        comparison_count: int,
        payload: Mapping[str, object],
        revision: int,
        state: str,
        claim_owner: str,
        claimed_at: str,
    ) -> dict[str, object]:
        return {
            "publication_key": key,
            "cohort_digest": cohort_digest,
            "pair_digest": pair_digest,
            "comparison_count": comparison_count,
            "payload": dict(payload),
            "state": state,
            "revision": revision,
            "claim_owner": claim_owner,
            "claimed_at": claimed_at,
            "execution_authority": False,
            "promotion_authority": False,
        }

    async def _mark_publication_published(self, key: str, claim: PublicationClaim) -> bool:
        existing = await self._state_store.read_state(key)
        if existing is None or existing.get("state") == "published":
            return False
        if not claim_matches(existing, claim):
            return False
        revision = _integer(existing, "revision")
        return await self._state_store.compare_and_set_state_with_audit(
            key,
            {
                **dict(existing),
                "state": "published",
                "revision": revision + 1,
            },
            expected_revision=revision,
            audit_entry={
                "kind": "investigation_strategy_cohort_published",
                "principal": "Muninn",
                "cohort_digest": str(existing.get("cohort_digest") or ""),
                "revision": revision + 1,
            },
        )

    async def _release_publication_claim(self, key: str, claim: PublicationClaim) -> None:
        existing = await self._state_store.read_state(key)
        if existing is None or existing.get("state") != "publishing":
            return
        if not claim_matches(existing, claim):
            return
        revision = _integer(existing, "revision")
        await self._state_store.compare_and_set_state_with_audit(
            key,
            {
                **dict(existing),
                "state": "pending",
                "revision": revision + 1,
                "claim_owner": "",
                "claimed_at": "",
            },
            expected_revision=revision,
            audit_entry={
                "kind": "investigation_strategy_cohort_released",
                "principal": "Muninn",
                "cohort_digest": str(existing.get("cohort_digest") or ""),
                "revision": revision + 1,
            },
        )


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if type(item) is not int or item < 0:
        raise ValueError(f"investigation strategy {key} MUST be non-negative")
    return item


__all__ = ["MuninnInvestigationStrategyCohortSink"]
