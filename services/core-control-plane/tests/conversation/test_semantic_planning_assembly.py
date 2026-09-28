"""Typed frame and plan prompt assembly keys."""

from __future__ import annotations

from types import SimpleNamespace

from fdai.core.conversation.semantic_planning_assembly import (
    frame_assembly_keys,
    frame_result_keys,
    plan_assembly_keys,
)


def test_frame_keys_come_only_from_accepted_judgment_intents() -> None:
    assert frame_assembly_keys(None) is None
    assert frame_assembly_keys({"primary_intent": "Not A Token"}) is None
    assert frame_assembly_keys(
        {"primary_intent": "query.manifest", "secondary_intents": ["query.ontology_declaration"]}
    ) == ("intent:query.manifest", "intent:query.ontology_declaration")


def test_plan_keys_bind_the_verified_frame_shape() -> None:
    frame = SimpleNamespace(output_shape=SimpleNamespace(value="ontology_manifest"))

    assert plan_assembly_keys(frame) == ("shape:ontology_manifest",)  # type: ignore[arg-type]


def test_frame_result_keys_name_the_proposed_shape() -> None:
    assert frame_result_keys({"output_shape": "causal_evidence"}) == ("shape:causal_evidence",)
    assert frame_result_keys({"output_shape": None}) == ()
