"""Bootstrap resolver - gates + idempotency."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from fdai.rule_catalog.schema.llm_registry import load_llm_registry_from_mapping
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    CatalogQuery,
    PermissionQuery,
    QuotaQuery,
    ResolvedCapability,
    ResolvedModels,
    ResolverError,
    resolve,
)

_SUB = "00000000-0000-0000-0000-000000000000"
_OID = "00000000-0000-0000-0000-000000000001"
_REGION = "koreacentral"


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
