"""Tests for :func:`collect_primary_candidates` + primary-pool serialization.

Covers the invariant-safe T2 primary latency pool
(docs/roadmap/architecture/llm-strategy.md section "T2 Primary Latency Pool"):
the pool MUST be single-publisher, ordered by preference, and round-trip
through ``resolved-models.json``.
"""

from __future__ import annotations

from typing import Any

import pytest

from fdai.rule_catalog.schema.llm_registry import load_llm_registry_from_mapping
from fdai.rule_catalog.schema.llm_resolver import (
    CatalogQuery,
    NarratorCandidate,
    QuotaQuery,
    ResolvedModels,
    ResolverError,
    collect_primary_candidates,
    reasoner_primary_deployment_name,
)

_REGION = "koreacentral"
_ENDPOINT = "https://example-openai.openai.azure.com/"


def _registry(primary_prefs: list[dict[str, str]]) -> Any:
    return load_llm_registry_from_mapping(
        {
            "schema_version": "1.0.0",
            "models": {
                "t1.embedding": {
                    "preferences": [
                        {"publisher": "OpenAI", "family": "text-embedding-3-small"}
                    ],
                    "capacity_tpm": 100_000,
                },
                "t2.reasoner.primary": {
                    "preferences": primary_prefs,
                    "capacity_tpm": 20_000,
                },
                "t2.reasoner.secondary": {
                    "preferences": [{"publisher": "Anthropic", "family": "claude-opus-4"}],
                    "capacity_tpm": 10_000,
                },
            },
        }
    )


class _Catalog(CatalogQuery):
    def __init__(self, families: set[str]) -> None:
        self._families = families

    def families_in_region(self, region: str) -> set[str]:
        del region
        return set(self._families)


class _Quota(QuotaQuery):
    def __init__(self, table: dict[str, int]) -> None:
        self._table = table

    def available_capacity_tpm(self, *, region: str, publisher: str, family: str) -> int:
        del region, publisher
        return self._table.get(family, 0)


def test_deployment_name_is_url_safe() -> None:
    assert reasoner_primary_deployment_name("gpt-5.4") == "t2primary-gpt-5-4"
    assert reasoner_primary_deployment_name("gpt-4o") == "t2primary-gpt-4o"


class TestCollectPrimaryCandidates:
    def test_same_publisher_pool_in_preference_order(self) -> None:
        reg = _registry(
            [
                {"publisher": "OpenAI", "family": "gpt-4o"},
                {"publisher": "OpenAI", "family": "gpt-4.1"},
            ]
        )
        catalog = _Catalog({"gpt-4o", "gpt-4.1"})
        quota = _Quota({"gpt-4o": 20_000, "gpt-4.1": 20_000})
        winner, cands = collect_primary_candidates(
            registry=reg, region=_REGION, catalog=catalog, quota=quota, endpoint=_ENDPOINT
        )
        assert [c.deployment for c in cands] == ["t2primary-gpt-4o", "t2primary-gpt-4-1"]
        assert winner is not None
        assert winner.deployment == "t2primary-gpt-4o"
        assert all(c.endpoint == _ENDPOINT for c in cands)

    def test_cross_publisher_pool_raises(self) -> None:
        # A latency pool that spans two publishers would let the race swap
        # the primary's publisher and collapse the mixed-model cross-check.
        reg = _registry(
            [
                {"publisher": "OpenAI", "family": "gpt-4o"},
                {"publisher": "Anthropic", "family": "claude-opus-4"},
            ]
        )
        catalog = _Catalog({"gpt-4o", "claude-opus-4"})
        quota = _Quota({"gpt-4o": 20_000, "claude-opus-4": 20_000})
        with pytest.raises(ResolverError, match="cross_publisher"):
            collect_primary_candidates(
                registry=reg, region=_REGION, catalog=catalog, quota=quota, endpoint=_ENDPOINT
            )

    def test_no_viable_family_returns_none(self) -> None:
        reg = _registry([{"publisher": "OpenAI", "family": "gpt-4o"}])
        winner, cands = collect_primary_candidates(
            registry=reg,
            region=_REGION,
            catalog=_Catalog(set()),
            quota=_Quota({}),
            endpoint=_ENDPOINT,
        )
        assert winner is None
        assert cands == ()

    def test_single_viable_returns_one(self) -> None:
        reg = _registry(
            [
                {"publisher": "OpenAI", "family": "gpt-4o"},
                {"publisher": "OpenAI", "family": "gpt-4.1"},
            ]
        )
        winner, cands = collect_primary_candidates(
            registry=reg,
            region=_REGION,
            catalog=_Catalog({"gpt-4o"}),
            quota=_Quota({"gpt-4o": 20_000}),
            endpoint=_ENDPOINT,
        )
        assert len(cands) == 1
        assert winner is not None
        assert winner.deployment == "t2primary-gpt-4o"

    def test_zero_quota_family_excluded(self) -> None:
        reg = _registry(
            [
                {"publisher": "OpenAI", "family": "gpt-4o"},
                {"publisher": "OpenAI", "family": "gpt-4.1"},
            ]
        )
        winner, cands = collect_primary_candidates(
            registry=reg,
            region=_REGION,
            catalog=_Catalog({"gpt-4o", "gpt-4.1"}),
            quota=_Quota({"gpt-4o": 20_000, "gpt-4.1": 0}),
            endpoint=_ENDPOINT,
        )
        assert [c.deployment for c in cands] == ["t2primary-gpt-4o"]
        assert winner is not None


class TestSerialization:
    def test_roundtrip_preserves_primary_candidates(self) -> None:
        cands = (
            NarratorCandidate(
                endpoint=_ENDPOINT, deployment="t2primary-gpt-4o", api_version="2024-06-01"
            ),
            NarratorCandidate(
                endpoint=_ENDPOINT, deployment="t2primary-gpt-4-1", api_version="2024-06-01"
            ),
        )
        rm = ResolvedModels(
            schema_version="1.0.0",
            region=_REGION,
            subscription_id="sub",
            deployer_object_id="dep",
            mixed_model_mode="azure-foundry",
            capabilities=(),
            reasoner_primary_candidates=cands,
        )
        back = ResolvedModels.from_json(rm.to_json())
        assert back.reasoner_primary_candidates == cands

    def test_field_absent_when_empty(self) -> None:
        rm = ResolvedModels(
            schema_version="1.0.0",
            region=_REGION,
            subscription_id="sub",
            deployer_object_id="dep",
            mixed_model_mode="azure-foundry",
            capabilities=(),
        )
        assert "reasoner_primary_candidates" not in rm.to_json()
