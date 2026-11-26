"""The default runtime accepts only canonical closed non-executable document intent envelopes."""

from __future__ import annotations

import json
import runpy
from copy import deepcopy
from pathlib import Path

import pytest
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime_payload_validation import default_payload_validator
from fdai_service_contracts.document_intent import (
    INTENT_OWNERS,
    DocumentIntentApproval,
    DocumentIntentEvent,
)
from fdai_service_contracts.ontology_query import content_digest

DIGEST = "sha256:" + "a" * 64


def event(phase="reviewed"):
    kwargs = {}
    if phase in {"applied", "verified", "verified_sealed", "rolled_back", "recovery_held"}:
        kwargs["applied_revision"] = 1
    if phase in {"verified", "verified_sealed"}:
        kwargs["outcome"] = "matched"
    elif phase == "rolled_back":
        kwargs["outcome"] = "rolled_back"
    elif phase in {"held", "recovery_held", "arbitration_requested", "arbitrated"}:
        kwargs["outcome"] = "mismatched"
    return DocumentIntentEvent.create(phase, DIGEST, "wire-test", **kwargs)


def approval():
    return {
        "kind": "document_intent_projection",
        "producer_principal": "Var",
        "correlation_id": "wire-test",
        "idempotency_key": "approval-final:" + "b" * 64,
        "action_idempotency_key": "sha256:" + "c" * 64,
        "action_type": "document.review-intent-diff",
        "resource_id": "document-intent:" + DIGEST[7:],
        "state": "approved",
        "approvers": ["human:reviewer"],
        "original_quorum_required": 1,
        "effective_quorum_required": 1,
        "params": {"intent_digest": DIGEST},
    }


@pytest.mark.parametrize("phase", tuple(INTENT_OWNERS))
def test_every_owned_phase_passes_default_validator(phase):
    message = event(phase)
    load_pantheon().assert_can_publish(message.producer_principal, message.topic)
    default_payload_validator(message.topic, message.model_dump(mode="json"))


@pytest.mark.parametrize(
    "field", ["execution_authority", "action_type", "source_text", "properties"]
)
@pytest.mark.parametrize("phase", ["reviewed", "rolled_back", "verdict_sealed"])
def test_authority_and_source_content_cannot_be_added_to_owned_envelopes(field, phase):
    message = event(phase)
    body = message.model_dump(mode="json")
    body[field] = True if field == "execution_authority" else "untrusted"
    with pytest.raises(ValueError):
        default_payload_validator(message.topic, body)


@pytest.mark.parametrize(
    "update",
    [
        {"producer_principal": "Thor"},
        {"schema_version": "2.0.0"},
        {"envelope_schema_version": True},
        {"execution_authority": 0},
        {"applied_revision": True},
        {"intent_digest": "sha256:" + "b" * 64},
        {"resource_id": "service:unrelated"},
        {"idempotency_key": "different"},
    ],
)
def test_spliced_event_identity_and_noncanonical_types_are_rejected(update):
    message = event()
    body = message.model_dump(mode="json") | update
    with pytest.raises(ValueError):
        default_payload_validator(message.topic, body)


def test_canonical_event_cannot_select_another_owned_topic():
    with pytest.raises(ValueError, match="canonical owned topic"):
        default_payload_validator("object.rollback", event().model_dump(mode="json"))


@pytest.mark.parametrize(
    ("phase", "outcome", "revision"),
    [
        ("reviewed", "matched", 0),
        ("verified", "pending", 1),
        ("verified_sealed", "matched", 0),
        ("applied", "pending", 0),
        ("rolled_back", "matched", 1),
        ("recovery_held", "mismatched", 0),
    ],
)
def test_phase_state_cannot_be_spliced_even_with_recomputed_content_identity(
    phase, outcome, revision
):
    body = event(phase).model_dump(mode="json")
    body.update(outcome=outcome, applied_revision=revision)
    body["idempotency_key"] = content_digest(
        {
            "phase": phase,
            "intent": DIGEST,
            "correlation": "wire-test",
            "outcome": outcome,
            "revision": revision,
        }
    )
    with pytest.raises(ValueError, match="inconsistent outcome or revision"):
        default_payload_validator(INTENT_OWNERS[phase][1], body)


def test_exact_var_approval_passes_but_cannot_become_an_event_or_action():
    default_payload_validator("object.approval", approval())
    with pytest.raises(ValueError):
        default_payload_validator("object.rule", approval())
    with pytest.raises(ValueError):
        default_payload_validator("object.action-run", event().model_dump(mode="json"))


@pytest.mark.parametrize(
    "update",
    [
        {"producer_principal": "Muninn"},
        {"execution_authority": True},
        {"execution_authority": 0},
        {"action_type": "ops.restart-service"},
        {"action_run_identity": "sha256:" + "d" * 64},
        {"resource_id": "document-intent:" + "b" * 64},
        {"original_quorum_required": True},
        {"effective_quorum_required": 2},
        {"approvers": []},
        {"approvers": ["human:one", "human:two"]},
        {"development_authority": {"enabled": True}},
        {"unknown": "untrusted"},
    ],
)
def test_var_approval_authority_quorum_and_diff_splices_are_rejected(update):
    with pytest.raises(ValueError):
        default_payload_validator("object.approval", approval() | update)


def test_approval_params_are_closed_and_have_no_source_content():
    body = deepcopy(approval())
    body["params"]["source_text"] = "private"
    with pytest.raises(ValueError):
        default_payload_validator("object.approval", body)
    assert DocumentIntentApproval.model_json_schema()["additionalProperties"] is False


def test_generated_schema_resources_match_canonical_sdk_models():
    root = Path(__file__).resolve().parents[4]
    generator = runpy.run_path(
        str(root / "scripts/quality/contracts/generate_document_intent_schemas.py")
    )
    for name, rendered in generator["render_schemas"]().items():
        path = root / "packages/service-contracts/src/fdai_service_contracts/schemas" / name
        assert (path / "1.0.0.json").read_text() == rendered
        assert json.loads(rendered)["additionalProperties"] is False
