from __future__ import annotations

from copy import deepcopy

import pytest
from fdai.rule_catalog.schema.control_objective import (
    ControlObjective,
    ControlObjectiveCatalogError,
    control_objective_content_hash,
    load_control_objective_from_mapping,
    validate_control_objective_transition,
)

_DIGEST_ZERO = f"sha256:{'0' * 64}"


def _objective_mapping() -> dict[str, object]:
    raw: dict[str, object] = {
        "schema_version": "1.0.0",
        "id": "reliability.node-pool.zone-failure-tolerance",
        "version": "1.0.0",
        "title": "Node pool remains available after one zone failure",
        "description": "Preserve node-pool availability after one zone becomes unavailable.",
        "operating_domain": "resilience",
        "protected_outcome_refs": ["outcome.availability"],
        "applicable_ontology": {
            "object_type": "Resource",
            "resource_types": ["kubernetes-node-pool"],
            "property_refs": ["property.kubernetes-node-pool.availability_zones"],
        },
        "predicate_family": "availability_zone_count >= minimum_zone_count",
        "state": "candidate",
        "semantic_surface_refs": [],
        "content_digest": _DIGEST_ZERO,
        "provenance": {
            "source_url": "https://github.com/dotnetpower/fdai",
            "resolved_ref": (
                "control-objective:reliability.node-pool.zone-failure-tolerance@1.0.0"
            ),
            "content_hash": _DIGEST_ZERO,
            "license": "MIT",
            "retrieved_at": "2026-08-13T00:00:00Z",
        },
    }
    draft = ControlObjective.model_validate(raw)
    digest = control_objective_content_hash(draft)
    raw["content_digest"] = digest
    provenance = raw["provenance"]
    assert isinstance(provenance, dict)
    provenance["content_hash"] = digest
    return raw


def _load(raw: dict[str, object]) -> ControlObjective:
    return load_control_objective_from_mapping(
        raw,
        operating_domains=frozenset({"resilience"}),
        object_type_names=frozenset({"Resource"}),
        resource_type_ids=frozenset({"kubernetes-node-pool"}),
        property_refs=frozenset({"property.kubernetes-node-pool.availability_zones"}),
    )


def test_valid_control_objective_is_digest_pinned_and_candidate_only() -> None:
    objective = _load(_objective_mapping())

    assert objective.ref == "reliability.node-pool.zone-failure-tolerance@1.0.0"
    assert objective.content_digest == control_objective_content_hash(objective)
    assert objective.provenance.content_hash == objective.content_digest


@pytest.mark.parametrize("field", ["effect", "enforcement", "approval", "execution_authority"])
def test_control_objective_rejects_authority_fields(field: str) -> None:
    raw = _objective_mapping()
    raw[field] = "forbidden"

    with pytest.raises(ControlObjectiveCatalogError, match="Extra inputs are not permitted"):
        _load(raw)


def test_control_objective_rejects_digest_drift_and_unknown_refs_together() -> None:
    raw = deepcopy(_objective_mapping())
    raw["description"] = "Changed without refreshing the digest."
    applicable = raw["applicable_ontology"]
    assert isinstance(applicable, dict)
    applicable["resource_types"] = ["unknown-resource"]

    with pytest.raises(ControlObjectiveCatalogError) as raised:
        _load(raw)

    messages = " ".join(issue.message for issue in raised.value.issues)
    assert "unknown resource type" in messages
    assert "content_digest mismatch" in messages
    assert "provenance.content_hash mismatch" in messages


def test_control_objective_lifecycle_rejects_review_bypass() -> None:
    previous = _load(_objective_mapping())
    promoted_raw = _objective_mapping()
    promoted_raw["state"] = "promoted"
    promoted_draft = ControlObjective.model_validate(promoted_raw)
    digest = control_objective_content_hash(promoted_draft)
    promoted_raw["content_digest"] = digest
    provenance = promoted_raw["provenance"]
    assert isinstance(provenance, dict)
    provenance["content_hash"] = digest
    promoted = _load(promoted_raw)

    with pytest.raises(ValueError, match="candidate.*promoted"):
        validate_control_objective_transition(previous, promoted)
