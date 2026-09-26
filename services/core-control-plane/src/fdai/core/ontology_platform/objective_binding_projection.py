"""Read-only projection of exact catalog objective bindings and receipt evidence."""

from __future__ import annotations

from collections.abc import Sequence

from fdai.core.ontology_platform.catalog_projection import CatalogOntologyProjection
from fdai.rule_catalog.schema.control_objective import ControlObjective
from fdai.rule_catalog.schema.equivalence_validation import (
    EquivalenceReceiptState,
    EquivalenceValidationReceipt,
)
from fdai.rule_catalog.schema.rule import rule_content_hash
from fdai.rule_catalog.schema.rule_objective_binding import RuleObjectiveBinding
from fdai.shared.contracts.models import Rule
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord


def build_objective_binding_projection(
    *,
    objectives: Sequence[ControlObjective],
    rules: Sequence[Rule],
    bindings: Sequence[RuleObjectiveBinding],
    receipts: Sequence[EquivalenceValidationReceipt],
) -> CatalogOntologyProjection:
    """Project verified catalog pins; never infer a verdict from a candidate relation."""

    objective_refs = {objective.ref: objective.content_digest for objective in objectives}
    rule_refs = {f"{rule.id}@{rule.version}": (rule.id, rule_content_hash(rule)) for rule in rules}
    receipt_refs = {receipt.ref: receipt for receipt in receipts}
    if len(objective_refs) != len(objectives) or len(rule_refs) != len(rules):
        raise ValueError("objective binding projection has duplicate catalog references")
    if len(receipt_refs) != len(receipts):
        raise ValueError("objective binding projection has duplicate receipt references")

    objects: list[OntologyObjectRecord] = []
    links: list[OntologyLinkRecord] = []
    for receipt in receipts:
        objects.append(
            OntologyObjectRecord(
                id=f"equivalence-validation-receipt:{receipt.ref}",
                object_type="EquivalenceValidationReceipt",
                properties={
                    "id": f"equivalence-validation-receipt:{receipt.ref}",
                    "version": receipt.version,
                    "result": receipt.result.value,
                    "reviewer": receipt.reviewer,
                    "state": receipt.state.value,
                    "content_digest": receipt.content_digest,
                },
            )
        )
    for binding in bindings:
        if objective_refs.get(binding.objective.ref) != binding.objective.content_digest:
            raise ValueError("objective binding references an unprojected objective")
        rule_pin = rule_refs.get(binding.rule.ref)
        if rule_pin is None or rule_pin[1] != binding.rule.content_digest:
            raise ValueError("objective binding references an unprojected Rule version")
        binding_id = f"rule-objective-binding:{binding.ref}"
        objects.append(
            OntologyObjectRecord(
                id=binding_id,
                object_type="RuleObjectiveBinding",
                properties={
                    "id": binding_id,
                    "version": binding.version,
                    "relationship": binding.relationship.value,
                    "implementation_signature_digest": binding.implementation_signature_digest,
                    "evidence_signature_digest": binding.evidence_signature_digest,
                    "state": binding.state.value,
                    "content_digest": binding.content_digest,
                },
            )
        )
        links.extend(
            (
                OntologyLinkRecord(
                    from_id=f"control-objective:{binding.objective.ref}",
                    link_type="objective_bound_by",
                    to_id=binding_id,
                ),
                OntologyLinkRecord(
                    from_id=binding_id,
                    link_type="binding_targets_rule",
                    to_id=rule_pin[0],
                ),
            )
        )
        if binding.equivalence_receipt is not None:
            bound_receipt = receipt_refs.get(binding.equivalence_receipt.ref)
            if (
                bound_receipt is None
                or bound_receipt.content_digest != binding.equivalence_receipt.content_digest
                or bound_receipt.state is not EquivalenceReceiptState.REVIEWED
            ):
                raise ValueError("objective binding references an unprojected receipt")
            links.append(
                OntologyLinkRecord(
                    from_id=binding_id,
                    link_type="binding_validated_by",
                    to_id=f"equivalence-validation-receipt:{binding.equivalence_receipt.ref}",
                )
            )
    if len({item.id for item in objects}) != len(objects):
        raise ValueError("objective binding projection has duplicate object identities")
    return CatalogOntologyProjection(
        objects=tuple(sorted(objects, key=lambda item: item.id)),
        links=tuple(sorted(links, key=lambda item: (item.from_id, item.link_type, item.to_id))),
    )
