from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fdai.core.ontology_platform.objective_binding_projection import (
    build_objective_binding_projection,
)
from fdai.rule_catalog.schema.control_objective import (
    ControlObjective,
    load_control_objective_catalog,
)
from fdai.rule_catalog.schema.equivalence_validation import (
    EquivalenceReceiptState,
    EquivalenceValidationReceipt,
    EquivalenceValidationResult,
)
from fdai.rule_catalog.schema.rego_semantics import load_rego_semantics
from fdai.rule_catalog.schema.rule import rule_content_hash
from fdai.rule_catalog.schema.rule_objective_binding import (
    CatalogRecordPin,
    RuleObjectiveBinding,
    load_rule_objective_binding_catalog,
)
from fdai.shared.contracts.models import Rule

ROOT = Path(__file__).resolve().parents[5]
CATALOG = ROOT / "rule-catalog"
EVIDENCE_REF = "property.kubernetes-node-pool.availability_zones"


def _catalog() -> tuple[tuple[ControlObjective, ...], Rule, tuple[RuleObjectiveBinding, ...]]:
    objectives = load_control_objective_catalog(
        CATALOG / "control-objectives",
        operating_domains=frozenset({"reliability"}),
        object_type_names=frozenset({"Resource"}),
        resource_type_ids=frozenset({"kubernetes-node-pool"}),
        property_refs=frozenset({EVIDENCE_REF}),
    )
    rule = Rule.model_validate(
        yaml.safe_load(
            (CATALOG / "catalog/kubernetes-node-pool.multi-zone.yaml").read_text(encoding="utf-8")
        )
    )
    rule_ref = f"{rule.id}@{rule.version}"
    semantics = load_rego_semantics(ROOT / rule.check_logic.reference)
    bindings = load_rule_objective_binding_catalog(
        CATALOG / "rule-objective-bindings",
        objective_digests={item.ref: item.content_digest for item in objectives},
        rule_digests={rule_ref: rule_content_hash(rule)},
        rule_implementation_digests={rule_ref: semantics.normalized_semantic_digest},
        evidence_refs=frozenset({EVIDENCE_REF}),
    )
    return objectives, rule, bindings


def test_projects_candidate_vocabulary_without_authority_or_fabricated_receipts() -> None:
    objectives, rule, bindings = _catalog()
    projection = build_objective_binding_projection(
        objectives=objectives,
        rules=(rule,),
        bindings=bindings,
        receipts=(),
    )
    assert len(projection.objects) == 1
    assert len(projection.links) == 2
    binding = projection.objects[0]
    assert binding.object_type == "RuleObjectiveBinding"
    assert binding.properties["state"] == "candidate"
    assert binding.properties["content_digest"] == bindings[0].content_digest
    assert set(binding.properties) == {
        "id",
        "version",
        "relationship",
        "implementation_signature_digest",
        "evidence_signature_digest",
        "state",
        "content_digest",
    }
    assert {(item.link_type, item.to_id) for item in projection.links} == {
        ("objective_bound_by", binding.id),
        ("binding_targets_rule", rule.id),
    }
    assert projection == build_objective_binding_projection(
        objectives=objectives, rules=(rule,), bindings=bindings, receipts=()
    )


def test_rejects_missing_exact_rule_or_objective_and_unissued_receipt() -> None:
    objectives, rule, bindings = _catalog()
    with pytest.raises(ValueError, match="unprojected Rule version"):
        build_objective_binding_projection(
            objectives=objectives, rules=(), bindings=bindings, receipts=()
        )
    with pytest.raises(ValueError, match="unprojected objective"):
        build_objective_binding_projection(
            objectives=(), rules=(rule,), bindings=bindings, receipts=()
        )
    wrong_objective = bindings[0].model_copy(
        update={
            "objective": CatalogRecordPin(
                ref=bindings[0].objective.ref, content_digest=f"sha256:{'b' * 64}"
            )
        }
    )
    with pytest.raises(ValueError, match="unprojected objective"):
        build_objective_binding_projection(
            objectives=objectives, rules=(rule,), bindings=(wrong_objective,), receipts=()
        )
    wrong_rule = bindings[0].model_copy(
        update={
            "rule": CatalogRecordPin(ref=bindings[0].rule.ref, content_digest=f"sha256:{'b' * 64}")
        }
    )
    with pytest.raises(ValueError, match="unprojected Rule version"):
        build_objective_binding_projection(
            objectives=objectives, rules=(rule,), bindings=(wrong_rule,), receipts=()
        )
    fabricated = bindings[0].model_copy(
        update={
            "equivalence_receipt": CatalogRecordPin(
                ref="equivalence.unissued@1.0.0",
                content_digest=f"sha256:{'a' * 64}",
            )
        }
    )
    with pytest.raises(ValueError, match="unprojected receipt"):
        build_objective_binding_projection(
            objectives=objectives, rules=(rule,), bindings=(fabricated,), receipts=()
        )


def test_projects_only_reviewed_receipt_fields_on_a_bound_exact_pin() -> None:
    objectives, rule, bindings = _catalog()
    receipt = EquivalenceValidationReceipt.model_construct(
        id="equivalence.example",
        version="1.0.0",
        result=EquivalenceValidationResult.VALIDATED,
        reviewer="Heimdall",
        state=EquivalenceReceiptState.REVIEWED,
        content_digest=f"sha256:{'a' * 64}",
    )
    binding = bindings[0].model_copy(
        update={
            "equivalence_receipt": CatalogRecordPin(
                ref=receipt.ref,
                content_digest=receipt.content_digest,
            )
        }
    )
    projection = build_objective_binding_projection(
        objectives=objectives, rules=(rule,), bindings=(binding,), receipts=(receipt,)
    )
    receipt_record = next(
        item for item in projection.objects if item.object_type == "EquivalenceValidationReceipt"
    )
    assert set(receipt_record.properties) == {
        "id",
        "version",
        "result",
        "reviewer",
        "state",
        "content_digest",
    }
    assert (
        binding.ref,
        receipt.ref,
    ) == (
        projection.links[-1].from_id.removeprefix("rule-objective-binding:"),
        projection.links[-1].to_id.removeprefix("equivalence-validation-receipt:"),
    )
    with pytest.raises(ValueError, match="unprojected receipt"):
        build_objective_binding_projection(
            objectives=objectives,
            rules=(rule,),
            bindings=(binding,),
            receipts=(receipt.model_copy(update={"state": EquivalenceReceiptState.CANDIDATE}),),
        )
