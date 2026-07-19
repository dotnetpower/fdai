"""LlmRegistry loader + mixed-model invariant."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fdai.rule_catalog.schema.llm_registry import (
    LlmRegistryError,
    MixedModelMode,
    Sku,
    load_llm_registry_from_mapping,
    load_llm_registry_from_yaml,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
UPSTREAM_REGISTRY = REPO_ROOT / "rule-catalog" / "llm-registry.yaml"


def _minimal() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "models": {
            "t1.embedding": {
                "preferences": [{"publisher": "OpenAI", "family": "text-embedding-3-small"}],
                "capacity_tpm": 100_000,
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


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_upstream_registry_file_loads_clean() -> None:
    registry = load_llm_registry_from_yaml(UPSTREAM_REGISTRY)
    assert registry.mixed_model_mode is MixedModelMode.AZURE_FOUNDRY
    assert "t1.embedding" in registry.models
    assert "t2.reasoner.primary" in registry.models
    assert "t2.reasoner.secondary" in registry.models
    assert registry.models["t1.embedding"].sku is Sku.STANDARD
    assert {
        preference.family for preference in registry.models["t2.reasoner.primary"].preferences
    } >= {
        "gpt-5",
        "gpt-5.2",
        "gpt-5.4",
    }


def test_load_from_mapping_accepts_minimal_shape() -> None:
    registry = load_llm_registry_from_mapping(_minimal())
    assert registry.models["t2.reasoner.primary"].preferences[0].family == "gpt-4o"
    assert registry.models["t2.reasoner.secondary"].preferences[0].publisher == "Anthropic"


# ---------------------------------------------------------------------------
# Structural violations (schema)
# ---------------------------------------------------------------------------


def test_missing_schema_version_is_rejected() -> None:
    raw = _minimal()
    del raw["schema_version"]
    with pytest.raises(LlmRegistryError) as exc:
        load_llm_registry_from_mapping(raw)
    assert any("schema_version" in i.key or "schema_version" in i.message for i in exc.value.issues)


def test_capability_key_pattern_is_enforced() -> None:
    raw = _minimal()
    models = raw["models"]
    assert isinstance(models, dict)
    models["bare-key"] = models.pop("t1.embedding")
    with pytest.raises(LlmRegistryError):
        load_llm_registry_from_mapping(raw)


def test_capacity_tpm_floor_is_enforced() -> None:
    raw = _minimal()
    models = raw["models"]
    assert isinstance(models, dict)
    primary = models["t2.reasoner.primary"]
    assert isinstance(primary, dict)
    primary["capacity_tpm"] = 100  # < 1000 floor
    with pytest.raises(LlmRegistryError):
        load_llm_registry_from_mapping(raw)


@pytest.mark.parametrize(
    "sku",
    ("ProvisionedManaged", "GlobalProvisionedManaged", "DataZoneProvisionedManaged"),
)
def test_provisioned_skus_require_ptu_capacity(sku: str) -> None:
    raw = _minimal()
    models = raw["models"]
    assert isinstance(models, dict)
    primary = models["t2.reasoner.primary"]
    assert isinstance(primary, dict)
    primary["sku"] = sku
    del primary["capacity_tpm"]
    primary["capacity_ptu"] = 30

    registry = load_llm_registry_from_mapping(raw)

    assert registry.models["t2.reasoner.primary"].requested_capacity == 30
    assert registry.models["t2.reasoner.primary"].capacity_unit == "ptu"


def test_provisioned_sku_rejects_tpm_capacity() -> None:
    raw = _minimal()
    models = raw["models"]
    assert isinstance(models, dict)
    primary = models["t2.reasoner.primary"]
    assert isinstance(primary, dict)
    primary["sku"] = "ProvisionedManaged"

    with pytest.raises(LlmRegistryError, match="capacity_ptu"):
        load_llm_registry_from_mapping(raw)


def test_capability_must_have_at_least_one_preference() -> None:
    raw = _minimal()
    models = raw["models"]
    assert isinstance(models, dict)
    primary = models["t2.reasoner.primary"]
    assert isinstance(primary, dict)
    primary["preferences"] = []
    with pytest.raises(LlmRegistryError):
        load_llm_registry_from_mapping(raw)


# ---------------------------------------------------------------------------
# Mixed-model invariant (pydantic)
# ---------------------------------------------------------------------------


def test_mixed_model_same_publisher_is_rejected_in_default_mode() -> None:
    raw = _minimal()
    models = raw["models"]
    assert isinstance(models, dict)
    secondary = models["t2.reasoner.secondary"]
    assert isinstance(secondary, dict)
    # Force same-publisher first-preference across the two reasoners.
    secondary["preferences"] = [{"publisher": "OpenAI", "family": "gpt-4-turbo"}]
    with pytest.raises(LlmRegistryError) as exc:
        load_llm_registry_from_mapping(raw)
    assert any("mixed-model" in i.message or "mixed_model" in i.message for i in exc.value.issues)


def test_mixed_model_hil_only_mode_allows_same_publisher() -> None:
    """In `hil-only` mode there is no secondary; the invariant does not apply."""
    raw = _minimal()
    raw["mixed_model_mode"] = "hil-only"
    models = raw["models"]
    assert isinstance(models, dict)
    secondary = models["t2.reasoner.secondary"]
    assert isinstance(secondary, dict)
    secondary["preferences"] = [{"publisher": "OpenAI", "family": "gpt-4-turbo"}]
    registry = load_llm_registry_from_mapping(raw)
    assert registry.mixed_model_mode is MixedModelMode.HIL_ONLY


# ---------------------------------------------------------------------------
# YAML loader guards
# ---------------------------------------------------------------------------


def test_yaml_loader_rejects_non_mapping_root(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("- item\n", encoding="utf-8")
    with pytest.raises(LlmRegistryError, match="mapping"):
        load_llm_registry_from_yaml(p)


def test_yaml_loader_reads_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.safe_dump(_minimal()), encoding="utf-8")
    registry = load_llm_registry_from_yaml(p)
    assert "t1.embedding" in registry.models


# ---------------------------------------------------------------------------
# Config <-> registry drift-guard
# ---------------------------------------------------------------------------


def test_default_llm_capabilities_all_exist_in_upstream_registry() -> None:
    """Every capability in the upstream config default (`_DEFAULT_LLM_CAPABILITIES`)
    MUST be declared in `rule-catalog/llm-registry.yaml`.

    Regression guard: renaming or removing a registry capability without
    updating `_DEFAULT_LLM_CAPABILITIES` would leave a boot-time reference
    to a nonexistent binding, which the composition root cannot resolve.
    Fails-fast at CI time instead of at process start.
    """
    from fdai.shared.config.models import _DEFAULT_LLM_CAPABILITIES

    registry = load_llm_registry_from_yaml(UPSTREAM_REGISTRY)
    missing = sorted(set(_DEFAULT_LLM_CAPABILITIES) - set(registry.models))
    assert not missing, (
        f"config default lists capabilities not declared in the upstream "
        f"llm-registry: {missing}. Add the capability to the registry, "
        f"remove it from _DEFAULT_LLM_CAPABILITIES, or fork-override the "
        f"registry."
    )
