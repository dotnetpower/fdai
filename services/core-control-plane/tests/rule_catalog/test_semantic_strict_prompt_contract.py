"""Exact prompt contracts for strict ontology assurance operation families."""

from pathlib import Path

from fdai.core.prompts.registry import FileSystemPromptRegistry

_CATALOG = Path(__file__).resolve().parents[4] / "rule-catalog"


def test_semantic_frame_pins_strict_operation_shapes() -> None:
    frame = FileSystemPromptRegistry(_CATALOG).get_base("semantic.query.frame")

    assert frame.version == 8
    assert 'subject_constraints ["LinkType"]' in frame.body
    assert 'measure_concepts ["type"]' in frame.body
    assert 'output_shape causal_evidence and subject_constraints ["Resource"]' in frame.body
    assert 'output_shape evidence_validation and subject_constraints ["Resource"]' in frame.body


def test_semantic_plan_pins_exact_resource_type_predicate() -> None:
    plan = FileSystemPromptRegistry(_CATALOG).get_base("semantic.query.plan")

    assert plan.version == 10
    assert 'predicate exactly {"property":"type","operator":"exists"}' in plan.body
    assert "never resource_type, object_type, properties.type" in plan.body
