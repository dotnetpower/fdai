"""Heimdall-owned complete posture evidence production."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypeVar

import psycopg

from fdai.core.assurance_twin import (
    AssuranceTwinEvaluationUnavailableError,
    CompletePostureEvaluation,
    InMemoryProjection,
)
from fdai.delivery.assurance_twin_evidence_source import (
    AssuranceTwinEvidenceClockCapacityError,
    AssuranceTwinEvidenceClockContentionError,
    AssuranceTwinEvidenceExpiredError,
    StateStoreTwinEvidenceRepository,
)
from fdai.delivery.assurance_twin_inventory import (
    AssuranceTwinInventoryChangedError,
    TwinInventoryRevision,
    TwinInventoryUnavailableError,
)
from fdai.delivery.assurance_twin_writers import AssuranceTwinPublishRequest, findings_digest

_LOG = logging.getLogger(__name__)
_FRESHNESS_TTL = timedelta(minutes=30)
_FenceResult = TypeVar("_FenceResult")


class TwinInventorySource(Protocol):
    async def load(
        self,
        *,
        now: datetime,
        freshness_ttl: timedelta,
        required_scopes: tuple[str, ...],
    ) -> TwinInventoryRevision: ...

    async def load_at_revision(
        self,
        *,
        expected_revision: str,
        now: datetime,
        freshness_ttl: timedelta,
        required_scopes: tuple[str, ...],
    ) -> TwinInventoryRevision: ...

    async def run_at_revision(
        self,
        *,
        expected_revision: str,
        now: datetime,
        freshness_ttl: timedelta,
        required_scopes: tuple[str, ...],
        operation: Callable[[], Awaitable[_FenceResult]],
    ) -> _FenceResult: ...


class CompletePostureEvaluator(Protocol):
    async def evaluate_assurance_twin_posture(
        self,
        *,
        projection: InMemoryProjection,
        inventory_revision: str,
    ) -> CompletePostureEvaluation: ...

    async def run_assurance_twin_if_current(
        self,
        *,
        rule_generation_revision: str,
        operation: Callable[[], Awaitable[_FenceResult]],
    ) -> _FenceResult | None: ...


class AssuranceTwinPostureProducer:
    """Record only complete exact-revision T0 evidence for Heimdall."""

    owner = "Heimdall"

    def __init__(
        self,
        *,
        inventory: TwinInventorySource,
        evaluator: CompletePostureEvaluator,
        repository: StateStoreTwinEvidenceRepository,
        scope: str,
        required_scopes: tuple[str, ...],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not scope.strip():
            raise ValueError("Assurance Twin posture scope MUST be non-empty")
        if not required_scopes or required_scopes != tuple(sorted(set(required_scopes))):
            raise ValueError("Assurance Twin Inventory scopes MUST be non-empty and canonical")
        self._inventory = inventory
        self._evaluator = evaluator
        self._repository = repository
        self._scope = scope
        self._required_scopes = required_scopes
        self._clock = clock or (lambda: datetime.now(UTC))

    async def produce_once(self) -> AssuranceTwinPublishRequest | None:
        """Evaluate and retain one current generation, or abstain explicitly."""

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Assurance Twin producer clock MUST be timezone-aware")
        try:
            inventory = await self._inventory.load(
                now=now,
                freshness_ttl=_FRESHNESS_TTL,
                required_scopes=self._required_scopes,
            )
            evaluation = await self._evaluator.evaluate_assurance_twin_posture(
                projection=inventory.projection,
                inventory_revision=inventory.source_revision,
            )
        except (
            AssuranceTwinEvaluationUnavailableError,
            TwinInventoryUnavailableError,
            psycopg.Error,
        ) as exc:
            _LOG.info(
                "assurance_twin_posture_evidence_unavailable",
                extra={"reason": type(exc).__name__},
            )
            return None

        source_revision = _digest(
            {
                "inventory_revision": inventory.source_revision,
                "rule_set_digest": evaluation.rule_set_digest,
                "rule_generation_digest": evaluation.rule_generation_digest,
                "rule_generation_time": evaluation.rule_generation_time.isoformat(),
                "coverage_refs": evaluation.coverage_refs,
                "findings_digest": findings_digest(evaluation.findings),
            }
        )
        generated_at = now
        fresh_until = inventory.completed_at + _FRESHNESS_TTL
        if generated_at >= fresh_until:
            _LOG.info(
                "assurance_twin_posture_evidence_unavailable",
                extra={"reason": "rule_generation_after_inventory_expiry"},
            )
            return None

        async def record() -> AssuranceTwinPublishRequest | None:
            try:
                return await self._repository.record_posture(
                    scope=self._scope,
                    source_revision=source_revision,
                    findings=evaluation.findings,
                    evaluated_rule_ids=evaluation.evaluated_rule_ids,
                    coverage_refs=evaluation.coverage_refs,
                    rule_set_revision=evaluation.rule_set_digest,
                    rule_generation_revision=evaluation.rule_generation_digest,
                    inventory_revision=inventory.source_revision,
                    generated_at=generated_at,
                    fresh_until=fresh_until,
                    correlation_id=f"assurance-twin-posture:{source_revision}",
                )
            except (
                AssuranceTwinEvidenceClockCapacityError,
                AssuranceTwinEvidenceClockContentionError,
                AssuranceTwinEvidenceExpiredError,
                psycopg.Error,
            ) as exc:
                _LOG.warning(
                    "assurance_twin_posture_evidence_write_unavailable",
                    extra={"reason": type(exc).__name__},
                )
                return None

        try:
            return await self._evaluator.run_assurance_twin_if_current(
                rule_generation_revision=evaluation.rule_generation_digest,
                operation=lambda: self.run_assurance_twin_inventory_if_current(
                    inventory_revision=inventory.source_revision,
                    operation=record,
                ),
            )
        except AssuranceTwinInventoryChangedError as exc:
            _LOG.info(
                "assurance_twin_inventory_revision_unavailable",
                extra={"reason": type(exc).__name__},
            )
            return None

    async def run_assurance_twin_inventory_if_current(
        self,
        *,
        inventory_revision: str,
        operation: Callable[[], Awaitable[_FenceResult]],
    ) -> _FenceResult | None:
        try:
            return await self._inventory.run_at_revision(
                expected_revision=inventory_revision,
                now=self._clock(),
                freshness_ttl=_FRESHNESS_TTL,
                required_scopes=self._required_scopes,
                operation=operation,
            )
        except AssuranceTwinInventoryChangedError as exc:
            affected_request = (
                exc.result
                if isinstance(exc.result, AssuranceTwinPublishRequest)
                else getattr(exc.result, "request", None)
            )
            if isinstance(affected_request, AssuranceTwinPublishRequest):
                await self._repository.mark_inventory_changed(affected_request)
            raise
        except (TwinInventoryUnavailableError, psycopg.Error) as exc:
            _LOG.info(
                "assurance_twin_inventory_revision_unavailable",
                extra={"reason": type(exc).__name__},
            )
            return None

    async def run(self, stop: asyncio.Event, *, interval_seconds: float = 300.0) -> None:
        if interval_seconds <= 0:
            raise ValueError("Assurance Twin posture producer interval MUST be positive")
        while not stop.is_set():
            await self.produce_once()
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AssuranceTwinPostureProducer",
    "CompletePostureEvaluator",
    "TwinInventorySource",
]
