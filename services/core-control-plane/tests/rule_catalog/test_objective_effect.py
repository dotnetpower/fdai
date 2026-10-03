from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.schema.objective_effect import (
    ObjectiveEffectBindingState,
    ObjectiveEffectCatalogError,
    RuleObjectiveEffectBinding,
    load_objective_effect_catalog,
    load_objective_effect_from_mapping,
    objective_effect_content_hash,
)

_RULE_REF = "kubernetes-cluster.diagnostic-settings-required@1.0.0"
_RULE_DIGEST = f"sha256:{'a' * 64}"
_OTHER_DIGEST = f"sha256:{'b' * 64}"
_ACTION_TYPE = "remediate.enable-diagnostic-settings"


def _binding_mapping() -> dict[str, object]:
    raw: dict[str, object] = {
        "schema_version": "1.0.0",
        "id": "effect.kubernetes-cluster-diagnostics",
        "version": "1.0.0",
        "rule": {"ref": _RULE_REF, "content_digest": _RULE_DIGEST},
        "action_type": _ACTION_TYPE,
        "effects": [
            {
                "objective_kind": "availability",
                "metric": "slo_signal_completeness",
                "utility": 0.6,
                "confidence": 0.9,
                "expected_min": -1.0,
                "expected_max": 1.0,
                "observation_window_seconds": 300,
            },
            {
                "objective_kind": "run_rate",
                "metric": "telemetry_ingestion_run_rate",
                "utility": -0.4,
                "confidence": 0.9,
                "expected_min": -1.0,
                "expected_max": 1.0,
                "observation_window_seconds": 300,
            },
        ],
        "reviewer": "Forseti",
        "state": "reviewed",
        "content_digest": _OTHER_DIGEST,
        "provenance": {
            "source_url": "https://github.com/dotnetpower/fdai",
            "resolved_ref": "objective-effect:kubernetes-cluster-diagnostics@1.0.0",
            "content_hash": _OTHER_DIGEST,
            "license": "MIT",
            "retrieved_at": "2026-10-04T00:00:00Z",
        },
    }
    loaded = RuleObjectiveEffectBinding.model_validate(raw)
    digest = objective_effect_content_hash(loaded)
    raw["content_digest"] = digest
    provenance = raw["provenance"]
    assert isinstance(provenance, dict)
    provenance["content_hash"] = digest
    return raw


def _load(raw: dict[str, object]):
    return load_objective_effect_from_mapping(
        raw,
        rule_digests={_RULE_REF: _RULE_DIGEST},
        action_type_names=frozenset({_ACTION_TYPE}),
    )


def test_valid_objective_effect_binding_is_digest_bound() -> None:
    binding = _load(_binding_mapping())

    assert binding.rule.ref == _RULE_REF
    assert binding.action_type == _ACTION_TYPE
    assert binding.state is ObjectiveEffectBindingState.REVIEWED
    assert binding.content_digest == objective_effect_content_hash(binding)


@pytest.mark.parametrize("field", ["domain", "option_id", "authority", "approval"])
def test_objective_effect_binding_rejects_authority_and_option_fields(field: str) -> None:
    raw = _binding_mapping()
    raw[field] = "forbidden"

    with pytest.raises(ObjectiveEffectCatalogError, match="Extra inputs"):
        _load(raw)


def test_objective_effect_binding_rejects_stale_pins() -> None:
    raw = deepcopy(_binding_mapping())
    rule = raw["rule"]
    assert isinstance(rule, dict)
    rule["content_digest"] = _OTHER_DIGEST

    with pytest.raises(ObjectiveEffectCatalogError) as raised:
        _load(raw)

    messages = " ".join(issue.message for issue in raised.value.issues)
    assert "rule digest mismatch" in messages
    assert "content_digest mismatch" in messages


def test_objective_effect_catalog_fails_closed_for_missing_required_binding(tmp_path: Path) -> None:
    (tmp_path / "effect.yaml").write_text(
        yaml.safe_dump(_binding_mapping(), sort_keys=False),
        encoding="utf-8",
    )

    bindings = load_objective_effect_catalog(
        tmp_path,
        rule_digests={_RULE_REF: _RULE_DIGEST},
        action_type_names=frozenset({_ACTION_TYPE}),
        required_bindings=frozenset(
            {("kubernetes-cluster.diagnostic-settings-required", _ACTION_TYPE)}
        ),
    )
    assert len(bindings) == 1

    with pytest.raises(ObjectiveEffectCatalogError, match="missing reviewed"):
        load_objective_effect_catalog(
            tmp_path,
            rule_digests={_RULE_REF: _RULE_DIGEST},
            action_type_names=frozenset({_ACTION_TYPE}),
            required_bindings=frozenset({("missing.rule", _ACTION_TYPE)}),
        )
