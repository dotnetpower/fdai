from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fdai.delivery.persistence.postgres_cost_governance import (
    PostgresCostGovernanceConfig,
    PostgresCostGovernanceStore,
    _current_observation_values,
)
from fdai.delivery.persistence.postgres_cost_governance_decision import (
    PostgresCostGovernanceDecisionStore,
)
from fdai.shared.providers.cost_governance import CostObservation
from fdai.shared.providers.cost_governance_decision import CostDecisionOutcome
from fdai_service_contracts import CostAnalyticsRunReceipt, CostAnalyticsRunStatus

NOW = datetime(2026, 9, 17, tzinfo=UTC)
_STORE_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src/fdai/delivery/persistence/postgres_cost_governance.py"
)


class _Cursor:
    rowcount = 1

    async def fetchone(self) -> dict[str, object] | None:
        return None


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Connection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.parameters: list[object] = []

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(self, query: str, params: object = None) -> _Cursor:
        self.statements.append(query)
        self.parameters.append(params)
        return _Cursor()


def _receipt(scope_id: str) -> CostAnalyticsRunReceipt:
    digest = hashlib.sha256(scope_id.encode()).hexdigest()
    return CostAnalyticsRunReceipt(
        run_id=f"costrun:{'a' * 64}",
        receipt_digest=f"sha256:{'a' * 64}",
        scope_digest=f"sha256:{digest}",
        venue="local",
        window_start_at=NOW - timedelta(days=1),
        window_end_at=NOW,
        started_at=NOW,
        finished_at=NOW,
        status=CostAnalyticsRunStatus.COMPLETE,
    )


@pytest.mark.asyncio
async def test_analytics_run_receipt_is_scope_bound_and_append_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = PostgresCostGovernanceStore(
        config=PostgresCostGovernanceConfig(dsn="postgresql://example.invalid/fdai")
    )

    async def connect() -> _Connection:
        return connection

    async def timeout(_connection: object) -> None:
        return None

    monkeypatch.setattr(store, "_connect", connect)
    monkeypatch.setattr(store, "_timeout", timeout)

    assert await store.append_cost_analytics_run_receipt(
        _receipt("subscriptions/example"),
        scope_id="subscriptions/example",
    )
    assert "INSERT INTO cost_governance_analytics_run_receipt" in connection.statements[-1]
    assert "ON CONFLICT (run_id) DO NOTHING" in connection.statements[-1]

    with pytest.raises(ValueError, match="scope digest"):
        await store.append_cost_analytics_run_receipt(
            _receipt("subscriptions/other"),
            scope_id="subscriptions/example",
        )


@pytest.mark.asyncio
async def test_case_projection_accepts_only_explicit_observation_mode_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    store = PostgresCostGovernanceDecisionStore(dsn="postgresql://example.invalid/fdai")

    async def connect() -> _Connection:
        return connection

    async def timeout(_connection: object) -> None:
        return None

    monkeypatch.setattr(store, "_connect", connect)
    monkeypatch.setattr(store, "_timeout", timeout)
    frame = SimpleNamespace(
        episode_id="episode-1",
        evidence_cutoff=NOW,
        digest=f"sha256:{'b' * 64}",
        scope=SimpleNamespace(target_refs=("resource-one",)),
        options=(SimpleNamespace(to_mapping=lambda: {"option_id": "option.no-action"}),),
        selected_option_id="option.no-action",
    )
    decision = SimpleNamespace(
        episode_id="episode-1",
        decision_frame_digest=frame.digest,
        observation_mode=True,
        outcome=CostDecisionOutcome.HOLD,
        terminal=False,
        reason="hard_dependency_observation_mode",
    )

    assert await store.append_observation_mode_case(
        scope_id="subscriptions/example",
        frame=frame,
        decision=decision,
        episode_revision=1,
        source_authority="forseti-observation-mode",
    )
    assert "INSERT INTO cost_governance_case_projection" in connection.statements[-1]
    assert "episode.observation_mode" in connection.statements[-1]
    assert "episode.outcome = 'hold'" in connection.statements[-1]

    decision.observation_mode = False
    with pytest.raises(ValueError, match="observation-mode holds"):
        await store.append_observation_mode_case(
            scope_id="subscriptions/example",
            frame=frame,
            decision=decision,
            episode_revision=1,
            source_authority="forseti-observation-mode",
        )


def test_observation_reads_and_writes_use_only_the_current_daily_fact() -> None:
    source = _STORE_SOURCE.read_text(encoding="utf-8")

    assert "INSERT INTO cost_observation_current" in source
    assert "ON CONFLICT (" in source
    assert "EXCLUDED.recorded_at, EXCLUDED.observation_id" in source
    assert source.count("JOIN cost_observation_current AS current") >= 2
    assert "item.event_start_at.astimezone(UTC).date()" in source


def test_corrected_daily_observations_share_one_stable_current_key() -> None:
    def observation(identifier: str, recorded_at: datetime) -> CostObservation:
        return CostObservation(
            observation_id=f"costobs:{identifier * 64}",
            package_id="cost-governance",
            scope_id="subscriptions/example",
            service_id="compute",
            amount=1,
            currency="USD",
            event_start_at=NOW - timedelta(days=1),
            event_end_at=NOW,
            observed_at=NOW,
            recorded_at=recorded_at,
            source_authority="azure-cost-management",
            source_uri="cost-service:compute",
            completeness=1,
            ontology_release_id="ontology:test",
            ontology_release_digest=f"sha256:{'c' * 64}",
            evidence_digest=f"sha256:{identifier * 64}",
            retention_until=NOW + timedelta(days=400),
        )

    original = _current_observation_values(observation("a", NOW))
    corrected = _current_observation_values(observation("b", NOW + timedelta(minutes=1)))

    assert original[:5] == corrected[:5]
    assert original[5:] != corrected[5:]
