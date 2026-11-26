"""Synthetic, deterministic H10 boundary scenarios; no production providers or mutations."""

from __future__ import annotations

import asyncio
import builtins
import json
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, Mock, call

import pytest
from fdai.core.human_assignment.scoped_duties import (
    DutyResolution,
    DutySubject,
    DutySubjectKind,
    DutySubjectResolver,
    ExactScopeCatalogReader,
    ScopeCatalogEntry,
    ScopedDutyBinding,
    ScopedDutyInput,
    ScopedDutyPolicy,
    ScopedDutyValidationError,
    canonical_digest,
)
from fdai.core.human_assignment.scoped_duty_planning import (
    HeldReason,
    ScopedDutyPlanner,
    render_scoped_duty_review,
)
from fdai.core.stewardship.model import Duty

AT = datetime(2026, 9, 14, 12, tzinfo=UTC)
HOUR = timedelta(hours=1)
REVISION = "revision:example"
SCOPE = "scope:example"
PRIMARY = DutySubject(DutySubjectKind.PERSON, "human:example")
BACKUP = DutySubject(DutySubjectKind.PERSON, "human:example-backup")
THIRD = DutySubject(DutySubjectKind.PERSON, "human:example-third")
GROUP = DutySubject(DutySubjectKind.GROUP, "00000000-0000-0000-0000-000000000000")
OTHER_GROUP = DutySubject(DutySubjectKind.GROUP, "human:example-group")
SCHEDULE = DutySubject(DutySubjectKind.SCHEDULE, "human:example-schedule")
POLICY = ScopedDutyPolicy(timedelta(minutes=5), 1.0, 5.0)


def _binding(
    subject: DutySubject = PRIMARY, duty: Duty = Duty.PRIMARY, **changes: Any
) -> ScopedDutyBinding:
    fallback = PRIMARY if subject.kind is DutySubjectKind.SCHEDULE else None
    return replace(
        ScopedDutyBinding(subject, "Odin", SCOPE, duty, AT - HOUR, AT + HOUR, fallback),
        **changes,
    )


def _receipt(
    subject: DutySubject, people: tuple[DutySubject, ...], **changes: Any
) -> DutyResolution:
    return replace(
        DutyResolution(
            subject,
            AT,
            people,
            AT - timedelta(seconds=30),
            AT + timedelta(minutes=2),
            "evidence:example",
            "a" * 64,
            True,
        ),
        **changes,
    )


def _input(*bindings: ScopedDutyBinding) -> ScopedDutyInput:
    return ScopedDutyInput(REVISION, bindings or (_binding(), _binding(BACKUP, Duty.BACKUP)))


