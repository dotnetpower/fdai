from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.operational_context.test_context import (
    TestContextClaim as ContextClaim,
)
from fdai.core.operational_context.test_context import (
    evaluate_test_context,
    observation_context_digest,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission

NOW = datetime(2026, 9, 14, tzinfo=UTC)


def _claim() -> ContextClaim:
    return ContextClaim(
        context_id="test-example",
        revision=1,
        access_scope_digest="a" * 64,
        target_ref="resource-example",
        signal_code="cpu_percent",
        expected_min=60,
        expected_max=90,
        effective_from=NOW,
        effective_to=NOW + timedelta(hours=1),
        recorded_at=NOW,
        source_ref="operator-turn:example",
        requested_by="operator-one",
        reviewed_by="reviewer-two",
        policy_revision="policy:example:1",
        state="reviewed",
    )


def _admission(claim: ContextClaim) -> DecisionEvidenceAdmission:
    return DecisionEvidenceAdmission(
        receipt_digest="sha256:" + "b" * 64,
        verification_bundle_digest="sha256:" + "c" * 64,
        evidence_digest=claim.digest,
        scope_digest="sha256:" + claim.access_scope_digest,
        purpose_id="operational-test-context",
        source_revision=claim.policy_revision,
        verified_at=NOW,
        valid_until=NOW + timedelta(minutes=30),
    )


def _evaluate(claim: ContextClaim | None, **overrides: Any) -> Any:
    values = {
        "target_ref": "resource-example",
        "access_scope_digest": "a" * 64,
        "signal_code": "cpu_percent",
        "observed_value": 80.0,
        "observed_at": NOW + timedelta(minutes=1),
        "evaluated_at": NOW + timedelta(minutes=2),
        "service_impact": "none",
        "protected_signal": False,
        "admission": _admission(claim) if claim is not None else None,
    }
    if claim is not None:
        values["observation_admission"] = replace(
            _admission(claim),
            purpose_id="operational-test-observation",
            verified_at=NOW + timedelta(minutes=1),
            evidence_digest=observation_context_digest(
                **{
                    key: values[key]
                    for key in (
                        "target_ref",
                        "access_scope_digest",
                        "signal_code",
                        "observed_value",
                        "observed_at",
                        "service_impact",
                        "protected_signal",
                    )
                }
            ),
        )
    values.update(overrides)
    return evaluate_test_context(claim, **values)


@pytest.mark.parametrize("changes", [{"observation_admission": None}, {"observed_value": 81.0}])
def test_claim_approval_cannot_self_attest_current_observation(changes: dict[str, Any]) -> None:
    result = _evaluate(_claim(), **changes)
    assert result.response_disposition == "hold"
    assert result.reason == "observation_admission_required"


def test_expected_signal_preserves_observation_and_cannot_grant_execution() -> None:
    result = _evaluate(_claim())
    assert result.observed_fact == "observed"
    assert result.expected_condition == "expected"
    assert result.response_disposition == "observe"
    assert result.learning_eligibility == "test_cohort"
    assert result.execution_eligibility == "ordinary_gates_required"


async def test_authenticated_commands_require_var_review_and_preserve_revision_identity() -> None:
    from fdai.core.operational_context.test_context_commands import TestContextCommandHandler
    from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    admission = _TransitionAdmission()
    contexts = GovernedTestContextStore(
        store=InMemoryStateStore(), admission=admission, clock=lambda: NOW
    )
    handler = TestContextCommandHandler(contexts=contexts, admission=admission, clock=lambda: NOW)
    claim = _claim()
    request = {
        "operation": "propose",
        "context_id": claim.context_id,
        "access_scope_digest": claim.access_scope_digest,
        "target_ref": claim.target_ref,
        "signal_code": claim.signal_code,
        "expected_revision": 0,
        "policy_revision": claim.policy_revision,
        "source_ref": claim.source_ref,
        "semantic_receipt": "sha256:" + "a" * 64,
        "expected_min": 60,
        "expected_max": 90,
        "effective_from": NOW.isoformat(),
        "effective_to": (NOW + timedelta(hours=1)).isoformat(),
    }
    payload = {
        "request": request,
        "actor_id": "operator-one",
        "actor_roles": ["Contributor"],
        "idempotency_key": "context-example",
        "requested_at": NOW.isoformat(),
    }
    assert (await handler.transition(payload, reviewed_by_var=False))["state"] == "proposed"
    review = {
        key: value
        for key, value in request.items()
        if key not in {"expected_min", "expected_max", "effective_from", "effective_to"}
    }
    review.update(operation="review", expected_revision=1)
    payload.update(request=review, actor_id="reviewer-two", actor_roles=["Approver"])
    with pytest.raises(PermissionError, match="Var"):
        await handler.transition(payload, reviewed_by_var=False)
    assert (await handler.transition(payload, reviewed_by_var=True))["state"] == "reviewed"


@pytest.mark.parametrize("state", ["proposed", "revoked", "conflicting"])
def test_unreviewed_revoked_and_conflicting_context_are_held(state: str) -> None:
    assert _evaluate(replace(_claim(), state=state)).response_disposition == "hold"


@pytest.mark.parametrize(
    "overrides",
    [
        {"admission": None},
        {"target_ref": "other-resource"},
        {"access_scope_digest": "d" * 64},
        {"evaluated_at": NOW + timedelta(hours=1)},
        {"observed_value": float("nan")},
        {"service_impact": "unknown"},
        {"observed_at": NOW + timedelta(hours=2)},
    ],
)
def test_unknown_or_invalid_inputs_never_become_expected_context(overrides: dict[str, Any]) -> None:
    assert _evaluate(_claim(), **overrides).response_disposition == "hold"


@pytest.mark.parametrize(
    "overrides",
    [
        {"observed_value": 95.0},
        {"signal_code": "io_errors"},
        {"protected_signal": True},
        {"service_impact": "affected"},
    ],
)
def test_unexpected_or_protected_impact_requires_investigation(overrides: dict[str, Any]) -> None:
    assert _evaluate(_claim(), **overrides).response_disposition == "investigate"


def test_late_user_correction_does_not_rewrite_original_decision_context() -> None:
    result = _evaluate(replace(_claim(), recorded_at=NOW + timedelta(minutes=2)))
    assert result.reason == "context_not_current_at_decision"


def test_same_operator_cannot_self_review_using_casing_or_whitespace() -> None:
    assert (
        _evaluate(replace(_claim(), reviewed_by=" OPERATOR-ONE ")).reason
        == "independent_review_required"
    )


def test_test_environment_statement_alone_is_not_an_expected_fault() -> None:
    assert _evaluate(None).reason == "context_missing"


def test_changed_limits_invalidate_original_admission() -> None:
    original = _claim()
    assert (
        _evaluate(replace(original, expected_max=95), admission=_admission(original)).reason
        == "context_admission_required"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"target_ref": ""},
        {"revision": True},
        {"access_scope_digest": "bad"},
        {"state": "active"},
        {"recorded_at": NOW.replace(tzinfo=None)},
        {"effective_to": NOW},
        {"expected_max": float("nan")},
        {"expected_min": 100},
    ],
)
def test_invalid_claim_contract_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        replace(_claim(), **changes)


