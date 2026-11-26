from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fdai.agents._framework.bragi_publication import handoff_event_payload
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.mimir_maintenance import (
    MimirCatalogPromotionOutcome,
    MimirRegressionResult,
)
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime_payload_validation import default_payload_validator
from fdai.agents.mimir import Mimir
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _PromotionReader:
    def __init__(self, outcome: MimirCatalogPromotionOutcome) -> None:
        self.outcome = outcome

    async def read_promotion_outcomes(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> Sequence[MimirCatalogPromotionOutcome]:
        del limit, now
        return (self.outcome,)


class _RegressionRunner:
    def __init__(self, *, started_at: datetime) -> None:
        self.started_at = started_at

    async def run_regression(
        self,
        outcome: MimirCatalogPromotionOutcome,
        *,
        now: datetime,
    ) -> MimirRegressionResult:
        del now
        return MimirRegressionResult(
            passed=True,
            started_at=self.started_at,
            completed_at=self.started_at + timedelta(minutes=5),
            evidence_ref=f"regression:{outcome.rule_id}",
        )


async def test_mimir_promotion_evidence_without_digests_passes_default_validator() -> None:
    now = datetime(2032, 1, 2, 1, 0, tzinfo=UTC)
    saga = Saga(clock=lambda: now)
    norns = Norns(promotion_threshold=1)
    mimir = Mimir(governance_state_store=InMemoryStateStore(), clock=lambda: now)
    bus = InMemoryBus(registry=load_pantheon(), payload_validator=default_payload_validator)
    saga.bind_bus(bus)
    norns.bind_bus(bus)
    mimir.bind_bus(bus)
    bus.subscribe("object.issue", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)
    bus.subscribe("object.rule", "Saga", saga.on_typed_message)
    saga.bind_issue_close_promotion_evidence_producer()
    handoff = handoff_event_payload(
        session_id="session-validator-close",
        question="unknown validator close",
        turn_index=0,
        reason="no_route",
        emitted_at=now - timedelta(hours=48),
    )
    fingerprint = str(handoff["problem_fingerprint"])
    await saga.on_typed_message("object.handoff-escalation", handoff)
    mimir.bind_catalog_promotion_outcome_reader(
        _PromotionReader(
            MimirCatalogPromotionOutcome(
                problem_fingerprint=fingerprint,
                promotion_pr="https://github.com/dotnetpower/fdai/pull/1999",
                correlation_id="promotion-validator",
                outcome="promoted",
                rule_id="rule.validator",
                promoted_at=now - timedelta(hours=26),
            )
        )
    )
    mimir.bind_regression_runner(_RegressionRunner(started_at=now - timedelta(hours=25)))

    await mimir.maintenance_tick()
    await saga.maintenance_tick()

    rule_messages = bus.messages_on("object.rule")
    assert len(rule_messages) == 1
    assert rule_messages[0].payload["candidate_digest"] is None
    assert rule_messages[0].payload["package_digest"] is None
    assert "mode" not in rule_messages[0].payload
    assert saga.github.issues[fingerprint].open is False
    assert saga.behavior_snapshot()["maintenance_tick:issue_close_scan_closed"] == 1
