"""Bootstrap resolver - gates + idempotency."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fdai.rule_catalog.schema.llm_registry import (
    load_llm_registry_from_mapping,
    load_llm_registry_from_yaml,
)
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    CatalogQuery,
    PermissionQuery,
    ProvisionedCapacityQuery,
    QuotaQuery,
    ResolvedCapability,
    ResolvedModels,
    ResolverError,
    resolve,
)
from fdai.rule_catalog.schema.model_binding_policy import load_model_binding_policy_from_mapping

_SUB = "00000000-0000-0000-0000-000000000000"
_OID = "00000000-0000-0000-0000-000000000001"
_REGION = "koreacentral"
_UPSTREAM_REGISTRY = Path(__file__).resolve().parents[5] / "rule-catalog" / "llm-registry.yaml"


def _registry(overrides: Mapping[str, Any] | None = None):  # type: ignore[no-untyped-def]
    raw: dict[str, Any] = {
        "schema_version": "1.0.0",
        "models": {
            "t1.embedding": {
                "preferences": [
                    {"publisher": "OpenAI", "family": "text-embedding-3-small"},
                    {"publisher": "OpenAI", "family": "text-embedding-3-large"},
                ],
                "capacity_tpm": 100_000,
            },
            "t1.judge": {
                "preferences": [{"publisher": "OpenAI", "family": "gpt-4o-mini"}],
                "capacity_tpm": 40_000,
            },
            "t2.reasoner.primary": {
                "preferences": [{"publisher": "OpenAI", "family": "gpt-4o"}],
                "capacity_tpm": 20_000,
            },
            "t2.reasoner.secondary": {
                "preferences": [{"publisher": "Anthropic", "family": "claude-opus-4"}],
                "capacity_tpm": 10_000,
            },
        },
    }
    if overrides:
        raw.update(overrides)
    return load_llm_registry_from_mapping(raw)


class _StaticCatalog(CatalogQuery):
    def __init__(self, families: set[str]) -> None:
        self._families = set(families)

    def families_in_region(self, region: str) -> set[str]:
        del region
        return set(self._families)


class _PublisherStaticCatalog(_StaticCatalog):
    def __init__(self, families: set[str], publisher_families: set[tuple[str, str]]) -> None:
        super().__init__(families)
        self._publisher_families = set(publisher_families)

    def publisher_families_in_region(self, region: str) -> set[tuple[str, str]]:
        del region
        return set(self._publisher_families)


class _AlwaysPermissionQuery(PermissionQuery):
    def __init__(self, granted: bool) -> None:
        self._granted = granted

    def principal_has_cognitive_services_contributor(
        self, *, subscription_id: str, principal_object_id: str
    ) -> bool:
        del subscription_id, principal_object_id
        return self._granted


class _DictQuota(QuotaQuery):
    def __init__(self, table: dict[tuple[str, str], int], default: int = 0) -> None:
        self._table = dict(table)
        self._default = default

    def available_capacity_tpm(self, *, region: str, publisher: str, family: str) -> int:
        del region
        return self._table.get((publisher, family), self._default)


class _SkuDictQuota(_DictQuota):
    def __init__(self, table: dict[tuple[str, str, str], int]) -> None:
        super().__init__({})
        self._sku_table = dict(table)

    def available_capacity_tpm_for_sku(
        self,
        *,
        region: str,
        publisher: str,
        family: str,
        sku: str,
    ) -> int:
        del region
        return self._sku_table.get((publisher, family, sku), 0)


class _PtuCapacity(ProvisionedCapacityQuery):
    def __init__(self, available: int) -> None:
        self._available = available

    def available_capacity_ptu(
        self,
        *,
        region: str,
        publisher: str,
        family: str,
        sku: str,
    ) -> int:
        del region, publisher, family, sku
        return self._available


class _PtuCapacityByFamily(ProvisionedCapacityQuery):
    def __init__(self, available: Mapping[str, int]) -> None:
        self._available = dict(available)

    def available_capacity_ptu(
        self,
        *,
        region: str,
        publisher: str,
        family: str,
        sku: str,
    ) -> int:
        del region, publisher, sku
        return self._available.get(family, 0)


class _StaticVersions:
    def __init__(self, versions: Mapping[tuple[str, str], str]) -> None:
        self._versions = dict(versions)

    def latest_stable_version(self, *, region: str, publisher: str, family: str) -> str | None:
        del region
        return self._versions.get((publisher, family))


class _InvalidVersions:
    def __init__(self, value: object) -> None:
        self._value = value

    def latest_stable_version(self, *, region: str, publisher: str, family: str) -> str | None:
        del region, publisher, family
        return self._value  # type: ignore[return-value]


def _default_full_quota() -> _DictQuota:
    return _DictQuota(
        {
            ("OpenAI", "text-embedding-3-small"): 100_000,
            ("OpenAI", "text-embedding-3-large"): 100_000,
            ("OpenAI", "gpt-4o-mini"): 40_000,
            ("OpenAI", "gpt-4o"): 20_000,
            ("Anthropic", "claude-opus-4"): 10_000,
        }
    )


def _families_full() -> set[str]:
    return {
        "text-embedding-3-small",
        "text-embedding-3-large",
        "gpt-4o-mini",
        "gpt-4o",
        "claude-opus-4",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_resolve_maps_every_capability_when_all_gates_pass() -> None:
    result = resolve(
        registry=_registry(),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(_families_full()),
        permission=_AlwaysPermissionQuery(True),
        quota=_default_full_quota(),
    )
    assert {c.name for c in result.capabilities} == {
        "t1.embedding",
        "t1.judge",
        "t2.reasoner.primary",
        "t2.reasoner.secondary",
    }
    for c in result.capabilities:
        assert c.status is CapabilityStatus.RESOLVED


def test_publisher_catalog_does_not_match_same_named_family_from_wrong_publisher() -> None:
    publisher_families = {("OpenAI", family) for family in _families_full()}
    result = resolve(
        registry=_registry(),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_PublisherStaticCatalog(_families_full(), publisher_families),
        permission=_AlwaysPermissionQuery(True),
        quota=_default_full_quota(),
    )

    secondary = next(item for item in result.capabilities if item.name == "t2.reasoner.secondary")
    assert secondary.status is CapabilityStatus.HIL_ONLY
    assert secondary.reasons[0].startswith("no_preferred_family_in_region")


@pytest.mark.parametrize("version", [None, 1, ""])
def test_live_version_query_must_return_stable_string(version: object) -> None:
    with pytest.raises(ResolverError, match="no_stable_model_version"):
        resolve(
            registry=_registry(),
            region=_REGION,
            subscription_id=_SUB,
            deployer_object_id=_OID,
            catalog=_StaticCatalog(_families_full()),
            permission=_AlwaysPermissionQuery(True),
            quota=_default_full_quota(),
            model_versions=_InvalidVersions(version),
        )


def test_upstream_secondary_resolves_reviewed_mistral_profile() -> None:
    policy = load_model_binding_policy_from_mapping(
        {
            "schema_version": "1.0.0",
            "environment": "dev",
            "revision": 1,
            "capabilities": {
                "t2.reasoner.secondary": {
                    "selection_mode": "pinned",
                    "publisher": "MistralAI",
                    "family": "Mistral-Large-3",
                    "version_policy": "latest-compatible",
                    "sku": "GlobalStandard",
                    "capacity": {"unit": "tpm", "value": 1_000},
                }
            },
        }
    )
    result = resolve(
        registry=load_llm_registry_from_yaml(_UPSTREAM_REGISTRY),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_PublisherStaticCatalog(
            {"gpt-4o", "claude-opus-4", "Mistral-Large-3"},
            {
                ("OpenAI", "gpt-4o"),
                ("Anthropic", "claude-opus-4"),
                ("MistralAI", "Mistral-Large-3"),
            },
        ),
        permission=_AlwaysPermissionQuery(True),
        quota=_SkuDictQuota(
            {
                ("OpenAI", "gpt-4o", "Standard"): 100_000,
                ("Anthropic", "claude-opus-4", "Standard"): 100_000,
                ("MistralAI", "Mistral-Large-3", "GlobalStandard"): 1_000,
            }
        ),
        model_versions=_StaticVersions(
            {
                ("OpenAI", "gpt-4o"): "2024-11-20",
                ("Anthropic", "claude-opus-4"): "2026-01-01",
                ("MistralAI", "Mistral-Large-3"): "1",
            }
        ),
        binding_policy=policy,
    )

    secondary = next(item for item in result.capabilities if item.name == "t2.reasoner.secondary")
    assert secondary.status is CapabilityStatus.RESOLVED
    assert secondary.publisher == "MistralAI"
    assert secondary.family == "Mistral-Large-3"
    assert secondary.version == "1"
    assert secondary.sku == "GlobalStandard"
    assert secondary.capacity_tpm == 1_000


def test_legacy_quota_adapter_cannot_resolve_nonstandard_mistral_sku() -> None:
    policy = load_model_binding_policy_from_mapping(
        {
            "schema_version": "1.0.0",
            "environment": "dev",
            "revision": 1,
            "capabilities": {
                "t2.reasoner.secondary": {
                    "selection_mode": "pinned",
                    "publisher": "MistralAI",
                    "family": "Mistral-Large-3",
                    "version_policy": "latest-compatible",
                    "sku": "GlobalStandard",
                    "capacity": {"unit": "tpm", "value": 1_000},
                }
            },
        }
    )
    result = resolve(
        registry=load_llm_registry_from_yaml(_UPSTREAM_REGISTRY),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_PublisherStaticCatalog(
            {"gpt-4o", "claude-opus-4", "Mistral-Large-3"},
            {
                ("OpenAI", "gpt-4o"),
                ("Anthropic", "claude-opus-4"),
                ("MistralAI", "Mistral-Large-3"),
            },
        ),
        permission=_AlwaysPermissionQuery(True),
        quota=_DictQuota(
            {
                ("OpenAI", "gpt-4o"): 100_000,
                ("Anthropic", "claude-opus-4"): 100_000,
                ("MistralAI", "Mistral-Large-3"): 1_000,
            }
        ),
        model_versions=_StaticVersions(
            {
                ("OpenAI", "gpt-4o"): "2024-11-20",
                ("Anthropic", "claude-opus-4"): "2026-01-01",
                ("MistralAI", "Mistral-Large-3"): "1",
            }
        ),
        binding_policy=policy,
    )

    secondary = next(item for item in result.capabilities if item.name == "t2.reasoner.secondary")
    assert secondary.status is CapabilityStatus.HIL_ONLY
    assert "zero_quota" in secondary.reasons[0]


def test_resolve_maps_ontology_council_slots_without_weakening_reasoner_invariant() -> None:
    council_families = {"gpt-5.6-sol", "gpt-5.5", "gpt-5.4"}
    quota = _SkuDictQuota(
        {
            ("OpenAI", "text-embedding-3-small", "Standard"): 200_000,
            ("OpenAI", "gpt-5.4-mini", "Standard"): 200_000,
            ("OpenAI", "gpt-4.1-nano", "GlobalStandard"): 100_000,
            ("OpenAI", "gpt-4o", "Standard"): 100_000,
            ("Anthropic", "claude-opus-4", "Standard"): 100_000,
            ("OpenAI", "gpt-5.6-sol", "GlobalStandard"): 50_000,
            ("OpenAI", "gpt-5.5", "GlobalStandard"): 50_000,
            ("OpenAI", "gpt-5.4", "GlobalStandard"): 100_000,
        }
    )

    result = resolve(
        registry=load_llm_registry_from_yaml(_UPSTREAM_REGISTRY),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(
            {
                "text-embedding-3-small",
                "gpt-5.4-mini",
                "gpt-4.1-nano",
                "gpt-4o",
                "claude-opus-4",
            }
            | council_families
        ),
        permission=_AlwaysPermissionQuery(True),
        quota=quota,
    )

    by_name = {capability.name: capability for capability in result.capabilities}
    for name in (
        "t2.ontology.council.alpha",
        "t2.ontology.council.beta",
        "t2.ontology.council.gamma",
    ):
        assert by_name[name].status is CapabilityStatus.RESOLVED
    assert by_name["t2.reasoner.primary"].publisher == "OpenAI"
    assert by_name["t2.reasoner.secondary"].publisher == "Anthropic"


# ---------------------------------------------------------------------------
# Gate: no cognitive services contributor
# ---------------------------------------------------------------------------


def test_missing_role_degrades_every_capability_to_hil_only() -> None:
    result = resolve(
        registry=_registry(),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(_families_full()),
        permission=_AlwaysPermissionQuery(False),
        quota=_default_full_quota(),
    )
    for c in result.capabilities:
        assert c.status is CapabilityStatus.HIL_ONLY
        assert any("cognitive_services_contributor" in r for r in c.reasons)


# ---------------------------------------------------------------------------
# Gate: preferred family missing from region
# ---------------------------------------------------------------------------


def test_missing_family_marks_only_that_capability_hil() -> None:
    """A region drop that forces the resolver to fall through preferences
    into a same-publisher family for the secondary reasoner MUST raise -
    the invariant is enforced *after* resolve, not just at load time."""
    reg = _registry(
        {
            "models": {
                "t1.embedding": {
                    "preferences": [
                        {"publisher": "OpenAI", "family": "text-embedding-3-small"},
                    ],
                    "capacity_tpm": 100_000,
                },
                "t1.judge": {
                    "preferences": [{"publisher": "OpenAI", "family": "gpt-4o-mini"}],
                    "capacity_tpm": 40_000,
                },
                "t2.reasoner.primary": {
                    "preferences": [{"publisher": "OpenAI", "family": "gpt-4o"}],
                    "capacity_tpm": 20_000,
                },
                # Secondary's FIRST preference is Anthropic (invariant OK at load),
                # but the region only has the FALLBACK OpenAI family.
                "t2.reasoner.secondary": {
                    "preferences": [
                        {"publisher": "Anthropic", "family": "claude-opus-4"},
                        {"publisher": "OpenAI", "family": "gpt-4-turbo"},
                    ],
                    "capacity_tpm": 10_000,
                },
            }
        }
    )
    # Region lacks claude-opus-4 but has gpt-4-turbo → secondary resolves to OpenAI
    # → mixed-model invariant violated after resolve.
    catalog_families = {
        "text-embedding-3-small",
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4-turbo",
    }
    quota = _DictQuota(
        {
            ("OpenAI", "text-embedding-3-small"): 100_000,
            ("OpenAI", "gpt-4o-mini"): 40_000,
            ("OpenAI", "gpt-4o"): 20_000,
            ("OpenAI", "gpt-4-turbo"): 10_000,
        }
    )
    with pytest.raises(ResolverError, match="mixed_model_invariant"):
        resolve(
            registry=reg,
            region=_REGION,
            subscription_id=_SUB,
            deployer_object_id=_OID,
            catalog=_StaticCatalog(catalog_families),
            permission=_AlwaysPermissionQuery(True),
            quota=quota,
        )


def test_missing_family_hil_only_when_registry_stays_valid() -> None:
    """The region drops the secondary's preferred family; only that
    capability degrades to HIL_ONLY - the primary + T1 keep working."""
    missing_secondary = _families_full() - {"claude-opus-4"}
    result = resolve(
        registry=_registry(),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(missing_secondary),
        permission=_AlwaysPermissionQuery(True),
        quota=_default_full_quota(),
    )
    by_name = {c.name: c for c in result.capabilities}
    assert by_name["t2.reasoner.secondary"].status is CapabilityStatus.HIL_ONLY
    assert by_name["t2.reasoner.primary"].status is CapabilityStatus.RESOLVED
    assert by_name["t1.embedding"].status is CapabilityStatus.RESOLVED


# ---------------------------------------------------------------------------
# Gate: quota reduction / refusal
# ---------------------------------------------------------------------------


def test_quota_reduction_marks_capacity_reduced() -> None:
    quota = _DictQuota(
        {
            ("OpenAI", "text-embedding-3-small"): 50_000,
            ("OpenAI", "text-embedding-3-large"): 50_000,
            ("OpenAI", "gpt-4o-mini"): 40_000,
            ("OpenAI", "gpt-4o"): 20_000,
            ("Anthropic", "claude-opus-4"): 10_000,
        }
    )
    result = resolve(
        registry=_registry(),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(_families_full()),
        permission=_AlwaysPermissionQuery(True),
        quota=quota,
    )
    embed = next(c for c in result.capabilities if c.name == "t1.embedding")
    assert embed.status is CapabilityStatus.CAPACITY_REDUCED
    assert embed.capacity_tpm == 50_000
    assert any("capacity_reduced" in r for r in embed.reasons)


def test_provisioned_capacity_uses_ptu_without_tpm_conversion() -> None:
    raw = _minimal_registry_with_provisioned_primary()
    result = resolve(
        registry=load_llm_registry_from_mapping(raw),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(_families_full()),
        permission=_AlwaysPermissionQuery(True),
        quota=_default_full_quota(),
        provisioned_capacity=_PtuCapacity(20),
    )

    primary = _cap(result, "t2.reasoner.primary")
    assert primary.status is CapabilityStatus.CAPACITY_REDUCED
    assert primary.capacity_tpm == 0
    assert primary.capacity_unit == "ptu"
    assert primary.capacity_value == 20
    assert '"capacity": {' in result.to_json()
    assert '"value": 20' in result.to_json()


def test_provisioned_capacity_falls_through_to_deployable_preference() -> None:
    raw = _minimal_registry_with_provisioned_primary()
    raw["models"]["t2.reasoner.primary"]["preferences"] = [
        {"publisher": "OpenAI", "family": "gpt-4o"},
        {"publisher": "OpenAI", "family": "gpt-4.1"},
    ]
    result = resolve(
        registry=load_llm_registry_from_mapping(raw),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(_families_full() | {"gpt-4.1"}),
        permission=_AlwaysPermissionQuery(True),
        quota=_default_full_quota(),
        provisioned_capacity=_PtuCapacityByFamily({"gpt-4o": 0, "gpt-4.1": 30}),
    )

    primary = _cap(result, "t2.reasoner.primary")
    assert primary.status is CapabilityStatus.RESOLVED
    assert primary.family == "gpt-4.1"
    assert primary.capacity_unit == "ptu"
    assert primary.capacity_value == 30


def test_pinned_policy_uses_only_requested_ptu_family() -> None:
    policy = load_model_binding_policy_from_mapping(
        {
            "schema_version": "1.0.0",
            "environment": "production",
            "revision": 2,
            "capabilities": {
                "t2.reasoner.primary": {
                    "selection_mode": "pinned",
                    "publisher": "OpenAI",
                    "family": "gpt-4.1",
                    "version_policy": "latest-compatible",
                    "sku": "GlobalProvisionedManaged",
                    "capacity": {"unit": "ptu", "value": 30},
                }
            },
        }
    )
    result = resolve(
        registry=_registry(),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(_families_full() | {"gpt-4.1"}),
        permission=_AlwaysPermissionQuery(True),
        quota=_default_full_quota(),
        provisioned_capacity=_PtuCapacityByFamily({"gpt-4o": 30, "gpt-4.1": 30}),
        binding_policy=policy,
    )

    primary = _cap(result, "t2.reasoner.primary")
    assert primary.family == "gpt-4.1"
    assert primary.sku == "GlobalProvisionedManaged"
    assert primary.selection_mode == "pinned"
    assert result.binding_policy_revision == 2
    assert result.binding_policy_digest == policy.digest()


def test_hil_only_policy_skips_provider_capacity() -> None:
    policy = load_model_binding_policy_from_mapping(
        {
            "schema_version": "1.0.0",
            "environment": "production",
            "revision": 1,
            "capabilities": {"t2.reasoner.secondary": {"selection_mode": "hil-only"}},
        }
    )
    result = resolve(
        registry=_registry(),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(_families_full()),
        permission=_AlwaysPermissionQuery(True),
        quota=_default_full_quota(),
        binding_policy=policy,
    )

    secondary = _cap(result, "t2.reasoner.secondary")
    assert secondary.status is CapabilityStatus.HIL_ONLY
    assert secondary.selection_mode == "hil-only"
    assert secondary.reasons == ("binding_policy_hil_only",)


def test_provisioned_capacity_without_capacity_query_fails_closed() -> None:
    result = resolve(
        registry=load_llm_registry_from_mapping(_minimal_registry_with_provisioned_primary()),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(_families_full()),
        permission=_AlwaysPermissionQuery(True),
        quota=_default_full_quota(),
    )

    primary = _cap(result, "t2.reasoner.primary")
    assert primary.status is CapabilityStatus.HIL_ONLY
    assert primary.capacity_unit == "ptu"
    assert "provisioned_capacity_query_unavailable" in primary.reasons


def _minimal_registry_with_provisioned_primary() -> dict[str, Any]:
    raw = {
        "schema_version": "1.0.0",
        "models": {
            "t1.embedding": {
                "preferences": [{"publisher": "OpenAI", "family": "text-embedding-3-small"}],
                "capacity_tpm": 100_000,
            },
            "t1.judge": {
                "preferences": [{"publisher": "OpenAI", "family": "gpt-4o-mini"}],
                "capacity_tpm": 40_000,
            },
            "t2.reasoner.primary": {
                "preferences": [{"publisher": "OpenAI", "family": "gpt-4o"}],
                "sku": "ProvisionedManaged",
                "capacity_ptu": 30,
            },
            "t2.reasoner.secondary": {
                "preferences": [{"publisher": "Anthropic", "family": "claude-opus-4"}],
                "capacity_tpm": 10_000,
            },
        },
    }
    return raw


def test_quota_below_min_ratio_marks_hil_only() -> None:
    quota = _DictQuota(
        {
            # 10k < 20% of 100k (20k) → HIL_ONLY
            ("OpenAI", "text-embedding-3-small"): 10_000,
            ("OpenAI", "text-embedding-3-large"): 10_000,
            ("OpenAI", "gpt-4o-mini"): 40_000,
            ("OpenAI", "gpt-4o"): 20_000,
            ("Anthropic", "claude-opus-4"): 10_000,
        }
    )
    result = resolve(
        registry=_registry(),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(_families_full()),
        permission=_AlwaysPermissionQuery(True),
        quota=quota,
    )
    embed = next(c for c in result.capabilities if c.name == "t1.embedding")
    assert embed.status is CapabilityStatus.HIL_ONLY
    assert any("quota_below_min_ratio" in r for r in embed.reasons)


def test_zero_quota_marks_hil_only() -> None:
    quota = _DictQuota(
        {
            ("OpenAI", "text-embedding-3-small"): 0,
            ("OpenAI", "text-embedding-3-large"): 100_000,
            ("OpenAI", "gpt-4o-mini"): 40_000,
            ("OpenAI", "gpt-4o"): 20_000,
            ("Anthropic", "claude-opus-4"): 10_000,
        }
    )
    result = resolve(
        registry=_registry(),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog({"text-embedding-3-small"}),  # only this one
        permission=_AlwaysPermissionQuery(True),
        quota=quota,
    )
    embed = next(c for c in result.capabilities if c.name == "t1.embedding")
    assert embed.status is CapabilityStatus.HIL_ONLY
    assert any("zero_quota" in r for r in embed.reasons)


# ---------------------------------------------------------------------------
# Idempotency + serialization
# ---------------------------------------------------------------------------


def test_resolve_output_is_deterministic() -> None:
    kwargs = dict(
        registry=_registry(),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(_families_full()),
        permission=_AlwaysPermissionQuery(True),
        quota=_default_full_quota(),
    )
    a = resolve(**kwargs)  # type: ignore[arg-type]
    b = resolve(**kwargs)  # type: ignore[arg-type]
    assert a.to_json() == b.to_json()


def test_resolved_models_round_trips_json() -> None:
    original = resolve(
        registry=_registry(),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(_families_full()),
        permission=_AlwaysPermissionQuery(True),
        quota=_default_full_quota(),
    )
    text = original.to_json()
    restored = ResolvedModels.from_json(text)
    assert restored.to_json() == text
    # And frozen record equality - every field.
    for a, b in zip(original.capabilities, restored.capabilities, strict=True):
        assert isinstance(a, ResolvedCapability)
        assert a == b


def test_resolved_capability_rejects_negative_tpm() -> None:
    with pytest.raises(ValueError, match="capacity_tpm"):
        ResolvedCapability(
            name="t1.embedding",
            status=CapabilityStatus.RESOLVED,
            publisher="OpenAI",
            family="text-embedding-3-small",
            sku="Standard",
            capacity_tpm=-1,
            invocation="always",
        )


def _resolved_models_fixture() -> ResolvedModels:
    return resolve(
        registry=_registry(),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(_families_full()),
        permission=_AlwaysPermissionQuery(True),
        quota=_default_full_quota(),
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda raw: raw.update(schema_version="2.0.0"), "schema_version"),
        (
            lambda raw: raw["capabilities"][0].update(capacity_tpm=1000.5),
            "capacity_tpm",
        ),
        (
            lambda raw: raw.update(narrator_candidates=[{"endpoint": "https://example.invalid"}]),
            "narrator_candidates",
        ),
    ],
)
def test_resolved_models_rejects_malformed_replay_fields(
    mutation: Any,
    message: str,
) -> None:
    raw = json.loads(_resolved_models_fixture().to_json())
    mutation(raw)

    with pytest.raises(ValueError, match=message):
        ResolvedModels.from_json(json.dumps(raw))


def test_resolved_models_rejects_duplicate_json_keys() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        ResolvedModels.from_json('{"schema_version":"1.0.0","schema_version":"2.0.0"}')


def test_resolved_models_rejects_duplicate_capability_names() -> None:
    raw = json.loads(_resolved_models_fixture().to_json())
    raw["capabilities"][0]["name"] = raw["capabilities"][1]["name"]

    with pytest.raises(ValueError, match="capability names MUST be unique"):
        ResolvedModels.from_json(json.dumps(raw))


# ---------------------------------------------------------------------------
# Gate: tool_calling_required family support (G3)
# ---------------------------------------------------------------------------


def _registry_tool_calling():  # type: ignore[no-untyped-def]
    raw: dict[str, Any] = {
        "schema_version": "1.0.0",
        "models": {
            "t1.embedding": {
                "preferences": [{"publisher": "OpenAI", "family": "text-embedding-3-small"}],
                "capacity_tpm": 100_000,
            },
            "t1.judge": {
                "preferences": [{"publisher": "OpenAI", "family": "gpt-4o-mini"}],
                "capacity_tpm": 40_000,
            },
            "t2.reasoner.primary": {
                "preferences": [{"publisher": "OpenAI", "family": "gpt-4o"}],
                "capacity_tpm": 20_000,
                "tool_calling_required": True,
            },
            "t2.reasoner.secondary": {
                "preferences": [{"publisher": "Anthropic", "family": "claude-opus-4"}],
                "capacity_tpm": 10_000,
            },
        },
    }
    return load_llm_registry_from_mapping(raw)


def _resolve_tool_calling(tool_calling_families: frozenset[str] | None):  # type: ignore[no-untyped-def]
    return resolve(
        registry=_registry_tool_calling(),
        region=_REGION,
        subscription_id=_SUB,
        deployer_object_id=_OID,
        catalog=_StaticCatalog(_families_full()),
        permission=_AlwaysPermissionQuery(True),
        quota=_default_full_quota(),
        tool_calling_families=tool_calling_families,
    )


def _cap(result: ResolvedModels, name: str) -> ResolvedCapability:
    return next(c for c in result.capabilities if c.name == name)


def test_tool_calling_required_resolves_when_family_supported() -> None:
    result = _resolve_tool_calling(frozenset({"gpt-4o"}))
    assert _cap(result, "t2.reasoner.primary").status is CapabilityStatus.RESOLVED


def test_tool_calling_required_degrades_when_family_unsupported() -> None:
    # gpt-4o (the primary's chosen family) is NOT tool-calling capable here.
    result = _resolve_tool_calling(frozenset({"gpt-4o-mini"}))
    primary = _cap(result, "t2.reasoner.primary")
    assert primary.status is CapabilityStatus.HIL_ONLY
    assert any("family_lacks_tool_calling" in r for r in primary.reasons)
    # A capability that does not require tool calling is unaffected.
    assert _cap(result, "t1.judge").status is CapabilityStatus.RESOLVED


def test_tool_calling_none_skips_the_check() -> None:
    # No tool-calling probe supplied -> existing behavior, primary resolves.
    result = _resolve_tool_calling(None)
    assert _cap(result, "t2.reasoner.primary").status is CapabilityStatus.RESOLVED
