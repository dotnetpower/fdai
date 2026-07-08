"""Tests for :func:`collect_narrator` + resolved-models narrator serialization."""

from __future__ import annotations

from typing import Any

from fdai.rule_catalog.schema.llm_registry import load_llm_registry_from_mapping
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    CatalogQuery,
    NarratorCandidate,
    QuotaQuery,
    ResolvedModels,
    collect_narrator,
    collect_narrator_deployments,
    narrator_deployment_name,
)

_REGION = "koreacentral"
_ENDPOINT = "https://example-openai.openai.azure.com/"


def _registry() -> Any:
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
                "t1.judge": {
                    "preferences": [
                        {"publisher": "OpenAI", "family": "gpt-5.4-mini"},
                        {"publisher": "OpenAI", "family": "gpt-5-mini"},
                        {"publisher": "OpenAI", "family": "gpt-4.1-mini"},
                        {"publisher": "OpenAI", "family": "gpt-4o-mini"},
                    ],
                    "capacity_tpm": 200_000,
                },
                "t2.reasoner.primary": {
                    "preferences": [{"publisher": "OpenAI", "family": "gpt-4o"}],
                    "capacity_tpm": 20_000,
                },
                "t2.reasoner.secondary": {
                    "preferences": [
                        {"publisher": "Anthropic", "family": "claude-opus-4"}
                    ],
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

    def available_capacity_tpm(
        self, *, region: str, publisher: str, family: str
    ) -> int:
        del region, publisher
        return self._table.get(family, 0)


class TestCollectNarrator:
    def test_returns_all_viable_prefs_in_order(self) -> None:
        # Two of the four mini families are in-region with quota.
        catalog = _Catalog(
            {"gpt-5.4-mini", "gpt-4.1-mini", "gpt-4o-mini", "text-embedding-3-small"}
        )
        quota = _Quota(
            {
                "gpt-5.4-mini": 50_000,
                "gpt-4.1-mini": 40_000,
                # gpt-4o-mini: in catalog but zero quota - dropped
                "gpt-4o-mini": 0,
                "text-embedding-3-small": 100_000,
            }
        )
        winner, candidates = collect_narrator(
            registry=_registry(),
            region=_REGION,
            catalog=catalog,
            quota=quota,
            endpoint=_ENDPOINT,
        )
        assert winner == NarratorCandidate(
            endpoint=_ENDPOINT,
            deployment="narrator-gpt-5-4-mini",
            api_version="2024-08-01-preview",
        )
        assert [c.deployment for c in candidates] == [
            "narrator-gpt-5-4-mini",
            "narrator-gpt-4-1-mini",
        ]
        # All carry the passed endpoint + api_version.
        for c in candidates:
            assert c.endpoint == _ENDPOINT
            assert c.api_version == "2024-08-01-preview"

    def test_no_viable_family_returns_none(self) -> None:
        catalog = _Catalog({"text-embedding-3-small"})  # no mini family
        quota = _Quota({"text-embedding-3-small": 100_000})
        winner, candidates = collect_narrator(
            registry=_registry(),
            region=_REGION,
            catalog=catalog,
            quota=quota,
            endpoint=_ENDPOINT,
        )
        assert winner is None
        assert candidates == ()

    def test_unknown_capability_name_returns_none(self) -> None:
        winner, candidates = collect_narrator(
            registry=_registry(),
            region=_REGION,
            catalog=_Catalog({"gpt-5.4-mini"}),
            quota=_Quota({"gpt-5.4-mini": 50_000}),
            endpoint=_ENDPOINT,
            capability_name="does.not.exist",
        )
        assert winner is None
        assert candidates == ()

    def test_custom_api_version_propagates(self) -> None:
        winner, candidates = collect_narrator(
            registry=_registry(),
            region=_REGION,
            catalog=_Catalog({"gpt-5.4-mini"}),
            quota=_Quota({"gpt-5.4-mini": 50_000}),
            endpoint=_ENDPOINT,
            api_version="2025-01-01-preview",
        )
        assert winner is not None
        assert winner.api_version == "2025-01-01-preview"
        assert all(c.api_version == "2025-01-01-preview" for c in candidates)


class TestResolvedModelsNarratorSerialization:
    def _empty_resolved(self) -> ResolvedModels:
        return ResolvedModels(
            schema_version="1.0.0",
            region=_REGION,
            subscription_id="00000000-0000-0000-0000-000000000000",
            deployer_object_id="00000000-0000-0000-0000-000000000001",
            mixed_model_mode="azure-foundry",
            capabilities=(),
        )

    def test_narrator_fields_omitted_when_absent(self) -> None:
        """Legacy golden files stay byte-identical when the caller opts out."""
        text = self._empty_resolved().to_json()
        assert "narrator" not in text
        assert "narrator_candidates" not in text

    def test_narrator_fields_round_trip(self) -> None:
        winner = NarratorCandidate(
            endpoint=_ENDPOINT,
            deployment="narrator-gpt-5-4-mini",
            api_version="2024-08-01-preview",
        )
        second = NarratorCandidate(
            endpoint=_ENDPOINT,
            deployment="narrator-gpt-5-mini",
            api_version="2024-08-01-preview",
        )
        original = ResolvedModels(
            schema_version="1.0.0",
            region=_REGION,
            subscription_id="00000000-0000-0000-0000-000000000000",
            deployer_object_id="00000000-0000-0000-0000-000000000001",
            mixed_model_mode="azure-foundry",
            capabilities=(),
            narrator=winner,
            narrator_candidates=(winner, second),
        )
        text = original.to_json()
        assert "narrator" in text
        assert "narrator_candidates" in text
        restored = ResolvedModels.from_json(text)
        assert restored.narrator == winner
        assert restored.narrator_candidates == (winner, second)
        assert restored.to_json() == text


class TestNarratorDeploymentName:
    def test_dots_become_dashes_and_prefixes_narrator(self) -> None:
        assert narrator_deployment_name("gpt-5.4-mini") == "narrator-gpt-5-4-mini"
        assert narrator_deployment_name("gpt-4o-mini") == "narrator-gpt-4o-mini"
        # A family with no dots is unchanged besides the prefix.
        assert narrator_deployment_name("plain") == "narrator-plain"


class TestCollectNarratorDeployments:
    def test_emits_one_capability_per_viable_pref(self) -> None:
        catalog = _Catalog({"gpt-5.4-mini", "gpt-5-mini", "gpt-4o-mini"})
        quota = _Quota(
            {
                "gpt-5.4-mini": 300_000,  # exceeds request -> clamped down
                "gpt-5-mini": 150_000,  # below request -> use available
                "gpt-4o-mini": 0,  # dropped
            }
        )
        deployments = collect_narrator_deployments(
            registry=_registry(),
            region=_REGION,
            catalog=catalog,
            quota=quota,
        )
        # One per viable pref, in registry preference order.
        names = [d.name for d in deployments]
        assert names == ["narrator-gpt-5-4-mini", "narrator-gpt-5-mini"]
        by_name = {d.name: d for d in deployments}
        # capacity_tpm clamped to min(spec, available).
        assert by_name["narrator-gpt-5-4-mini"].capacity_tpm == 200_000  # spec
        assert by_name["narrator-gpt-5-mini"].capacity_tpm == 150_000  # available
        # Every deployment is RESOLVED - viability was pre-checked.
        for d in deployments:
            assert d.status == CapabilityStatus.RESOLVED
            assert d.family in {"gpt-5.4-mini", "gpt-5-mini"}
            assert d.publisher == "OpenAI"
            assert d.reasons == ("narrator_deployment_for=t1.judge",)

    def test_no_viable_family_returns_empty(self) -> None:
        deployments = collect_narrator_deployments(
            registry=_registry(),
            region=_REGION,
            catalog=_Catalog({"text-embedding-3-small"}),
            quota=_Quota({"text-embedding-3-small": 100_000}),
        )
        assert deployments == ()

    def test_unknown_capability_returns_empty(self) -> None:
        deployments = collect_narrator_deployments(
            registry=_registry(),
            region=_REGION,
            catalog=_Catalog({"gpt-5.4-mini"}),
            quota=_Quota({"gpt-5.4-mini": 200_000}),
            capability_name="does.not.exist",
        )
        assert deployments == ()

    def test_names_match_collect_narrator_deployment_field(self) -> None:
        """The router must land on exactly the deployments Terraform created."""
        catalog = _Catalog({"gpt-5.4-mini", "gpt-5-mini"})
        quota = _Quota({"gpt-5.4-mini": 200_000, "gpt-5-mini": 200_000})
        _, candidates = collect_narrator(
            registry=_registry(),
            region=_REGION,
            catalog=catalog,
            quota=quota,
            endpoint=_ENDPOINT,
        )
        deployments = collect_narrator_deployments(
            registry=_registry(), region=_REGION, catalog=catalog, quota=quota,
        )
        assert {c.deployment for c in candidates} == {d.name for d in deployments}
