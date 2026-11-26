"""Scenario-lab governed Chaos provider entry point."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.core.chaos.promotion_evidence import load_promotion_ledger
from fdai.delivery.chaos.governed_bindings import GovernedChaosBindings
from fdai.delivery.persistence import (
    PostgresAdvisoryResourceLock,
    PostgresAdvisoryResourceLockConfig,
    PostgresStateStore,
    PostgresStateStoreConfig,
    StateStoreActionPromotionRegistry,
)

from fdai_governed_chaos_provider.config import GovernedChaosProviderConfig
from fdai_governed_chaos_provider.provider import (
    StateStoreChaosApprovalVerifier,
    StateStoreChaosRunPlanner,
    StateStoreRecoveryEvidenceCollector,
    StateStoreThorRecoveryDispatcher,
)


def build_governed_chaos_bindings(*, environment: Mapping[str, str]) -> GovernedChaosBindings:
    """Build deployment-owned governed Chaos collaborators from bounded configuration."""

    config = GovernedChaosProviderConfig.from_environment(environment)
    state_store = PostgresStateStore(
        config=PostgresStateStoreConfig(
            dsn=config.state_store_dsn,
            statement_timeout_ms=config.statement_timeout_ms,
            connect_timeout_s=config.connect_timeout_seconds,
        )
    )
    action_registry = StateStoreActionPromotionRegistry(store=state_store)
    return GovernedChaosBindings(
        state_store=state_store,
        action_registry=action_registry,
        scenario_ledger=load_promotion_ledger(config.promotion_ledger_path),
        approval_verifier=StateStoreChaosApprovalVerifier(
            store=state_store,
            approval_prefix=config.approval_prefix,
        ),
        planner=StateStoreChaosRunPlanner(
            store=state_store,
            action_registry=action_registry,
            plan_prefix=config.plan_prefix,
            target_binding_id=config.target_binding_id,
            stop_event_prefix=config.stop_event_prefix,
        ),
        recovery_dispatcher=StateStoreThorRecoveryDispatcher(
            store=state_store,
            dispatch_prefix=config.dispatch_prefix,
        ),
        evidence_collector=StateStoreRecoveryEvidenceCollector(
            store=state_store,
            evidence_prefix=config.evidence_prefix,
        ),
        target_lock=PostgresAdvisoryResourceLock(
            config=PostgresAdvisoryResourceLockConfig(
                dsn=config.state_store_dsn,
                lock_timeout_ms=config.lock_timeout_ms,
                connect_timeout_s=config.connect_timeout_seconds,
            )
        ),
    )


__all__ = ["build_governed_chaos_bindings"]
