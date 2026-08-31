from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
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
                "payload": {
                    "source_authority": "azure-cost-analytics",
                    "observed_at": "2026-08-28T00:00:00Z",
                    "complete": True,
                    "trend": [],
                    "budgets": [],
                    "recommendations": [],
                    "limitations": [],
                }
            }
        ]


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
    assert projection.source_authority == "azure-cost-analytics"


@pytest.mark.asyncio
async def test_global_analytics_requires_one_unambiguous_scope() -> None:
    reader = _AnalyticsReader()

    await reader.read_analytics(scope="*")

    assert "HAVING COUNT(DISTINCT candidate.scope_id) = 1" in reader.query
    assert "JOIN (" in reader.query
    assert "SELECT DISTINCT scope_id" in reader.query
    assert "FROM cost_observation" in reader.query
