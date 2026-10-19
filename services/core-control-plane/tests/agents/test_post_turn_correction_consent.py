from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.agents._framework.bragi_publication import _publication_key
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.bragi import Bragi
from fdai.agents.norns import Norns
from fdai.core.learning import PostTurnReviewInput, review_input_to_mapping
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.user_context import UserPreferenceRecord
from fdai_service_contracts.post_turn_review import (
    PostTurnReviewInputWire,
    post_turn_review_event_payload,
)

_NOW = datetime(2026, 10, 19, tzinfo=UTC)
_PRINCIPAL_SCOPE = f"sha256:{hashlib.sha256(b'alice').hexdigest()}"
_CORRECTION = "Use the bounded observation window instead."


class _Coordinator:
    def __init__(self) -> None:
        self.inputs: list[PostTurnReviewInput] = []

    async def review(self, review_input: PostTurnReviewInput) -> None:
        self.inputs.append(review_input)


def _review(body_mode: str = "complete") -> PostTurnReviewInput:
    return PostTurnReviewInput(
        review_id="review-correction",
        principal_scope=_PRINCIPAL_SCOPE,
        operator_turn_id="turn-operator",
        assistant_turn_id="turn-assistant",
        completed_at=_NOW,
        operator_body=None if body_mode == "none" else "Inspect the bounded evidence.",
        assistant_body="The inspection completed." if body_mode == "complete" else None,
        explicit_corrections=(_CORRECTION,),
        evidence_refs=("audit:1",),
        validation_outcomes=("verified",),
        failure_recovered=True,
        procedure_fingerprint="procedure:1",
        repeated_procedure_count=3,
    )


def _preference(consent: str = "enabled") -> UserPreferenceRecord | None:
    if consent == "missing":
        return None
    return UserPreferenceRecord(
        principal_id="bob" if consent == "mismatched" else "alice",
        share_with_learner=consent != "disabled",
        revision=7,
        updated_at=_NOW,
    )


def _pipeline() -> tuple[InMemoryBus, Bragi, Norns, _Coordinator]:
    bus = InMemoryBus(registry=load_pantheon())
    coordinator = _Coordinator()
    bragi = Bragi()
    norns = Norns(post_turn_review=coordinator)  # type: ignore[arg-type]
    bragi.bind_bus(bus)
    bus.subscribe("object.post-turn-review", "Norns", norns.on_typed_message)
    return bus, bragi, norns, coordinator


@pytest.mark.parametrize("body_mode", ["none", "partial", "complete"])
@pytest.mark.parametrize("consent", ["missing", "disabled", "mismatched"])
async def test_bragi_strips_corrections_without_matching_consent(
    body_mode: str, consent: str
) -> None:
    bus, bragi, _norns, coordinator = _pipeline()
    review = _review(body_mode)

    assert await bragi.publish_post_turn_review(review, preference=_preference(consent))

    expected = replace(review, operator_body=None, assistant_body=None, explicit_corrections=())
    payload = bus.messages_on("object.post-turn-review")[0].payload
    assert payload["review"] == review_input_to_mapping(expected)
    assert "body_consent" not in payload
    assert coordinator.inputs == [expected]
    assert review.explicit_corrections == (_CORRECTION,)


@pytest.mark.parametrize("body_mode", ["none", "partial"])
async def test_norns_rejects_correction_text_without_complete_bodies(body_mode: str) -> None:
    _bus, _bragi, norns, coordinator = _pipeline()
    review = _review(body_mode)

    await norns.on_typed_message(
        "object.post-turn-review",
        {
            "producer_principal": "Bragi",
            "kind": "post_turn_review",
            "review": review_input_to_mapping(review),
        },
    )

    assert coordinator.inputs == []
    assert norns.behavior_snapshot()["post_turn_review_raw_body_incomplete"] == 1


@pytest.mark.parametrize(
    "corrections",
    [
        ("user@example.com", _CORRECTION),
        (_CORRECTION, "user@example.com"),
    ],
)
async def test_norns_scans_every_consented_correction(
    corrections: tuple[str, ...],
) -> None:
    _bus, bragi, norns, coordinator = _pipeline()
    review = replace(_review(), explicit_corrections=corrections)

    assert await bragi.publish_post_turn_review(review, preference=_preference())

    assert coordinator.inputs == []
    assert norns.behavior_snapshot()["post_turn_review_raw_body_sensitive"] == 1


@pytest.mark.parametrize("delta", [-1, 0, 1])
@pytest.mark.parametrize("multibyte", [False, True])
async def test_norns_bounds_combined_body_and_correction_bytes(delta: int, multibyte: bool) -> None:
    _bus, bragi, norns, coordinator = _pipeline()
    chunk = "가" * 5_000 if multibyte else "x" * 15_000
    corrections = (chunk,) * 4 + ("y" * (5_528 + delta),)
    review = replace(
        _review(), operator_body="O", assistant_body="A", explicit_corrections=corrections
    )
    assert len("\n".join(("O", "A", *corrections)).encode("utf-8")) == 64 * 1024 + delta

    assert await bragi.publish_post_turn_review(review, preference=_preference())

    if delta <= 0:
        assert coordinator.inputs == [review]
    else:
        assert coordinator.inputs == []
        assert norns.behavior_snapshot()["post_turn_review_raw_body_too_large"] == 1