async def test_governed_context_proposal_review_revoke_survives_restart() -> None:
    from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    class _Admission:
        async def admit(self, **values):
            return DecisionEvidenceAdmission(
                **values,
                receipt_digest="sha256:" + "b" * 64,
                verification_bundle_digest="sha256:" + "c" * 64,
                verified_at=NOW,
                valid_until=NOW + timedelta(hours=1),
            )

    state = InMemoryStateStore()
    lifecycle = GovernedTestContextStore(store=state, admission=_Admission(), clock=lambda: NOW)
    draft = replace(_claim(), state="proposed", reviewed_by="")
    await lifecycle.record_transition(draft, expected_revision=0, now=NOW)
    reviewed = replace(draft, state="reviewed", revision=2, reviewed_by="reviewer-two")
    await lifecycle.record_transition(reviewed, expected_revision=1, now=NOW)
    await lifecycle.record_transition(reviewed, expected_revision=1, now=NOW)
    restarted = GovernedTestContextStore(store=state, admission=_Admission(), clock=lambda: NOW)
    query = {
        "target_ref": draft.target_ref,
        "access_scope_digest": draft.access_scope_digest,
        "at": NOW,
    }
    assert await restarted.read(**query) == reviewed
    revoked = replace(reviewed, state="revoked", revision=3)
    await restarted.record_transition(revoked, expected_revision=2, now=NOW)
    assert await lifecycle.read(**query) == revoked
    assert await state.verify_chain()
    from unittest.mock import AsyncMock

    state.compare_and_set_state_with_audit = AsyncMock(wraps=state.compare_and_set_state_with_audit)
    await lifecycle.record_transition(reviewed, expected_revision=1, now=NOW)
    await lifecycle.record_transition(draft, expected_revision=0, now=NOW)
    state.compare_and_set_state_with_audit.assert_not_awaited()
    assert await lifecycle.read(**query) == revoked
    with pytest.raises(ValueError, match="revision"):
        await lifecycle.record_transition(
            replace(reviewed, reviewed_by="different-reviewer"), expected_revision=1, now=NOW
        )
    with pytest.raises(PermissionError, match="not allowed"):
        await lifecycle.record_transition(
            replace(revoked, state="reviewed", revision=4), expected_revision=3, now=NOW
        )


