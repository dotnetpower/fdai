"""Composition-root CLI for scheduled baseline and pattern-growth jobs."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from enum import StrEnum
from pathlib import Path

import httpx

from fdai.composition import (
    AzureWireOverrides,
    default_container_from_env,
    wire_azure_container,
)
from fdai.core.assurance_twin import StateStoreEffectModelRegistry
from fdai.core.measurement.regression import RegressionDetector
from fdai.core.measurement.runners import (
    AutomatedBaselineRunner,
    DynamicLearningRunner,
    PatternGrowthIntakeRunner,
)
from fdai.core.operator_memory import InMemoryOperatorMemoryStore
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.measurement.postgres_growth import (
    PostgresResponseOutcomeSource,
    PostgresVerifiedOutcomeSource,
    PostgresVerifiedPatternBuilder,
)
from fdai.delivery.measurement.scenario_replayer import FrozenScenarioReplayer
from fdai.delivery.persistence import (
    PgVectorPatternLibrary,
    PgVectorPatternLibraryConfig,
    PostgresStateStore,
    PostgresStateStoreConfig,
    StateStoreActionPromotionRegistry,
)

_LOGGER = logging.getLogger("fdai.delivery.measurement_runner_cli")


class MeasurementMode(StrEnum):
    BASELINE = "baseline"
    GROWTH = "growth"


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} MUST be configured")
    return value


def _repo_root() -> Path:
    for candidate in (Path.cwd(), Path("/app"), *Path(__file__).resolve().parents):
        if (candidate / "rule-catalog").is_dir() and (candidate / "tests" / "scenarios").is_dir():
            return candidate
    raise FileNotFoundError("measurement artifacts are missing from the runtime image")


async def _run_baseline() -> int:
    dsn = _required_env("FDAI_STATE_STORE_DSN")
    version = _required_env("FDAI_SCENARIO_SET_VERSION")
    audit_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    registry = StateStoreActionPromotionRegistry(store=audit_store)
    report = await AutomatedBaselineRunner(
        replayer=FrozenScenarioReplayer(
            repo_root=_repo_root(),
            scenario_set_version=version,
            audit_store=audit_store,
            promotion_registry=registry,
        ),
        detector=RegressionDetector(),
        registry=registry,
        audit_store=audit_store,
        persist_mode=registry.persist,
    ).run_once()
    _LOGGER.info(
        "measurement_baseline_complete aborted_reason=%s",
        report.aborted_reason or "none",
        extra={
            "scenario_set_version": report.scenario_set_version,
            "sample_count": report.sample_count,
            "regression_count": len(report.regressions),
            "demoted_action_types": list(report.demoted_action_types),
            "aborted": report.aborted_reason is not None,
        },
    )
    return 3 if report.aborted_reason is not None else 0


async def _run_growth() -> int:
    dsn = _required_env("FDAI_STATE_STORE_DSN")
    container = default_container_from_env()
    if container.config.llm.mode != "azure":
        raise RuntimeError("growth measurement requires llm.mode='azure' for 384-dim embeddings")
    endpoint = _required_env("FDAI_LLM_ENDPOINT")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=60.0, write=15.0, pool=5.0)
    ) as client:
        identity = ManagedIdentityWorkloadIdentity(http_client=client)
        container = await wire_azure_container(
            container,
            http_client=client,
            identity=identity,
            overrides=AzureWireOverrides(
                endpoint=endpoint,
                catalog_root=_repo_root() / "rule-catalog",
                operator_memory_store=InMemoryOperatorMemoryStore(),
            ),
        )
        embedding_model = container.require_llm_bindings().embedding_model
        if embedding_model.dim != 384:
            raise RuntimeError(f"growth embedding dimension MUST be 384; got {embedding_model.dim}")
        state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
        report = await PatternGrowthIntakeRunner(
            outcome_source=PostgresVerifiedOutcomeSource(
                dsn=dsn,
                state_store=state_store,
            ),
            pattern_builder=PostgresVerifiedPatternBuilder(
                dsn=dsn,
                embedding_model=embedding_model,
            ),
            writer=PgVectorPatternLibrary(config=PgVectorPatternLibraryConfig(dsn=dsn)),
            audit_store=state_store,
        ).run_once()
        dynamic_report = await DynamicLearningRunner(
            outcome_source=PostgresResponseOutcomeSource(
                dsn=dsn,
                state_store=state_store,
            ),
            registry=StateStoreEffectModelRegistry(state_store),
            audit_store=state_store,
        ).run_once()
    _LOGGER.info(
        "measurement_growth_complete",
        extra={
            "total_outcomes": report.total_outcomes,
            "accepted_count": report.accepted_count,
            "rejected_count": report.rejected_count,
            "build_failures": report.build_failures,
            "dynamic_total_outcomes": dynamic_report.total_outcomes,
            "dynamic_accepted_count": dynamic_report.accepted_count,
            "dynamic_rejected_count": dynamic_report.rejected_count,
        },
    )
    return 0


async def _amain(argv: list[str]) -> int:
    mode_raw = argv[0].lower() if argv else os.environ.get("FDAI_MEASUREMENT_MODE", "").lower()
    try:
        mode = MeasurementMode(mode_raw)
    except ValueError:
        _LOGGER.error("invalid_measurement_mode", extra={"mode": mode_raw or "<unset>"})
        return 2
    try:
        return await (_run_baseline() if mode is MeasurementMode.BASELINE else _run_growth())
    except Exception:
        _LOGGER.exception("measurement_runner_failed", extra={"mode": mode.value})
        return 3


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("FDAI_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(_amain(list(argv) if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
