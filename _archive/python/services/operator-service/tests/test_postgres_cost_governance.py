from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fdai_operator_service.postgres_cost_governance import (
    PostgresCostGovernanceConfig,
    PostgresCostGovernanceReader,
    _psycopg_dsn,
)
from fdai_service_contracts import DISCLOSURE_PRESETS


class _RecordingReader(PostgresCostGovernanceReader):
    def __init__(self) -> None:
        super().__init__(PostgresCostGovernanceConfig(dsn="postgresql://example.invalid/fdai"))
        self.query = ""
        self.params: Mapping[str, object] = {}

    async def _fetch(
        self,
        query: str,
        params: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        self.query = query
        self.params = params
        now = params["now"]
        assert isinstance(now, datetime)
        disclosure = DISCLOSURE_PRESETS["masked"].model_dump(mode="json")
        return [
            {
                "grant_id": "grant:matching-scope",
                "principal_id": params["principal_id"],
                "revision": 4,
                "purpose": params["purpose"],
                "scopes": [params["scope"]],
                "disclosure": disclosure,
                "effective_at": now - timedelta(minutes=1),
                "expires_at": now + timedelta(hours=1),
                "source_authority": "access-review",
                "ceiling_disclosure": disclosure,
                "ceiling_revision": 2,
                "ceiling_effective_at": now - timedelta(minutes=2),
                "ceiling_source_authority": "deployment-policy",
            }
        ]


class _AnalyticsReader(PostgresCostGovernanceReader):
    def __init__(self) -> None:
        super().__init__(PostgresCostGovernanceConfig(dsn="postgresql://example.invalid/fdai"))
        self.query = ""
        self.params: Mapping[str, object] = {}

    async def _fetch(
        self,
        query: str,
        params: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        self.query = query
        self.params = params
        return [
            {
                "scope_id": (
                    "subscription:one"
                    if self.params.get("scope") == "*"
                    else self.params.get("scope", "subscription:one")
                ),
                "snapshot_id": f"analytics:{'a' * 64}",
                "payload": {
                    "source_authority": "azure-cost-analytics",
                    "observed_at": "2026-08-28T00:00:00Z",
                    "complete": True,
                    "trend": [],
                    "budgets": [],
                    "recommendations": [],
                    "limitations": [],
                },
            }
        ]


class _CurrentRecordReader(PostgresCostGovernanceReader):
    def __init__(self) -> None:
        super().__init__(PostgresCostGovernanceConfig(dsn="postgresql://example.invalid/fdai"))
        self.query = ""

    async def _fetch(
        self,
        query: str,
        params: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        self.query = query
        now = datetime(2026, 9, 17, tzinfo=UTC)
        return [
            {
                "observation_id": "costobs:one",
                "scope_id": params["scope"],
                "service_id": "compute",
                "amount": Decimal("10"),
                "currency": "USD",
                "event_start_at": now - timedelta(days=1),
                "event_end_at": now,
                "observed_at": now,
                "recorded_at": now,
                "completeness": Decimal("1"),
                "source_authority": "azure-cost-management",
                "evidence_digest": f"sha256:{'a' * 64}",
            }
        ]


class _LiveProjectionReader(PostgresCostGovernanceReader):
    def __init__(self) -> None:
        super().__init__(PostgresCostGovernanceConfig(dsn="postgresql://example.invalid/fdai"))
        self.queries: list[str] = []

    async def _fetch(
        self,
        query: str,
        params: Mapping[str, object],
    ) -> list[dict[str, Any]]:
        self.queries.append(query)
        now = datetime(2026, 9, 17, tzinfo=UTC)
        if "GROUP BY observation.source_authority" in query:
            return [
                {
                    "source_authority": "azure-cost-management",
                    "window_start_at": now - timedelta(days=1),
                    "window_end_at": now,
                    "latest_source_at": now,
                    "complete_count": 2,
                    "partial_count": 1,
                }
            ]
        if "MIN(event_start_at)" in query:
            return [
                {
                    "window_start_at": now - timedelta(days=1),
                    "window_end_at": now,
                    "latest_source_at": now,
                    "complete_count": 2,
                    "partial_count": 1,
                    "decision_case_count": 1,
                    "incomplete_decision_case_count": 0,
                    "settlement_count": 1,
                    "incomplete_settlement_count": 0,
                }
            ]
        if "cost_governance_analytics_run_receipt" in query:
            return [
                {
                    "run_id": f"costrun:{'a' * 64}",
                    "receipt_digest": f"sha256:{'a' * 64}",
                    "scope_digest": f"sha256:{'b' * 64}",
                    "venue": "deployed",
                    "window_start_at": now - timedelta(days=1),
                    "window_end_at": now,
                    "started_at": now - timedelta(minutes=2),
                    "finished_at": now - timedelta(minutes=1),
                    "status": "partial",
                    "sources": [],
                    "observation_count": 3,
                    "trend_point_count": 1,
                    "budget_count": 0,
                    "recommendation_count": 0,
                    "utilization_count": 0,
                    "limitations": ["budgets_unavailable"],
                    "failure_reason": None,
                    "snapshot_id": f"analytics:{'c' * 64}",
                }
            ]
        if "jsonb_agg" in query:
            return [
                {
                    "episode_id": "episode-private",
                    "episode_revision": 1,
                    "decision_frame_digest": f"sha256:{'d' * 64}",
                    "terminal": True,
                    "realized_savings": Decimal("12"),
                    "currency": "USD",
                    "action_ref": "action-run:one",
                    "action_revision": 3,
                    "rollback_request_id": None,
                    "recovery_observed": False,
                    "settled_at": now,
                    "effects": [
                        {
                            "effect_id": "effect-cost",
                            "kind": "cost",
                            "status": "verified",
                            "reason": "expected_effect_observed",
                            "terminal": True,
                            "observation_digest": f"sha256:{'e' * 64}",
                            "completeness_digest": f"sha256:{'f' * 64}",
                        }
                    ],
                }
            ]
        if "ARRAY(" in query:
            return [
                {
                    "episode_id": "episode-private",
                    "episode_revision": 1,
                    "evidence_cutoff": now - timedelta(hours=1),
                    "decision_frame_digest": f"sha256:{'d' * 64}",
                    "target_refs": ["/subscriptions/private/resource"],
                    "options": [{"option_id": "option.no-action"}],
                    "selected_option_id": "option.no-action",
                    "verdict": "hold",
                    "reason": "hard_dependency_observation_mode",
                    "recorded_at": now,
                    "source_authority": "forseti-observation-mode",
                    "evidence_refs": ["evidence:one"],
                    "evidence_sources": ["heimdall"],
                    "recovery_steps": ["reacquire-context:success"],
                }
            ]
        raise AssertionError(f"unexpected query: {query}")


def test_sqlalchemy_psycopg_dsn_is_normalized_for_direct_driver_use() -> None:
    assert _psycopg_dsn("postgresql+psycopg://user@example.invalid/fdai") == (
        "postgresql://user@example.invalid/fdai"
    )
    assert _psycopg_dsn("postgresql://user@example.invalid/fdai") == (
        "postgresql://user@example.invalid/fdai"
    )


@pytest.mark.asyncio
async def test_access_query_selects_latest_grant_within_requested_scope() -> None:
    reader = _RecordingReader()
    now = datetime(2026, 8, 28, tzinfo=UTC)

    decision = await reader.read_access(
        principal_id="principal:one",
        purpose="cost-review",
        scope="subscription:one",
        now=now,
    )

    assert "FROM cost_access_grant AS access_grant" in reader.query
    assert "access_grant.scopes ? %(scope)s" in reader.query
    assert "access_grant.scopes ? '*'" in reader.query
    assert " AS grant" not in reader.query
    assert reader.params["scope"] == "subscription:one"
    assert decision.grant is not None
    assert decision.grant.scopes == ("subscription:one",)


@pytest.mark.asyncio
async def test_analytics_query_reads_latest_scope_snapshot() -> None:
    reader = _AnalyticsReader()

    projection = await reader.read_analytics(scope="subscription:one")

    assert "FROM cost_governance_analytics_snapshot" in reader.query
    assert "ORDER BY observed_at DESC" in reader.query
    assert reader.params["scope"] == "subscription:one"
    assert projection is not None
    assert projection.scope_id == "subscription:one"
    assert projection.projection.source_authority == "azure-cost-analytics"


@pytest.mark.asyncio
async def test_global_analytics_requires_one_unambiguous_scope() -> None:
    reader = _AnalyticsReader()

    await reader.read_analytics(scope="*")

    assert "WITH candidate_scope AS" in reader.query
    assert "HAVING COUNT(*) = 1" in reader.query
    assert "JOIN cost_observation_current AS current" in reader.query


@pytest.mark.asyncio
async def test_projection_reads_only_current_supersession_pointer() -> None:
    reader = _CurrentRecordReader()

    records = await reader.read_records(
        surface="overview",
        scope="subscriptions/example",
        limit=10,
    )

    assert len(records) == 1
    assert "FROM cost_observation_current AS current" in reader.query
    assert "ON observation.observation_id = current.observation_id" in reader.query


@pytest.mark.asyncio
async def test_evidence_reader_preserves_source_and_latest_run_health() -> None:
    reader = _LiveProjectionReader()

    evidence = await reader.read_projection_evidence(
        scope="subscriptions/example",
        analytics_snapshot_id=f"analytics:{'c' * 64}",
    )

    assert evidence.complete_count == 2
    assert evidence.partial_count == 1
    assert evidence.sources[0].state.value == "partial"
    assert evidence.latest_analytics_run is not None
    assert evidence.latest_analytics_run.status.value == "partial"
    assert evidence.decision_case_count == 1
    assert evidence.settlement_count == 1


@pytest.mark.asyncio
async def test_lineage_reads_pseudonymize_targets_and_require_persisted_tables() -> None:
    reader = _LiveProjectionReader()
    key = bytes(range(32))

    cases = await reader.read_decision_cases(
        scope="subscriptions/example",
        limit=20,
        pseudonym_key=key,
    )
    outcomes = await reader.read_settlement_outcomes(
        scope="subscriptions/example",
        limit=20,
        pseudonym_key=key,
    )

    assert cases[0].verdict == "hold"
    assert cases[0].target_refs[0].startswith("resource:")
    assert "private" not in repr(cases[0])
    assert outcomes[0].verified_savings == Decimal("12")
    assert outcomes[0].currency == "USD"
    assert outcomes[0].action_ref == "action-run:one"
    assert outcomes[0].action_revision == 3
    assert all("cost_observation" not in query for query in reader.queries[-2:])
