"""Current-admission gating for deployment-owned operating-intent authority."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.operational_context import (
    MAX_ADMITTED_OBJECT_IDS,
    OPERATING_INTENT_SOURCE_ADMISSION_KEY,
    OperatingIntentAdmissionExpectation,
    OperatingIntentAdmissionStatus,
    StateStoreOperatingIntentAdmissionReader,
    evaluate_operating_intent_admission,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)
_DIGEST = f"sha256:{'a' * 64}"
_OTHER_DIGEST = f"sha256:{'b' * 64}"
_EXPECTATION = OperatingIntentAdmissionExpectation(
    expected_revision="operating-intent-revision-1",
    expected_sha256=_DIGEST,
    generation=2,
)


def _admitted(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": "1.1.0",
        "status": "admitted",
        "binding_generation": 2,
        "source_revision": "operating-intent-revision-1",
        "snapshot_digest": _DIGEST,
        "owned_object_ids": ["generic-change-window"],
        "validated_at": (_NOW - timedelta(minutes=1)).isoformat(),
        "max_age_seconds": 900,
    }
    record.update(overrides)
    return record


def test_unconfigured_consumer_keeps_generic_behavior_without_an_ownership_fence() -> None:
    """No configured binding means this graph is not governed by an intent source."""

    admission = evaluate_operating_intent_admission(None, now=_NOW, expectation=None)

    assert admission.status is OperatingIntentAdmissionStatus.UNBOUND
    assert admission.grants_intent_authority is True
    assert admission.owned_object_ids is None


def test_absent_record_denies_for_a_configured_consumer() -> None:
    """A deleted, corrupted, or not-yet-written record proves nothing."""

    admission = evaluate_operating_intent_admission(None, now=_NOW, expectation=_EXPECTATION)

    assert admission.status is OperatingIntentAdmissionStatus.UNAVAILABLE
    assert admission.grants_intent_authority is False


def test_unconfigured_record_denies_for_a_configured_consumer() -> None:
    """The writer says nothing is bound while this consumer pins a source: deny."""

    admission = evaluate_operating_intent_admission(
        {"schema_version": "1.0.0", "status": "unconfigured"},
        now=_NOW,
        expectation=_EXPECTATION,
    )

    assert admission.status is OperatingIntentAdmissionStatus.BINDING_MISMATCH
    assert admission.grants_intent_authority is False


def test_current_admission_grants_and_carries_pinned_identity_and_ownership() -> None:
    admission = evaluate_operating_intent_admission(_admitted(), now=_NOW, expectation=_EXPECTATION)

    assert admission.status is OperatingIntentAdmissionStatus.ADMITTED
    assert admission.grants_intent_authority is True
    assert admission.source_revision == "operating-intent-revision-1"
    assert admission.snapshot_digest == _DIGEST
    assert admission.generation == 2
    assert admission.owned_object_ids == frozenset({"generic-change-window"})


def test_admission_expires_without_revalidation() -> None:
    """An old proof is not a current one, even though its status still reads admitted."""

    admission = evaluate_operating_intent_admission(
        _admitted(),
        now=_NOW + timedelta(seconds=901),
        expectation=_EXPECTATION,
    )

    assert admission.status is OperatingIntentAdmissionStatus.EXPIRED
    assert admission.grants_intent_authority is False


def test_quarantined_and_unavailable_deny() -> None:
    for status, expected in (
        ("quarantined", OperatingIntentAdmissionStatus.QUARANTINED),
        ("unavailable", OperatingIntentAdmissionStatus.UNAVAILABLE),
    ):
        admission = evaluate_operating_intent_admission(
            {
                "schema_version": "1.1.0",
                "status": status,
                "binding_generation": 2,
                "reason": "source is not currently effective (stale)",
                "validated_at": _NOW.isoformat(),
            },
            now=_NOW,
            expectation=_EXPECTATION,
        )

        assert admission.status is expected
        assert admission.grants_intent_authority is False
        assert admission.reason == "source is not currently effective (stale)"


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_revision": "operating-intent-revision-0"},
        {"snapshot_digest": _OTHER_DIGEST},
        {"binding_generation": 1},
        {"binding_generation": 3},
    ],
)
def test_a_foreign_binding_or_generation_denies(overrides: dict[str, object]) -> None:
    """A syntactically valid record from another binding is not this consumer's proof.

    The two ``binding_generation`` cases are the rolling-deployment fence in both
    directions: an old replica's record must not authorize the new rollout, and the
    new rollout's record must not authorize an old replica reading a graph it never
    validated.
    """

    admission = evaluate_operating_intent_admission(
        _admitted(**overrides), now=_NOW, expectation=_EXPECTATION
    )

    assert admission.status is OperatingIntentAdmissionStatus.BINDING_MISMATCH
    assert admission.grants_intent_authority is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "projected"},
        {"source_revision": ""},
        {"snapshot_digest": "not-a-digest"},
        {"snapshot_digest": f"sha256:{'g' * 64}"},
        {"binding_generation": 0},
        {"binding_generation": True},
        {"binding_generation": "2"},
        {"owned_object_ids": None},
        {"owned_object_ids": "generic-change-window"},
        {"owned_object_ids": ["generic-change-window", ""]},
        {"owned_object_ids": [1]},
        {"owned_object_ids": ["x"] * (MAX_ADMITTED_OBJECT_IDS + 1)},
        {"validated_at": "not-a-timestamp"},
        {"validated_at": "2026-08-27T12:00:00"},
        {"validated_at": (_NOW + timedelta(seconds=1)).isoformat()},
        {"max_age_seconds": 0},
        {"max_age_seconds": 86_401},
        {"max_age_seconds": True},
    ],
)
def test_malformed_admission_denies(overrides: dict[str, object]) -> None:
    admission = evaluate_operating_intent_admission(
        _admitted(**overrides), now=_NOW, expectation=_EXPECTATION
    )

    assert admission.status is OperatingIntentAdmissionStatus.MALFORMED
    assert admission.grants_intent_authority is False


def test_an_admission_may_own_nothing() -> None:
    """An empty ownership set is a real answer: it vouches for no window at all."""

    admission = evaluate_operating_intent_admission(
        _admitted(owned_object_ids=[]), now=_NOW, expectation=_EXPECTATION
    )

    assert admission.status is OperatingIntentAdmissionStatus.ADMITTED
    assert admission.owned_object_ids == frozenset()


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_operating_intent_admission(
            _admitted(), now=datetime(2026, 8, 27, 12), expectation=_EXPECTATION
        )


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"expected_revision": " "}, "non-empty"),
        ({"expected_sha256": "not-a-digest"}, "SHA-256"),
        ({"expected_sha256": f"sha256:{'g' * 64}"}, "SHA-256"),
        ({"generation": 0}, ">= 1"),
        ({"generation": True}, "integer"),
    ],
)
def test_expectation_rejects_an_unusable_binding(kwargs: dict[str, object], match: str) -> None:
    fields: dict[str, object] = {
        "expected_revision": "operating-intent-revision-1",
        "expected_sha256": _DIGEST,
        "generation": 2,
    }
    fields.update(kwargs)

    with pytest.raises(ValueError, match=match):
        OperatingIntentAdmissionExpectation(**fields)  # type: ignore[arg-type]


async def test_state_store_reader_resolves_the_durable_record() -> None:
    store = InMemoryStateStore()
    await store.write_state(OPERATING_INTENT_SOURCE_ADMISSION_KEY, _admitted())

    admission = await StateStoreOperatingIntentAdmissionReader(
        store, expectation=_EXPECTATION
    ).resolve(now=_NOW)

    assert admission.status is OperatingIntentAdmissionStatus.ADMITTED


async def test_state_store_reader_denies_when_the_record_is_gone() -> None:
    """The record the consumer depends on is missing; nothing currently vouches."""

    admission = await StateStoreOperatingIntentAdmissionReader(
        InMemoryStateStore(), expectation=_EXPECTATION
    ).resolve(now=_NOW)

    assert admission.status is OperatingIntentAdmissionStatus.UNAVAILABLE
    assert admission.grants_intent_authority is False


async def test_an_unconfigured_reader_ignores_a_foreign_record() -> None:
    """Generic compatibility comes from explicit configuration, never from a stray row."""

    store = InMemoryStateStore()
    await store.write_state(
        OPERATING_INTENT_SOURCE_ADMISSION_KEY,
        _admitted(source_revision="someone-elses-revision"),
    )

    admission = await StateStoreOperatingIntentAdmissionReader(store, expectation=None).resolve(
        now=_NOW
    )

    assert admission.status is OperatingIntentAdmissionStatus.UNBOUND
    assert admission.owned_object_ids is None
