from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fdai.agents import PantheonRuntime
from fdai.runtime.bootstrap_bragi_intent_training import (
    build_bragi_intent_training_batch,
    run_bragi_intent_training_batch,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "source_revision": "a" * 40,
        "batch_ref": "bragi-training:reviewed:1",
        "evaluator_principal_digest": "sha256:" + "b" * 64,
        "review": {
            "review_id": "review-bragi-training-1",
            "reviewer_principal_digest": "sha256:" + "c" * 64,
            "approval_ref": "approval:bragi-training:1",
        },
        "corpus": [
            {
                "evidence_id": "holdout-1",
                "source_kind": "post_turn_review_correction",
                "principal_scope_digest": "sha256:" + "1" * 64,
                "consent_ref": "preference:holdout-1:share-with-learner",
                "input_digest": "sha256:" + "2" * 64,
                "baseline_owner": "Njord",
                "corrected_owner": "Njord",
                "baseline_intent": "cost_breakdown",
                "corrected_intent": "cost_breakdown",
                "corrected_object_type": None,
                "targeted": False,
                "evidence_refs": ["audit:holdout-1"],
            },
            {
                "evidence_id": "target-1",
                "source_kind": "human_resolved_abstention",
                "principal_scope_digest": "sha256:" + "3" * 64,
                "consent_ref": "preference:target-1:share-with-learner",
                "input_digest": "sha256:" + "4" * 64,
                "baseline_owner": None,
                "corrected_owner": "Njord",
                "baseline_intent": None,
                "corrected_intent": "cost_breakdown",
                "corrected_object_type": None,
                "targeted": True,
                "evidence_refs": ["audit:target-1"],
            },
        ],
        "evaluation_results": [
            {
                "evidence_id": "holdout-1",
                "baseline_owner": "Njord",
                "candidate_owner": "Njord",
                "expected_owner": "Njord",
            },
            {
                "evidence_id": "target-1",
                "baseline_owner": None,
                "candidate_owner": "Njord",
                "expected_owner": "Njord",
            },
        ],
    }


def _write(path: Path, payload: dict[str, object]) -> str:
    content = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


async def test_reviewed_batch_runs_once_as_shadow_only_evidence(tmp_path: Path) -> None:
    path = tmp_path / "bragi-training.json"
    digest = _write(path, _manifest())
    batch = build_bragi_intent_training_batch(
        {
            "FDAI_BRAGI_INTENT_TRAINING_EVIDENCE_PATH": str(path),
            "FDAI_BRAGI_INTENT_TRAINING_EVIDENCE_SHA256": digest,
            "FDAI_SOURCE_REVISION": "a" * 40,
        }
    )
    assert batch is not None
    store = InMemoryStateStore()
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events.bragi-training-test",
        bragi_state_store=store,
        conversation_intent_training_evaluator=batch,
    )

    run = await run_bragi_intent_training_batch(runtime, batch)

    assert run.gate_passed is True
    assert run.payload["stages"]["promotion_decision"]["status"] == "shadow_ready"
    assert run.payload["stages"]["promotion_decision"]["activation_authority"] is False
    assert run.payload["authority"]["routes_runtime_traffic"] is False
    assert len(await store.read_states("pantheon/bragi/intent-training/", limit=20)) == 4


@pytest.mark.parametrize("mutation", ["digest", "revision", "same_principal", "unknown_field"])
def test_reviewed_batch_rejects_changed_or_nonindependent_evidence(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = _manifest()
    if mutation == "same_principal":
        payload["review"]["reviewer_principal_digest"] = payload["evaluator_principal_digest"]  # type: ignore[index]
    elif mutation == "unknown_field":
        payload["execution_authority"] = True
    path = tmp_path / "bragi-training.json"
    digest = _write(path, payload)
    environment = {
        "FDAI_BRAGI_INTENT_TRAINING_EVIDENCE_PATH": str(path),
        "FDAI_BRAGI_INTENT_TRAINING_EVIDENCE_SHA256": "f" * 64 if mutation == "digest" else digest,
        "FDAI_SOURCE_REVISION": "d" * 40 if mutation == "revision" else "a" * 40,
    }
    with pytest.raises(RuntimeError):
        build_bragi_intent_training_batch(environment)


@pytest.mark.parametrize("missing", ["path", "digest"])
def test_partial_bragi_training_configuration_fails_closed(tmp_path: Path, missing: str) -> None:
    environment = {
        "FDAI_BRAGI_INTENT_TRAINING_EVIDENCE_PATH": str(tmp_path / "bragi-training.json"),
        "FDAI_BRAGI_INTENT_TRAINING_EVIDENCE_SHA256": "a" * 64,
    }
    environment.pop(
        "FDAI_BRAGI_INTENT_TRAINING_EVIDENCE_PATH"
        if missing == "path"
        else "FDAI_BRAGI_INTENT_TRAINING_EVIDENCE_SHA256"
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        build_bragi_intent_training_batch(environment)


def test_absent_bragi_training_configuration_stays_unbound() -> None:
    assert build_bragi_intent_training_batch({}) is None
