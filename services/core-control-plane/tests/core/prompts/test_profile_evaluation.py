"""Exact prompt profile selection and content-free comparison tests."""

from __future__ import annotations

from pathlib import Path

from fdai.core.prompts import FileSystemPromptRegistry, compare_prompt_profiles

_CATALOG = Path(__file__).resolve().parents[5] / "rule-catalog"


def test_active_compact_semantic_profiles_are_smaller_than_dynamic_rollbacks() -> None:
    registry = FileSystemPromptRegistry(_CATALOG)
    rollbacks = {
        "semantic.judgment": "shadow.semantic-judgment-dynamic-v8",
        "semantic.query.frame": "shadow.semantic-query-frame-dynamic-v2",
        "semantic.query.plan": "shadow.semantic-query-plan-dynamic-v2",
    }

    comparisons = {
        capability: compare_prompt_profiles(
            registry,
            capability_id=capability,
            treatment_profile_id=profile_id,
        )
        for capability, profile_id in rollbacks.items()
    }
    compact_judgment = registry.resolve("semantic.judgment")

    assert (
        comparisons["semantic.judgment"].treatment_tokens
        - comparisons["semantic.judgment"].active_tokens
    ) / comparisons["semantic.judgment"].treatment_tokens > 0.3
    assert comparisons["semantic.query.frame"].treatment_tokens > (
        comparisons["semantic.query.frame"].active_tokens * 10
    )
    assert comparisons["semantic.query.plan"].treatment_tokens > (
        comparisons["semantic.query.plan"].active_tokens * 10
    )
    assert compact_judgment.profile is not None
    assert compact_judgment.profile.system_token_budget == 16384
    assert compact_judgment.root.id == "semantic-judgment-common"
    assert tuple(pack.id for pack in compact_judgment.packs) == (
        "semantic-judgment-compact",
        "semantic-incident-action-guidance",
        "semantic-resource-name-filter",
        "semantic-sre-diagnostic",
        "semantic-topic-ontology-schema",
        "semantic-topic-action-request",
        "semantic-topic-conversation",
    )
    assert all(
        comparison.active_profile_digest != comparison.treatment_profile_digest
        for comparison in comparisons.values()
    )
