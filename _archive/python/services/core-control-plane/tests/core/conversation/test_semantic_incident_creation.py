from fdai.core.conversation.semantic_incident_creation import (
    incident_creation_intent_from_judgment,
)
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

DIGEST = "sha256:" + "a" * 64


def _judgment(**overrides: object) -> SemanticJudgmentProposal:
    values: dict[str, object] = {
        "primary_intent": "action_request",
        "requested_facets": ["incident_create", "severity"],
        "targets": [
            {
                "kind": "severity",
                "value": "SEV2",
                "source_start": 0,
                "source_end": 4,
            },
            {
                "kind": "resource",
                "value": "service-api",
                "source_start": 15,
                "source_end": 26,
            },
        ],
        "confidence": 0.98,
        "ambiguous": False,
        "action_posture": "draft_only",
        "action_subject": "Incident",
    }
    values.update(overrides)
    return SemanticJudgmentProposal.model_validate(values)


def test_complete_incident_judgment_becomes_typed_candidate() -> None:
    intent = incident_creation_intent_from_judgment(
        _judgment(),
        source_input_digest=DIGEST,
    )

    assert intent is not None
    assert intent.action_type == "incident.create"
    assert intent.arguments.severity == "sev2"
    assert intent.arguments.target == "service-api"
    assert intent.execution_authority is False


def test_non_incident_draft_does_not_become_incident_candidate() -> None:
    intent = incident_creation_intent_from_judgment(
        _judgment(action_subject="Change", requested_facets=[]),
        source_input_digest=DIGEST,
    )

    assert intent is None
