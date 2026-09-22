"""Compose the Rule activation receipt consumer without crossing Core boundaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fdai_core_service.rule_activation_consumer import RuleActivationConsumer

from fdai.core.rule_activation import RuleActivationCoordinator, StateStoreRuleActivationLedger
from fdai.core.rule_activation.coordinator import RuleGenerationRuntime
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_rule_activation_receipts import (
    PostgresRuleActivationReceiptReader,
)
from fdai.shared.contracts.models import Rule
from fdai.shared.providers.state_store import StateStore


def build_rule_activation_consumer(
    *,
    store: StateStore,
    ledger: StateStoreRuleActivationLedger,
    runtime: RuleGenerationRuntime,
    available_rules: Sequence[Rule],
    environment: Mapping[str, str],
) -> RuleActivationConsumer | None:
    dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        return None
    return RuleActivationConsumer(
        receipts=PostgresRuleActivationReceiptReader(PostgresStateStoreConfig(dsn=dsn)),
        coordinator=RuleActivationCoordinator(
            store=store,
            ledger=ledger,
            runtime=runtime,
            available_rules=available_rules,
        ),
    )


__all__ = ["build_rule_activation_consumer"]
