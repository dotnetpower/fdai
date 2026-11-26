"""Model-proposed canonical values on collection filters never void a valid route."""

from __future__ import annotations

from fdai.core.conversation.conversation_preflight import (
    ConversationPreflightProposal,
    ConversationPreflightResult,
    preflight_operational_judgment,
)
from fdai.core.conversation.conversation_preflight_validation import preflight_input_digest
from fdai_service_contracts.ontology_query import content_digest


def test_collection_filter_canonical_value_is_dropped_not_rejected() -> None:
    utterance = "중지된 VM 있어?"
    proposal = ConversationPreflightProposal.model_validate(
        {
            "social_act": "none",
            "operational_signal": "explicit",
            "context_dependency": "none",
            "operational_family": "resource_collection",
            "operational_targets": [
                {
                    "kind": "resource_state_filter",
                    "value": "중지된",
                    "canonical_value": "stopped",
                    "source_start": 0,
                    "source_end": 3,
                },
                {
                    "kind": "resource_type_filter",
                    "value": "VM",
                    "canonical_value": None,
                    "source_start": 4,
                    "source_end": 6,
                },
            ],
            "operational_facets": ["resource_collection", "list", "current_state"],
            "confidence": 0.95,
        }
    )

    judgment = preflight_operational_judgment(
        ConversationPreflightResult(
            proposal=proposal,
            attempted=True,
            input_digest=preflight_input_digest(utterance),
            proposal_digest=content_digest(proposal.model_dump(mode="json")),
            model_config_digest="sha256:" + "a" * 64,
            prompt_digest="sha256:" + "b" * 64,
        ),
        utterance=utterance,
        allow_resource_collection=True,
    )

    assert judgment is not None
    assert all(target.canonical_value is None for target in judgment.targets)
    assert {target.kind for target in judgment.targets} >= {"resource_state_filter"}