def _planner(
    replies: dict[DutySubject, object] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[ScopedDutyPlanner, AsyncMock, AsyncMock]:
    defaults = {
        PRIMARY: _receipt(PRIMARY, (PRIMARY,)),
        BACKUP: _receipt(BACKUP, (BACKUP,)),
    }
    rows = replies if replies is not None else defaults

    def resolve(subject: DutySubject, *, at: datetime) -> object:
        assert at == AT
        result = rows.get(subject)
        if isinstance(result, Exception):
            raise result
        return result

    subjects = AsyncMock(spec=DutySubjectResolver)
    scopes = AsyncMock(spec=ExactScopeCatalogReader)
    subjects.resolve.side_effect = resolve
    scopes.read_scope.side_effect = lambda ref, *, source_revision: (
        ScopeCatalogEntry(SCOPE, REVISION) if ref == SCOPE else None
    )
    return ScopedDutyPlanner(subjects, scopes, clock or (lambda: AT), POLICY), subjects, scopes


def test_invalid_declaration_boundaries() -> None:
    for changes in (
        {"agent_name": "Example"},
        {"agent_name": "odin"},
        {"duty": "primary"},
        {"subject": "human:example"},
        {"scope_ref": ""},
        {"scope_ref": " scope:example"},
        {"effective_from": AT.replace(tzinfo=None)},
        {"effective_until": AT.replace(tzinfo=None)},
        {"effective_from": AT, "effective_until": AT},
        {"effective_from": AT + 2 * HOUR},
    ):
        with pytest.raises(ScopedDutyValidationError):
            replace(_binding(), **changes)


def test_people_require_already_normalized_exact_references() -> None:
    for ref in ("", " human:example", "human:example ", "human:Example", "a\nb"):
        with pytest.raises(ScopedDutyValidationError):
            DutySubject(DutySubjectKind.PERSON, ref)


def test_source_revision_is_exact_not_trimmed() -> None:
    for revision in ("", " revision:example", "revision:example ", "a" * 257):
        with pytest.raises(ScopedDutyValidationError):
            replace(_input(), source_revision=revision)


def test_duplicate_overlap_and_self_conflicting_duties() -> None:
    for duty in Duty:
        for start in (AT - HOUR, AT):
            with pytest.raises(ScopedDutyValidationError, match="overlapping"):
                _input(_binding(), _binding(duty=duty, effective_from=start))


def test_adjacent_windows_and_distinct_scopes_are_not_overlap() -> None:
    adjacent = _input(_binding(effective_until=AT), _binding(effective_from=AT))
    assert len(adjacent.bindings) == 2
    assert len(_input(_binding(), _binding(scope_ref="scope:example-other")).bindings) == 2
    offset = timezone(timedelta(hours=9))
    equivalent = replace(_binding(), effective_from=(AT - HOUR).astimezone(offset))
    assert _input(equivalent).digest == _input(_binding()).digest


def test_immutable_ordered_inputs_and_hard_bounds() -> None:
    bindings = tuple(_binding(scope_ref=f"scope:example-{index}") for index in range(30))
    source = ScopedDutyInput(REVISION, bindings)
    assert source.bindings == bindings
    for invalid in ((), list(bindings), set(bindings), iter(bindings), bindings + (_binding(),)):
        with pytest.raises(ScopedDutyValidationError):
            ScopedDutyInput(REVISION, invalid)
    people = tuple(DutySubject(DutySubjectKind.PERSON, f"human:example-{i:03}") for i in range(100))
    receipt = _receipt(GROUP, people)
    assert len(receipt.people) == 100
    for invalid_people in (people + (PRIMARY,), list(people), (PRIMARY, PRIMARY), (GROUP,)):
        with pytest.raises(ScopedDutyValidationError):
            _receipt(GROUP, invalid_people)
    for target, name, value in (
        (source, "bindings", ()),
        (receipt, "people", ()),
        (PRIMARY, "ref", "human:example-other"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(target, name, value)


def test_malformed_person_and_observation_receipts() -> None:
    for changes in (
        {"people": (BACKUP,)},
        {"complete": "true"},
        {"provenance_ref": " "},
        {"provenance_digest": "A" * 64},
        {"provenance_digest": "a" * 63},
        {"observed_at": AT.replace(tzinfo=None)},
        {"at": AT.replace(tzinfo=None)},
        {"valid_until": AT.replace(tzinfo=None)},
        {"valid_until": AT - HOUR},
    ):
        with pytest.raises(ScopedDutyValidationError):
            replace(_receipt(PRIMARY, (PRIMARY,)), **changes)


async def test_scope_reader_must_match_exact_identity_and_revision() -> None:
    for reply, reason in (
        (None, HeldReason.UNKNOWN_SCOPE),
        (RuntimeError(), HeldReason.SCOPE_UNAVAILABLE),
        (ScopeCatalogEntry("Scope:example", REVISION), HeldReason.SCOPE_MISMATCH),
        (ScopeCatalogEntry("scope:example/child", REVISION), HeldReason.SCOPE_MISMATCH),
        (ScopeCatalogEntry(SCOPE, "revision:example-other"), HeldReason.SCOPE_MISMATCH),
        ({"scope_ref": SCOPE}, HeldReason.SCOPE_MISMATCH),
    ):
        planner, subjects, scopes = _planner()
        scopes.read_scope.side_effect = reply if isinstance(reply, Exception) else None
        scopes.read_scope.return_value = reply
        plan = await planner.plan(_input())
        assert not plan.has_current_coverage and reason in plan.coverage[0].held_reasons
        subjects.resolve.assert_not_awaited()
        scopes.read_scope.assert_awaited_once_with(SCOPE, source_revision=REVISION)


async def test_group_expansion_identity_completeness_and_freshness() -> None:
    for changes, reason in (
        ({"subject": OTHER_GROUP}, HeldReason.SUBJECT_MISMATCH),
        ({"at": AT + timedelta(seconds=1)}, HeldReason.QUERY_TIME_MISMATCH),
        ({"complete": False}, HeldReason.INCOMPLETE_RESOLUTION),
        ({"people": ()}, HeldReason.EMPTY_RESOLUTION),
        ({"observed_at": AT + timedelta(seconds=1)}, HeldReason.STALE_RESOLUTION),
        ({"observed_at": AT - timedelta(minutes=5)}, HeldReason.STALE_RESOLUTION),
        ({"valid_until": AT}, HeldReason.STALE_RESOLUTION),
    ):
        planner, _, _ = _planner({GROUP: replace(_receipt(GROUP, (PRIMARY,)), **changes)})
        plan = await planner.plan(_input(_binding(GROUP)))
        assert plan.bindings[0].held_reason is reason and not plan.has_current_coverage


@pytest.mark.parametrize("backup_people", [(PRIMARY,), (PRIMARY, BACKUP)])
async def test_distinct_group_ids_do_not_prove_distinct_humans(backup_people) -> None:
    replies = {GROUP: _receipt(GROUP, (PRIMARY, THIRD))}
    replies[OTHER_GROUP] = _receipt(OTHER_GROUP, backup_people)
    planner, _, _ = _planner(replies)
    plan = await planner.plan(_input(_binding(GROUP), _binding(OTHER_GROUP, Duty.BACKUP)))
    assert not plan.has_current_coverage
    assert HeldReason.SELF_CONFLICT in plan.coverage[0].held_reasons
    assert PRIMARY.ref not in plan.coverage[0].backup_refs


@pytest.mark.parametrize("failure", [None, RuntimeError(), TimeoutError()])
async def test_schedule_outage_resolves_only_configured_static_person(failure: object) -> None:
    replies = {SCHEDULE: failure, PRIMARY: _receipt(PRIMARY, (PRIMARY,))}
    replies[BACKUP] = _receipt(BACKUP, (BACKUP,))
    planner, subjects, _ = _planner(replies)
    plan = await planner.plan(_input(_binding(SCHEDULE), _binding(BACKUP, Duty.ESCALATION)))
    assert plan.has_current_coverage and plan.bindings[0].used_fallback
    assert plan.bindings[0].schedule_failure is HeldReason.RESOLUTION_UNAVAILABLE
    assert plan.bindings[0].resolution is not None
    assert plan.bindings[0].resolution.subject == PRIMARY
    expected = [call(SCHEDULE, at=AT), call(PRIMARY, at=AT), call(BACKUP, at=AT)]
    assert subjects.resolve.await_args_list == expected


@pytest.mark.parametrize("fallback", [None, GROUP, SCHEDULE])
def test_schedule_fallback_cannot_be_missing_group_or_schedule(fallback) -> None:
    with pytest.raises(ScopedDutyValidationError):
        _binding(SCHEDULE, fallback=fallback)
    with pytest.raises(ScopedDutyValidationError):
        _binding(GROUP, fallback=PRIMARY)
    with pytest.raises(ScopedDutyValidationError):
        _binding(SCHEDULE, fallback=DutySubject(DutySubjectKind.PERSON, SCHEDULE.ref))


async def test_unverified_static_fallback_never_proves_coverage() -> None:
    for fallback_reply, reason in (
        (None, HeldReason.RESOLUTION_UNAVAILABLE),
        (_receipt(PRIMARY, (PRIMARY,), valid_until=AT), HeldReason.STALE_RESOLUTION),
        (_receipt(GROUP, (PRIMARY,)), HeldReason.SUBJECT_MISMATCH),
        ({"people": (PRIMARY,)}, HeldReason.INVALID_RESOLUTION),
    ):
        planner, _, _ = _planner({SCHEDULE: None, PRIMARY: fallback_reply})
        plan = await planner.plan(_input(_binding(SCHEDULE)))
        assert not plan.has_current_coverage and plan.bindings[0].held_reason is reason


async def test_future_and_expired_windows_cannot_resolve_or_claim_current() -> None:
    for start, end, reason in (
        (AT + HOUR, AT + 2 * HOUR, HeldReason.NOT_YET_EFFECTIVE),
        (AT - HOUR, AT, HeldReason.EXPIRED),
    ):
        planner, subjects, _ = _planner()
        request = _input(
            _binding(SCHEDULE, effective_from=start, effective_until=end),
            _binding(BACKUP, Duty.BACKUP, effective_from=start, effective_until=end),
        )
        plan = await planner.plan(request)
        assert not plan.has_current_coverage and reason in plan.coverage[0].held_reasons
        subjects.resolve.assert_not_awaited()


async def test_clock_recheck_after_reads_prevents_stale_coverage() -> None:
    for finish, reason in (
        (AT - timedelta(microseconds=1), HeldReason.CLOCK_ROLLBACK),
        (AT + timedelta(minutes=2), HeldReason.STALE_RESOLUTION),
        (AT + HOUR, HeldReason.EXPIRED),
    ):
        planner, _, _ = _planner(clock=Mock(side_effect=[AT, finish]))
        plan = await planner.plan(_input())
        assert not plan.has_current_coverage and plan.checked_at == finish
        assert reason in plan.coverage[0].held_reasons


async def test_future_activation_during_reads_stays_unobserved() -> None:
    planner, subjects, _ = _planner(clock=Mock(side_effect=[AT, AT + timedelta(seconds=2)]))
    plan = await planner.plan(_input(_binding(SCHEDULE, effective_from=AT + timedelta(seconds=1))))
    assert plan.bindings[0].held_reason is HeldReason.NOT_OBSERVED
    assert not plan.has_current_coverage
    subjects.resolve.assert_not_awaited()


async def test_adjacent_transition_and_future_rows_do_not_borrow_current_people() -> None:
    planner, subjects, _ = _planner()
    request = _input(
        _binding(effective_until=AT),
        _binding(effective_from=AT),
        _binding(BACKUP, Duty.BACKUP),
        _binding(SCHEDULE, effective_from=AT + HOUR, effective_until=AT + 2 * HOUR),
    )
    plan = await planner.plan(request)
    assert plan.has_current_coverage
    assert [row.resolution for row in plan.bindings if row.binding.subject == SCHEDULE] == [None]
    assert subjects.resolve.await_count == 2


async def test_digest_replay_sorting_exact_revision_and_inert_rendering() -> None:
    receipt = _receipt(GROUP, (THIRD, PRIMARY), observed_at=AT)
    replies = {GROUP: receipt, BACKUP: _receipt(BACKUP, (BACKUP,))}
    first, _, _ = _planner(replies)
    second, _, _ = _planner({**replies, GROUP: replace(receipt, people=(PRIMARY, THIRD))})
    request = _input(_binding(GROUP), _binding(BACKUP, Duty.BACKUP))
    plan = await first.plan(request)
    replay = await second.plan(replace(request, bindings=tuple(reversed(request.bindings))))
    text = render_scoped_duty_review(plan)
    payload = json.loads(text)
    assert text == render_scoped_duty_review(replay) and text.endswith("\n")
    assert plan.digest == payload.pop("digest") == canonical_digest(payload)
    assert payload["kind"] == "scoped_duty_review" and payload["schema_version"] == "1.0.0"
    assert payload["coverage_basis"] == "current_observation_only" and "stewardship" not in payload
    assert payload["bindings"][0]["binding"]["scope_ref"] == SCOPE
    assert payload["bindings"][0]["binding"]["effective_until"] == (AT + HOUR).isoformat()
    assert replace(request, source_revision="revision:example-other").digest != request.digest
    changed = replace(request.bindings[0], effective_until=AT + 2 * HOUR)
    assert replace(request, bindings=(changed, request.bindings[1])).digest != request.digest
    third, _, _ = _planner({**replies, GROUP: replace(receipt, provenance_digest="b" * 64)})
    assert (await third.plan(request)).digest != plan.digest
    stricter = replace(first, policy=ScopedDutyPolicy(timedelta(minutes=1), 1.0, 5.0))
    assert (await stricter.plan(request)).digest != plan.digest
    payload["bindings"][0]["binding"]["scope_ref"] = "scope:example-other"
    assert render_scoped_duty_review(plan) == text


async def test_no_models_agent_calls_writes_or_authority_fields(monkeypatch) -> None:
    planner, subjects, scopes = _planner()
    forbidden = Mock(side_effect=AssertionError("model, agent, or write operation is forbidden"))
    subjects.generate = subjects.call_agent = subjects.write_state = scopes.publish = forbidden
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        plan = await planner.plan(_input())
        payload = json.loads(render_scoped_duty_review(plan))
    forbidden.assert_not_called()
    assert plan.has_current_coverage and plan.review_required and not plan.execution_authority
    assert payload["review_required"] is True and payload["execution_authority"] is False
    assert not {"role", "requested_role", "iam"} & {item.name for item in fields(ScopedDutyBinding)}
    subjects.resolve.assert_has_awaits([call(PRIMARY, at=AT), call(BACKUP, at=AT)])
    assert subjects.resolve.await_count == 2 and scopes.read_scope.await_count == 2
    with pytest.raises(FrozenInstanceError):
        plan.source_revision = "revision:example-other"


async def test_cancellation_is_not_a_fallback_or_a_retry() -> None:
    planner, subjects, _ = _planner()
    subjects.resolve.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await planner.plan(_input(_binding(SCHEDULE)))
    assert subjects.resolve.await_count == 1


def test_policy_has_no_unbounded_or_permissive_defaults() -> None:
    bad = ((timedelta(0), 1), (-HOUR, 1), (HOUR, 0), (HOUR, True), (HOUR, float("nan")), (HOUR, 31))
    for age, timeout in bad:
        with pytest.raises(ScopedDutyValidationError):
            ScopedDutyPolicy(age, timeout, 5.0)


async def test_naive_clock_fails_before_any_read() -> None:
    planner, subjects, scopes = _planner(clock=Mock(return_value=AT.replace(tzinfo=None)))
    with pytest.raises(ScopedDutyValidationError):
        await planner.plan(_input())
    subjects.resolve.assert_not_awaited()
    scopes.read_scope.assert_not_awaited()


async def test_total_deadline_cancels_reads_without_claiming_partial_coverage():
    planner, subjects, scopes = _planner()
    planner = replace(planner, policy=replace(POLICY, total_timeout_seconds=0.001))

    async def blocked(*args, **kwargs):
        await asyncio.Event().wait()

    scopes.read_scope.side_effect = blocked
    with pytest.raises(ScopedDutyValidationError, match="total deadline"):
        await planner.plan(_input())
    subjects.resolve.assert_not_awaited()
    assert scopes.read_scope.await_count == 1


@pytest.mark.parametrize("changed", [None, RuntimeError("catalog unavailable")])
async def test_scope_changed_during_identity_reads_cannot_keep_coverage(changed):
    planner, subjects, scopes = _planner()
    scopes.read_scope.side_effect = [ScopeCatalogEntry(SCOPE, REVISION), changed]
    plan = await planner.plan(_input())
    assert not plan.has_current_coverage
    expected = HeldReason.UNKNOWN_SCOPE if changed is None else HeldReason.SCOPE_UNAVAILABLE
    assert expected in plan.coverage[0].held_reasons
    assert subjects.resolve.await_count == 2
    assert scopes.read_scope.await_count == 2
