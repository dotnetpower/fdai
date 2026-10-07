"""Compose Forseti's bounded baseline worker from runtime inventory, activation, and T0 state."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any, Protocol

from fdai_service_contracts.rule_activation import RuleActivationGeneration

from fdai.agents import (
    BaselineWorkerLimits,
    ForsetiBaselineScheduler,
    ForsetiBaselineWorker,
)
from fdai.core.rule_activation import StateStoreRuleActivationLedger
from fdai.core.tiers.t0_deterministic import RuleGenerationSnapshot
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_promoted_inventory_reader import (
    PostgresPromotedInventoryGenerationReader,
)
from fdai.runtime.bootstrap_core_model import assurance_twin_inventory_dsn
from fdai.shared.providers.state_store import StateStore

BASELINE_EVALUATION_ENABLED_ENV = "FDAI_BASELINE_EVALUATION_ENABLED"
BASELINE_EVALUATION_INTERVAL_ENV = "FDAI_BASELINE_EVALUATION_INTERVAL_SECONDS"
BASELINE_EVALUATION_MAX_RESOURCES_ENV = "FDAI_BASELINE_EVALUATION_MAX_RESOURCES"

_LOGGER = logging.getLogger("fdai.runtime.baseline_evaluation")


class _ActivationLedger(Protocol):
    async def current_generation(self) -> RuleActivationGeneration | None: ...


class _RuleGenerationRuntime(Protocol):
    async def rule_generation_snapshot(self) -> RuleGenerationSnapshot: ...


def bind_forseti_baseline_worker(
    pantheon: Any | None,
    state_store: StateStore | None,
    runtime: _RuleGenerationRuntime,
    environment: Mapping[str, str],
    *,
    activation_ledger: _ActivationLedger | None = None,
) -> ForsetiBaselineScheduler | None:
    """Bind the shadow-only baseline worker to Forseti, or return ``None`` without inputs."""

    agents: Mapping[str, Any] | None = getattr(pantheon, "agents", None)
    inventory_dsn = assurance_twin_inventory_dsn(environment)
    if environment.get(BASELINE_EVALUATION_ENABLED_ENV, "true").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        _LOGGER.info("forseti_baseline_evaluation_disabled")
        return None
    forseti = agents.get("Forseti") if agents is not None else None
    if forseti is None or state_store is None or not (inventory_dsn or "").strip():
        _LOGGER.info(
            "forseti_baseline_evaluation_unavailable",
            extra={"reason": "forseti_state_store_or_inventory_dsn_absent"},
        )
        return None
    worker = ForsetiBaselineWorker(
        state_store=state_store,
        reader=PostgresPromotedInventoryGenerationReader(
            config=PostgresInventorySnapshotStoreConfig(dsn=str(inventory_dsn))
        ),
        activation_source=(
            activation_ledger or StateStoreRuleActivationLedger(store=state_store)
        ).current_generation,
        rule_snapshot_source=runtime.rule_generation_snapshot,
        owner=f"forseti:{os.getpid()}",
        limits=BaselineWorkerLimits(
            max_resources=_positive_int(environment, BASELINE_EVALUATION_MAX_RESOURCES_ENV, 20_000)
        ),
    )
    scheduler = ForsetiBaselineScheduler(
        worker,
        interval_seconds=float(_positive_int(environment, BASELINE_EVALUATION_INTERVAL_ENV, 300)),
    )
    forseti.bind_baseline_scheduler(scheduler)
    _LOGGER.info("forseti_baseline_evaluation_ready")
    return scheduler


def _positive_int(environment: Mapping[str, str], key: str, default: int) -> int:
    raw = environment.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{key} MUST be a positive integer") from exc
    if value < 1:
        raise RuntimeError(f"{key} MUST be a positive integer")
    return value


__all__ = [
    "BASELINE_EVALUATION_ENABLED_ENV",
    "BASELINE_EVALUATION_INTERVAL_ENV",
    "BASELINE_EVALUATION_MAX_RESOURCES_ENV",
    "bind_forseti_baseline_worker",
]