class _TransitionAdmission:
    async def admit(self, **values):
        return DecisionEvidenceAdmission(
            **values,
            receipt_digest="sha256:" + "b" * 64,
            verification_bundle_digest="sha256:" + "c" * 64,
            verified_at=NOW,
            valid_until=NOW + timedelta(hours=1),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"reviewed_by": " OPERATOR-ONE "},
        {"expected_max": 100},
        {"source_ref": "operator-turn:substituted"},
        {"policy_revision": "policy:other"},
        {"revision": 4},
        {"recorded_at": NOW + timedelta(hours=2)},
    ],
)
async def test_context_review_cannot_change_or_self_approve_a_proposal(
    changes: dict[str, Any],
) -> None:
    from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    store = GovernedTestContextStore(
        store=InMemoryStateStore(), admission=_TransitionAdmission(), clock=lambda: NOW
    )
    draft = replace(_claim(), state="proposed", reviewed_by="")
    await store.record_transition(draft, expected_revision=0, now=NOW)
    reviewed = replace(draft, state="reviewed", revision=2, reviewed_by="reviewer-two")
    with pytest.raises((ValueError, PermissionError)):
        await store.record_transition(replace(reviewed, **changes), expected_revision=1, now=NOW)
    assert (
        await store.read(
            target_ref=draft.target_ref, access_scope_digest=draft.access_scope_digest, at=NOW
        )
        == draft
    )


async def test_overlapping_reviewed_contexts_are_not_activated() -> None:
    from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    store = GovernedTestContextStore(
        store=InMemoryStateStore(), admission=_TransitionAdmission(), clock=lambda: NOW
    )
    draft = replace(_claim(), state="proposed", reviewed_by="")
    await store.record_transition(draft, expected_revision=0, now=NOW)
    first = replace(draft, state="reviewed", revision=2, reviewed_by="reviewer-two")
    await store.record_transition(first, expected_revision=1, now=NOW)
    other = replace(draft, context_id="other-test")
    await store.record_transition(other, expected_revision=0, now=NOW)
    with pytest.raises(PermissionError, match="overlapping"):
        await store.record_transition(
            replace(other, state="reviewed", revision=2, reviewed_by="reviewer-two"),
            expected_revision=1,
            now=NOW,
        )
    assert (
        await store.read(
            target_ref=draft.target_ref, access_scope_digest=draft.access_scope_digest, at=NOW
        )
        == first
    )


@pytest.mark.parametrize("mode", ["missing", "wrong-scope", "expires-during-read"])
async def test_context_transition_requires_current_exact_admission(mode: str) -> None:
    from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    class _Admission(_TransitionAdmission):
        async def admit(self, **values):
            if mode == "missing":
                return None
            result = await super().admit(**values)
            return (
                replace(result, scope_digest="sha256:" + "f" * 64)
                if mode == "wrong-scope"
                else result
            )

    store = GovernedTestContextStore(
        store=InMemoryStateStore(),
        admission=_Admission(),
        clock=lambda: NOW + timedelta(hours=1) if mode == "expires-during-read" else NOW,
    )
    draft = replace(_claim(), state="proposed", reviewed_by="")
    with pytest.raises(PermissionError, match="independent admission"):
        await store.record_transition(draft, expected_revision=0, now=NOW)
    assert (
        await store.read(
            target_ref=draft.target_ref, access_scope_digest=draft.access_scope_digest, at=NOW
        )
        is None
    )


async def test_context_future_revision_is_not_mistaken_for_missing_context() -> None:
    from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    store = GovernedTestContextStore(
        store=InMemoryStateStore(),
        admission=_TransitionAdmission(),
        clock=lambda: NOW,
    )
    draft = replace(_claim(), state="proposed", reviewed_by="")
    await store.record_transition(draft, expected_revision=0, now=NOW)
    with pytest.raises(ValueError, match="future"):
        await store.read(
            target_ref=draft.target_ref,
            access_scope_digest=draft.access_scope_digest,
            at=NOW - timedelta(seconds=1),
        )


async def test_context_activation_rechecks_effective_end_after_admission() -> None:
    from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    durable = InMemoryStateStore()
    store = GovernedTestContextStore(
        store=durable, admission=_TransitionAdmission(), clock=lambda: NOW
    )
    draft = replace(
        _claim(), state="proposed", reviewed_by="", effective_to=NOW + timedelta(minutes=5)
    )
    await store.record_transition(draft, expected_revision=0, now=NOW)
    store._clock = lambda: draft.effective_to
    with pytest.raises(PermissionError, match="expired while"):
        await store.record_transition(
            replace(draft, state="reviewed", revision=2, reviewed_by="reviewer-two"),
            expected_revision=1,
            now=NOW,
        )


@pytest.mark.parametrize(
    "field,value", [("revision", 7), ("state", "reviewed"), ("context_id", "other")]
)
async def test_context_read_rejects_corrupted_revision_chain(field: str, value: Any) -> None:
    from fdai.core.operational_context.test_context_lifecycle import (
        GovernedTestContextStore,
        _state_key,
    )
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    durable = InMemoryStateStore()
    contexts = GovernedTestContextStore(
        store=durable, admission=_TransitionAdmission(), clock=lambda: NOW
    )
    draft = replace(_claim(), state="proposed")
    await contexts.record_transition(draft, expected_revision=0, now=NOW)
    key = _state_key(draft.access_scope_digest, draft.target_ref)
    state = await durable.read_state(key)
    assert state is not None
    state["histories"][draft.context_id][0][field] = value
    await durable.write_state(key, state)
    with pytest.raises(ValueError, match="(history|chain)"):
        await contexts.read(
            target_ref=draft.target_ref, access_scope_digest=draft.access_scope_digest, at=NOW
        )
