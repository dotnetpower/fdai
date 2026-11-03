"""Bound repeated full-reconciliation Resource events to Resources whose observation changed.

Every promoted inventory generation is a complete observation, but a Resource whose recorded
properties, provider reference, type, and property-freshness metadata equal the previous delivered
generation carries no new evidence for deterministic rule evaluation. Re-sending it only forces the
control loop, Saga ingress retention, and Heimdall to persist the same judgment again. This policy
omits such Resources and still bounds staleness: a full redelivery is required when the previous
generation was not fully delivered, no full redelivery is on record, or the redelivery interval
elapsed. The policy never changes event identity, shape, or authority.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.delivery.inventory_configuration_events import (
    configuration_delivery_key,
    configuration_delivery_pending,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.shared.providers.state_store import StateStore

FULL_REDELIVERY_ENV = "FDAI_INVENTORY_CONFIGURATION_FULL_REDELIVERY_SECONDS"
DEFAULT_FULL_REDELIVERY_SECONDS = 21_600
MAX_FULL_REDELIVERY_SECONDS = 604_800
LEDGER_PREFIX = "inventory-configuration:full-redelivery:"
_LEDGER_SCHEMA = "1.0.0"


@dataclass(frozen=True, slots=True)
class ConfigurationDeltaPlan:
    """Resources that may be omitted from this generation's event delivery."""

    unchanged: frozenset[str]
    full: bool
    reason: str


FULL_PLAN = ConfigurationDeltaPlan(frozenset(), True, "suppression_disabled")


class ConfigurationDeltaPolicy(Protocol):
    """Plan which promoted Resources need an event and record a completed full delivery."""

    async def plan(
        self, observation: PromotedInventoryObservation, *, scope_ref: str
    ) -> ConfigurationDeltaPlan: ...

    async def published(
        self,
        observation: PromotedInventoryObservation,
        plan: ConfigurationDeltaPlan,
        *,
        scope_ref: str,
    ) -> None: ...


class PreviousGenerationComparison(Protocol):
    """Read-only comparison against the closest earlier promoted generation of the same scope."""

    async def unchanged_since_previous(
        self, generation: str
    ) -> tuple[str | None, frozenset[str]]: ...


def full_redelivery_seconds(environ: Mapping[str, str] | None = None) -> int:
    """Return the validated interval; ``0`` disables suppression and always sends every Resource."""
    raw = (environ if environ is not None else os.environ).get(FULL_REDELIVERY_ENV, "").strip()
    if not raw:
        return DEFAULT_FULL_REDELIVERY_SECONDS
    if not raw.isdigit() or int(raw) > MAX_FULL_REDELIVERY_SECONDS:
        raise ValueError(f"{FULL_REDELIVERY_ENV} MUST be an integer in [0, 604800]")
    return int(raw)


def _ledger_key(scope_ref: str) -> str:
    return LEDGER_PREFIX + hashlib.sha256(scope_ref.encode("utf-8")).hexdigest()[:32]


class StateBackedConfigurationDeltaPolicy:
    """Persist only the time of the last full redelivery; evidence stays in snapshot rows."""

    def __init__(
        self,
        *,
        store: StateStore,
        comparison: PreviousGenerationComparison,
        full_redelivery_seconds: int = DEFAULT_FULL_REDELIVERY_SECONDS,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        if not 0 <= full_redelivery_seconds <= MAX_FULL_REDELIVERY_SECONDS:
            raise ValueError("full redelivery interval is out of range")
        self._store = store
        self._comparison = comparison
        self._interval = timedelta(seconds=full_redelivery_seconds)
        self._clock = clock

    async def plan(
        self, observation: PromotedInventoryObservation, *, scope_ref: str
    ) -> ConfigurationDeltaPlan:
        if self._interval == timedelta(0):
            return FULL_PLAN
        previous, unchanged = await self._comparison.unchanged_since_previous(
            observation.generation
        )
        if previous is None:
            return _full("no_previous_generation")
        marker = await self._store.read_state(configuration_delivery_key(previous))
        try:
            delivered = marker is not None and not configuration_delivery_pending(
                marker, generation=previous
            )
        except ValueError:
            delivered = False
        if not delivered:
            return _full("previous_delivery_incomplete")
        last_full = await self._last_full_redelivery(scope_ref)
        if last_full is None:
            return _full("no_full_redelivery_recorded")
        if self._clock() - last_full >= self._interval:
            return _full("full_redelivery_due")
        return ConfigurationDeltaPlan(unchanged, False, "unchanged_resources_omitted")

    async def published(
        self,
        observation: PromotedInventoryObservation,
        plan: ConfigurationDeltaPlan,
        *,
        scope_ref: str,
    ) -> None:
        if not plan.full or self._interval == timedelta(0):
            return
        await self._store.write_state(
            _ledger_key(scope_ref),
            {
                "schema_version": _LEDGER_SCHEMA,
                "generation": observation.generation,
                "full_published_at": self._clock().isoformat(),
                "resource_count": len(observation.resources),
                "execution_authority": False,
            },
        )

    async def _last_full_redelivery(self, scope_ref: str) -> datetime | None:
        ledger = await self._store.read_state(_ledger_key(scope_ref))
        if ledger is None or ledger.get("schema_version") != _LEDGER_SCHEMA:
            return None
        raw = ledger.get("full_published_at")
        if not isinstance(raw, str):
            return None
        try:
            published = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return published if published.tzinfo is not None else None


def _full(reason: str) -> ConfigurationDeltaPlan:
    return ConfigurationDeltaPlan(frozenset(), True, reason)


__all__ = [
    "ConfigurationDeltaPlan",
    "ConfigurationDeltaPolicy",
    "DEFAULT_FULL_REDELIVERY_SECONDS",
    "FULL_PLAN",
    "FULL_REDELIVERY_ENV",
    "PreviousGenerationComparison",
    "StateBackedConfigurationDeltaPolicy",
    "full_redelivery_seconds",
]
