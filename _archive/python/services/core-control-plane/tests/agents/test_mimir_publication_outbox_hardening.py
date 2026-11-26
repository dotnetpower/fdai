from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.mimir_maintenance import (
    MimirCatalogPromotionOutcome,
    MimirRegressionResult,
)
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.mimir import (
    Mimir,
    _issue_close_evidence_idempotency_key,
    _rule_publication_key,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _reviewed_promotion_ref() -> str:
    return f"catalog-pr:https://git.example.com/fdai/control-plane/pull/1@sha256:{'a' * 64}"


class _PromotionReader:
    def __init__(self) -> None:
        self.outcomes: list[MimirCatalogPromotionOutcome] = []

    async def read_promotion_outcomes(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> Sequence[MimirCatalogPromotionOutcome]:
        return tuple(self.outcomes[:limit])


class _RegressionRunner:
    def __init__(self, *, started_at: datetime) -> None:
        self.started_at = started_at

    async def run_regression(
        self,
        outcome: MimirCatalogPromotionOutcome,
        *,
        now: datetime,
    ) -> MimirRegressionResult:
        return MimirRegressionResult(
            passed=True,
            started_at=self.started_at,
            completed_at=self.started_at + timedelta(minutes=5),
            evidence_ref=f"regression:{outcome.rule_id}",
        )


async def test_direct_rule_promotion_checkpoints_when_bus_unbound_then_recovers() -> None:
    store = InMemoryStateStore()
    reviewed_change_ref = _reviewed_promotion_ref()
    first = Mimir(governance_state_store=store)

    first.promote("static.rule", source="manual", reviewed_change_ref=reviewed_change_ref)

    bus = InMemoryBus(registry=load_pantheon())
    restarted = Mimir(governance_state_store=store)
    restarted.bind_bus(bus)

    assert await restarted.recover_governance_state() == 2
    messages = bus.messages_on("object.rule")
    assert len(messages) == 1
    payload = messages[0].payload
    assert payload["rule_id"] == "static.rule"
    assert payload["reviewed_change_ref"] == reviewed_change_ref
    assert (await store.read_state(_rule_publication_key(payload["idempotency_key"])))[
        "status"
    ] == "published"


async def test_direct_policy_promotion_checkpoints_when_bus_unbound_then_recovers() -> None:
    store = InMemoryStateStore()
    first = Mimir(governance_state_store=store)

    first.promote(
        "policy.security.baseline",
        source="policy",
        reviewed_change_ref=_reviewed_promotion_ref(),
    )

    bus = InMemoryBus(registry=load_pantheon())
    restarted = Mimir(governance_state_store=store)
    restarted.bind_bus(bus)

    assert await restarted.recover_governance_state() == 2
    messages = bus.messages_on("object.policy")
    assert len(messages) == 1
    assert messages[0].payload["policy_id"] == "policy.security.baseline"


async def test_mimir_checkpoints_issue_close_evidence_without_bus_and_recovers() -> None:
    now = datetime(2032, 1, 2, 1, 0, tzinfo=UTC)
    store = InMemoryStateStore()
    reader = _PromotionReader()
    outcome = MimirCatalogPromotionOutcome(
        problem_fingerprint="fp-no-bus-publication",
        promotion_pr="https://github.com/dotnetpower/fdai/pull/1003",
        correlation_id="promotion-no-bus-publication",
        outcome="promoted",
        rule_id="rule.no.bus.publication",
        promoted_at=now - timedelta(hours=26),
    )
    reader.outcomes.append(outcome)
    first = Mimir(governance_state_store=store, clock=lambda: now)
    first.bind_catalog_promotion_outcome_reader(reader)
    first.bind_regression_runner(_RegressionRunner(started_at=now - timedelta(hours=25)))

    await first.maintenance_tick()

    idempotency_key = _issue_close_evidence_idempotency_key(outcome)
    assert (await store.read_state(_rule_publication_key(idempotency_key)))["status"] == "pending"
    bus = InMemoryBus(registry=load_pantheon())
    restarted = Mimir(governance_state_store=store, clock=lambda: now)
    restarted.bind_bus(bus)

    assert await restarted.recover_governance_state() == 1
    messages = bus.messages_on("object.rule")
    assert len(messages) == 1
    assert messages[0].payload["idempotency_key"] == idempotency_key
