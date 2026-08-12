from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.schema.rule_objective_binding import (
    BindingState,
    RuleObjectiveBinding,
    RuleObjectiveBindingCatalogError,
    evidence_signature_digest,
    load_rule_objective_binding_catalog,
    load_rule_objective_binding_from_mapping,
    rule_objective_binding_content_hash,
    validate_rule_objective_binding_transition,
)

_OBJECTIVE_REF = "reliability.node-pool.zone-failure-tolerance@1.0.0"
_RULE_REF = "kubernetes-node-pool.multi-zone@1.0.0"
_RECEIPT_REF = "equivalence.node-pool-zone-resilience@1.0.0"
_DIGEST_A = f"sha256:{'a' * 64}"
_DIGEST_B = f"sha256:{'b' * 64}"
_DIGEST_C = f"sha256:{'c' * 64}"


def _binding_mapping() -> dict[str, object]:
    raw: dict[str, object] = {
        "schema_version": "1.0.0",
        "id": "binding.node-pool-zone-resilience",
        "version": "1.0.0",
        "objective": {"ref": _OBJECTIVE_REF, "content_digest": _DIGEST_A},
        "rule": {"ref": _RULE_REF, "content_digest": _DIGEST_B},
        "relationship": "realizes",
        "applicability_delta": {
            "provider_refs": ["provider.azure"],
            "resource_subtype_refs": ["resource-type.kubernetes-node-pool"],
            "evidence_shape_refs": ["evidence.node-pool.topology"],
            "environment_constraint_refs": ["environment.production"],
        },
        "variant_dimensions": ["provider_mapping", "threshold"],
        "implementation_signature_digest": _DIGEST_B,
        "evidence_signature_digest": evidence_signature_digest(("evidence.node-pool.topology",)),
        "required_evidence_refs": ["evidence.node-pool.topology"],
        "equivalence_receipt": {
            "ref": _RECEIPT_REF,
            "content_digest": _DIGEST_C,
        },
        "non_equivalence_reasons": [],
        "reviewer": "Mimir",
        "state": "candidate",
        "content_digest": _DIGEST_C,
        "provenance": {
            "source_url": "https://github.com/dotnetpower/fdai",
            "resolved_ref": "binding:node-pool-zone-resilience@1.0.0",
            "content_hash": _DIGEST_C,
            "license": "MIT",
            "retrieved_at": "2026-08-13T00:00:00Z",
        },
    }
    draft = RuleObjectiveBinding.model_validate(raw)
    digest = rule_objective_binding_content_hash(draft)
    raw["content_digest"] = digest
    provenance = raw["provenance"]
    assert isinstance(provenance, dict)
    provenance["content_hash"] = digest
    return raw


def _load(raw: dict[str, object]) -> RuleObjectiveBinding:
    return load_rule_objective_binding_from_mapping(
        raw,
        objective_digests={_OBJECTIVE_REF: _DIGEST_A},
        rule_digests={_RULE_REF: _DIGEST_B},
        rule_implementation_digests={_RULE_REF: _DIGEST_B},
        evidence_refs=frozenset({"evidence.node-pool.topology"}),
        equivalence_receipt_digests={_RECEIPT_REF: _DIGEST_C},
        reviewed_equivalence_receipt_refs=frozenset({_RECEIPT_REF}),
    )


def _with_state(raw: dict[str, object], state: str) -> dict[str, object]:
    raw["state"] = state
    draft = RuleObjectiveBinding.model_validate(raw)
    digest = rule_objective_binding_content_hash(draft)
    raw["content_digest"] = digest
    provenance = raw["provenance"]
    assert isinstance(provenance, dict)
    provenance["content_hash"] = digest
    return raw


def test_valid_binding_pins_every_authoritative_catalog_record() -> None:
    binding = _load(_binding_mapping())

    assert binding.objective.ref == _OBJECTIVE_REF
    assert binding.rule.ref == _RULE_REF
    assert binding.equivalence_receipt is not None
    assert binding.content_digest == rule_objective_binding_content_hash(binding)


@pytest.mark.parametrize(
    "field",
    ["effect", "enforcement", "parameter_values", "approval", "execution_authority"],
)
def test_binding_rejects_authority_and_assignment_fields(field: str) -> None:
    raw = _binding_mapping()
    raw[field] = "forbidden"

    with pytest.raises(RuleObjectiveBindingCatalogError, match="Extra inputs"):
        _load(raw)


def test_binding_aggregates_unknown_refs_and_digest_drift() -> None:
    raw = deepcopy(_binding_mapping())
    objective = raw["objective"]
    rule = raw["rule"]
    receipt = raw["equivalence_receipt"]
    assert isinstance(objective, dict)
    assert isinstance(rule, dict)
    assert isinstance(receipt, dict)
    objective["ref"] = "reliability.unknown@1.0.0"
    rule["content_digest"] = _DIGEST_C
    receipt["ref"] = "equivalence.unknown@1.0.0"
    raw["required_evidence_refs"] = ["evidence.unknown"]
    raw["reviewer"] = "Changed reviewer"

    with pytest.raises(RuleObjectiveBindingCatalogError) as raised:
        _load(raw)

    messages = " ".join(issue.message for issue in raised.value.issues)
    assert "unknown objective version" in messages
    assert "rule digest mismatch" in messages
    assert "unknown evidence reference" in messages
    assert "unknown equivalence_receipt version" in messages
    assert "not independently reviewed" in messages
    assert "content_digest mismatch" in messages


def test_binding_rejects_unverified_signatures() -> None:
    raw = _binding_mapping()
    raw["implementation_signature_digest"] = _DIGEST_A
    raw["evidence_signature_digest"] = _DIGEST_A

    with pytest.raises(RuleObjectiveBindingCatalogError) as raised:
        _load(raw)

    messages = " ".join(issue.message for issue in raised.value.issues)
    assert "implementation signature mismatch" in messages
    assert "evidence signature mismatch" in messages


def test_partial_realization_requires_non_equivalence_reason() -> None:
    raw = _binding_mapping()
    raw["relationship"] = "partially_realizes"
    raw["equivalence_receipt"] = None

    with pytest.raises(RuleObjectiveBindingCatalogError, match="non_equivalence_reasons"):
        _load(raw)


def test_binding_cannot_skip_review_before_promotion() -> None:
    candidate = _load(_binding_mapping())
    promoted = _load(_with_state(_binding_mapping(), "promoted"))

    with pytest.raises(ValueError, match="not allowed"):
        validate_rule_objective_binding_transition(candidate, promoted)


@pytest.mark.parametrize(
    "state",
    [BindingState.CANDIDATE.value, BindingState.RETIRED.value],
)
def test_catalog_requires_reviewed_coverage_for_every_authored_rule(
    tmp_path: Path,
    state: str,
) -> None:
    binding = _with_state(_binding_mapping(), state)
    (tmp_path / "binding.yaml").write_text(
        yaml.safe_dump(binding, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(RuleObjectiveBindingCatalogError, match=_RULE_REF):
        load_rule_objective_binding_catalog(
            tmp_path,
            objective_digests={_OBJECTIVE_REF: _DIGEST_A},
            rule_digests={_RULE_REF: _DIGEST_B},
            rule_implementation_digests={_RULE_REF: _DIGEST_B},
            evidence_refs=frozenset({"evidence.node-pool.topology"}),
            equivalence_receipt_digests={_RECEIPT_REF: _DIGEST_C},
            reviewed_equivalence_receipt_refs=frozenset({_RECEIPT_REF}),
            required_reviewed_rule_refs=frozenset({_RULE_REF}),
        )