async def test_consented_corrections_reach_norns_once_without_mutation_authority() -> None:
    bus, bragi, norns, coordinator = _pipeline()
    review = _review()

    assert await bragi.publish_post_turn_review(review, preference=_preference())
    assert await bragi.publish_post_turn_review(review, preference=_preference())

    assert coordinator.inputs == [review]
    assert norns.behavior_snapshot()["post_turn_review_duplicate"] == 1
    assert norns.pending_candidates == []
    assert {message.topic for message in bus.published} == {"object.post-turn-review"}
    assert bus.messages_on("object.post-turn-review")[0].payload["body_consent"] == {
        "share_with_learner": True,
        "principal_scope": _PRINCIPAL_SCOPE,
        "consent_ref": f"user-preference:{_PRINCIPAL_SCOPE}:7",
    }


@pytest.mark.parametrize("body_mode", ["none", "partial", "complete"])
async def test_unconsented_corrections_are_removed_before_checkpoint_and_restart(
    body_mode: str,
) -> None:
    store = InMemoryStateStore()
    checkpoint = Bragi(state_store=store, clock=lambda: _NOW)
    review = _review(body_mode)
    expected = replace(review, operator_body=None, assistant_body=None, explicit_corrections=())
    payload = post_turn_review_event_payload(
        PostTurnReviewInputWire.model_validate(review_input_to_mapping(expected))
    )

    assert await checkpoint.publish_post_turn_review(review) is False
    row = await store.read_state(_publication_key(payload))
    assert row is not None
    assert row["payload"] == payload

    bus, _bragi, _norns, coordinator = _pipeline()
    restarted = Bragi(state_store=store, clock=lambda: _NOW)
    restarted.bind_bus(bus)
    assert await restarted.recover_bragi_publications() == 1
    assert coordinator.inputs == [expected]
    assert bus.messages_on("object.post-turn-review")[0].payload == {
        **payload,
        "schema_version": 1,
        "envelope_schema_version": 1,
    }


@pytest.mark.parametrize("body_mode", ["none", "partial", "complete"])
@pytest.mark.parametrize("consent", ["missing", "mismatched", "disabled", "numeric"])
async def test_legacy_outbox_never_republishes_corrections_without_matching_consent(
    body_mode: str, consent: str
) -> None:
    store = InMemoryStateStore()
    review = _review(body_mode)
    payload = post_turn_review_event_payload(
        PostTurnReviewInputWire.model_validate(review_input_to_mapping(review))
    )
    if consent != "missing":
        payload["body_consent"] = {
            "share_with_learner": {"disabled": False, "numeric": 1}.get(consent, True),
            "principal_scope": "principal-other" if consent == "mismatched" else _PRINCIPAL_SCOPE,
            "consent_ref": "user-preference:7",
        }
    key = _publication_key(payload)
    await store.write_state(
        key,
        {
            "schema_version": "1.0.0",
            "revision": 1,
            "status": "pending",
            "topic": "object.post-turn-review",
            "correlation_id": review.review_id,
            "idempotency_key": payload["idempotency_key"],
            "payload": payload,
        },
    )
    bus, _bragi, _norns, coordinator = _pipeline()
    restarted = Bragi(state_store=store, clock=lambda: _NOW)
    restarted.bind_bus(bus)
    safe_review = replace(
        review,
        review_id="review-safe",
        operator_body=None,
        assistant_body=None,
        explicit_corrections=(),
    )
    assert (
        await Bragi(state_store=store, clock=lambda: _NOW).publish_post_turn_review(safe_review)
        is False
    )

    assert await restarted.recover_bragi_publications() == 1

    assert len(bus.published) == 1
    assert coordinator.inputs == [safe_review]
    row = await store.read_state(key)
    assert row is not None
    assert row["status"] == "pending"
    assert row["payload"] == payload
    behavior = restarted.behavior_snapshot()
    assert (
        behavior.get("publication_outbox:recovery_missing_body_consent", 0)
        + behavior.get("publication_outbox:recovery_publish_failed", 0)
    ) == 1


async def test_consented_correction_outbox_recovery_preserves_the_recorded_proof() -> None:
    store = InMemoryStateStore()
    review = _review()
    checkpoint = Bragi(state_store=store, clock=lambda: _NOW)
    assert await checkpoint.publish_post_turn_review(review, preference=_preference()) is False
    bus, _bragi, _norns, coordinator = _pipeline()
    restarted = Bragi(state_store=store, clock=lambda: _NOW)
    restarted.bind_bus(bus)

    assert await restarted.recover_bragi_publications() == 1

    assert coordinator.inputs == [review]
    assert bus.messages_on("object.post-turn-review")[0].payload["body_consent"] == {
        "share_with_learner": True,
        "principal_scope": _PRINCIPAL_SCOPE,
        "consent_ref": f"user-preference:{_PRINCIPAL_SCOPE}:7",
    }
