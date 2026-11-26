"""Apply reports, failure suppressions, and the reported-state API."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from functools import partial
from typing import Any

import pytest
from fdai_deployment_cli.lifecycle_plan import SuppressionWindow
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from fdai_lifecycle_hub import models
from fdai_lifecycle_hub.api import MAX_STATE_BYTES, create_app
from fdai_lifecycle_hub.domain import Installation, Issued, IssuedPlan, Planner, Waiting
from fdai_lifecycle_hub.enrollment import EnrollmentRequest
from fdai_lifecycle_hub.errors import (
    ReportAttemptGapError,
    ReportConflictError,
    ReportProgressionError,
)
from fdai_lifecycle_hub.reports import (
    FAILURE_HOLD,
    FAILURE_HOLD_GRACE,
    validate_report_progress,
)
from fdai_lifecycle_hub.schemas import PlanReport, reported_state_json
from fdai_lifecycle_hub.signing import verify_key_proof
from fdai_lifecycle_hub.store import HubStore

type Enroll = Callable[[HubStore, Installation], None]

STATE_URL = "/v1/installations/installation-alpha/state"


def _report(digest: str, attempt: int, outcome: str, reason_code: str) -> PlanReport:
    return PlanReport.model_validate(
        {
            "attempt": attempt,
            "outcome": outcome,
            "reason_code": reason_code,
            "exact_plan_digest": digest,
            "summary": "1 entity",
            "reported_at": "2026-10-05T03:01:00Z",
        }
    )


@pytest.fixture
def registered(hub_store: HubStore, enroll: Enroll, installation: Installation) -> HubStore:
    enroll(hub_store, installation)
    return hub_store


@pytest.fixture
def issued(
    registered: HubStore, installation: Installation, planner: Planner, now: datetime
) -> IssuedPlan:
    outcome = registered.recompute(installation.installation_id, planner, now=now)
    assert isinstance(outcome, Issued)
    return IssuedPlan.from_signed(outcome.plan)


def _audited_suppressions(store: HubStore) -> list[tuple[str, dict[str, Any]]]:
    with Session(store.engine) as session:
        records = session.scalars(
            select(models.AuditRecord)
            .where(models.AuditRecord.action == "suppression.added")
            .order_by(models.AuditRecord.sequence)
        )
        return [(record.subject, record.payload) for record in records]


@pytest.mark.parametrize(
    ("outcome", "reason_code"),
    [
        ("apply-started", "apply_started"),
        ("applied", "applied"),
        ("rolled-back", "health_check_failed"),
        ("rolled-back", "apply_failed"),
    ],
)
def test_apply_outcomes_are_accepted_with_their_reason_codes(
    outcome: str, reason_code: str
) -> None:
    report = _report("sha256:" + "a" * 64, 1, outcome, reason_code)

    assert (report.outcome, report.reason_code) == (outcome, reason_code)


@pytest.mark.parametrize(
    ("outcome", "reason_code", "digest"),
    [
        ("apply-started", "apply_started", None),
        ("applied", "applied", None),
        ("rolled-back", "health_check_failed", None),
        ("applied", "health_check_failed", "sha256:" + "a" * 64),
        ("rolled-back", "applied", "sha256:" + "a" * 64),
        ("deployed", "applied", "sha256:" + "a" * 64),
    ],
)
def test_apply_reports_need_the_plan_digest_and_their_reason_codes(
    outcome: str, reason_code: str, digest: str | None
) -> None:
    with pytest.raises(ValidationError):
        PlanReport.model_validate(
            {
                "attempt": 1,
                "outcome": outcome,
                "reason_code": reason_code,
                "exact_plan_digest": digest,
                "summary": "",
                "reported_at": "2026-10-05T03:01:00Z",
            }
        )


def test_rolled_back_report_holds_every_plan_entity_until_lifted(
    registered: HubStore,
    installation: Installation,
    issued: IssuedPlan,
    planner: Planner,
    now: datetime,
) -> None:
    installation_id = installation.installation_id
    record = partial(registered.record_report, installation_id, issued.plan_id, now=now)

    record(_report(issued.digest, 1, "apply-started", "started"))
    record(_report(issued.digest, 2, "rolled-back", "health_check_failed"))

    starts_at = now - FAILURE_HOLD_GRACE
    hold = SuppressionWindow(
        "entity:core", starts_at, starts_at + FAILURE_HOLD, "failure", issued.plan_id
    )
    assert registered.load(installation_id).suppressions == (hold,)
    assert registered.current_plan(installation_id, now=now) is None
    assert _audited_suppressions(registered) == [
        (
            "entity:core",
            {
                "ends_at": hold.ends_at.isoformat(),
                "origin": "failure",
                "failed_plan_id": issued.plan_id,
            },
        )
    ]
    held = registered.recompute(installation_id, planner, now=now)
    assert isinstance(held, Waiting)
    assert held.release_id == issued.target_release_id
    assert [block.reason_code for block in held.checks[0].blocks] == ["suppression_window_active"]

    registered.lift_suppressions(installation_id, "entity:core", now=now)
    assert isinstance(registered.recompute(installation_id, planner, now=now), Issued)
    assert registered.audit_chain_intact()


def test_failure_hold_ends_by_itself(
    registered: HubStore,
    installation: Installation,
    issued: IssuedPlan,
    planner: Planner,
    now: datetime,
) -> None:
    registered.record_report(
        installation.installation_id,
        issued.plan_id,
        _report(issued.digest, 1, "apply-started", "started"),
        now=now,
    )
    report = _report(issued.digest, 2, "rolled-back", "apply_failed")
    registered.record_report(installation.installation_id, issued.plan_id, report, now=now)

    later = now - FAILURE_HOLD_GRACE + FAILURE_HOLD
    outcome = registered.recompute(installation.installation_id, planner, now=later)

    assert not isinstance(outcome, Waiting)


def test_failure_hold_absorbs_a_reader_clock_slightly_behind_the_writer(
    registered: HubStore,
    installation: Installation,
    issued: IssuedPlan,
    planner: Planner,
    now: datetime,
) -> None:
    """A recompute whose own clock reads a little earlier than the writer's still sees the hold,
    within the grace margin; past it, the hold is correctly not yet in effect."""

    registered.record_report(
        installation.installation_id,
        issued.plan_id,
        _report(issued.digest, 1, "apply-started", "started"),
        now=now,
    )
    report = _report(issued.digest, 2, "rolled-back", "apply_failed")
    registered.record_report(installation.installation_id, issued.plan_id, report, now=now)

    within_grace = registered.recompute(
        installation.installation_id, planner, now=now - FAILURE_HOLD_GRACE + timedelta(seconds=1)
    )
    beyond_grace = registered.recompute(
        installation.installation_id, planner, now=now - FAILURE_HOLD_GRACE - timedelta(seconds=1)
    )

    assert isinstance(within_grace, Waiting)
    assert not isinstance(beyond_grace, Waiting)


def test_repeated_rolled_back_report_adds_no_second_hold(
    registered: HubStore, installation: Installation, issued: IssuedPlan, now: datetime
) -> None:
    registered.record_report(
        installation.installation_id,
        issued.plan_id,
        _report(issued.digest, 1, "apply-started", "started"),
        now=now,
    )
    report = _report(issued.digest, 2, "rolled-back", "apply_failed")

    assert registered.record_report(installation.installation_id, issued.plan_id, report, now=now)
    assert not registered.record_report(
        installation.installation_id, issued.plan_id, report, now=now + timedelta(minutes=1)
    )
    assert len(registered.load(installation.installation_id).suppressions) == 1


@pytest.mark.parametrize("outcome", ["applied", "rolled-back"])
def test_effect_result_requires_apply_started(
    registered: HubStore,
    installation: Installation,
    issued: IssuedPlan,
    now: datetime,
    outcome: str,
) -> None:
    reason = "applied" if outcome == "applied" else "apply_failed"

    with pytest.raises(ReportProgressionError, match="apply-started"):
        registered.record_report(
            installation.installation_id,
            issued.plan_id,
            _report(issued.digest, 1, outcome, reason),
            now=now,
        )


@pytest.mark.parametrize(
    ("previous_outcome", "current_outcome", "current_reason"),
    [
        ("rejected", "rejected", "input_unavailable"),
        ("rejected", "apply-started", "apply_started"),
        ("apply-started", "applied", "applied"),
        ("apply-started", "rolled-back", "apply_failed"),
    ],
)
def test_report_progress_accepts_exact_nonterminal_successors(
    previous_outcome: str,
    current_outcome: str,
    current_reason: str,
) -> None:
    digest = "sha256:" + "a" * 64
    previous = _report(digest, 1, previous_outcome, "input_unavailable")
    current = _report(digest, 2, current_outcome, current_reason)

    validate_report_progress(previous, current)


@pytest.mark.parametrize(
    ("outcome", "reason_code", "exact_digest", "summary"),
    [
        ("apply-started", "apply_started", True, "1 entity"),
        ("rejected", "invalid_successor", False, ""),
        ("rejected", "plan_expired", True, ""),
        ("rejected", "plan_expired", False, "1 entity"),
    ],
)
def test_apply_started_rejects_every_other_non_effect_successor(
    outcome: str, reason_code: str, exact_digest: bool, summary: str
) -> None:
    digest = "sha256:" + "a" * 64
    previous = _report(digest, 1, "apply-started", "apply_started")
    current = PlanReport(
        attempt=2,
        outcome=outcome,
        reason_code=reason_code,
        exact_plan_digest=digest if exact_digest else None,
        summary=summary,
        reported_at=previous.reported_at + timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="followed by applied or rolled-back"):
        validate_report_progress(previous, current)


def test_apply_started_accepts_only_empty_plan_expired_rejection_and_makes_it_terminal() -> None:
    digest = "sha256:" + "a" * 64
    previous = _report(digest, 1, "apply-started", "apply_started")
    expired = PlanReport(
        attempt=2,
        outcome="rejected",
        reason_code="plan_expired",
        exact_plan_digest=None,
        summary="",
        reported_at=previous.reported_at + timedelta(seconds=1),
    )

    validate_report_progress(previous, expired)

    with pytest.raises(ValueError, match="terminal report"):
        validate_report_progress(
            expired,
            expired.model_copy(
                update={
                    "attempt": 3,
                    "reason_code": "invalid_successor",
                    "reported_at": expired.reported_at + timedelta(seconds=1),
                }
            ),
        )


def test_report_attempts_are_contiguous_despite_client_clock_changes(
    registered: HubStore, installation: Installation, issued: IssuedPlan, now: datetime
) -> None:
    record = partial(
        registered.record_report, installation.installation_id, issued.plan_id, now=now
    )
    first = _report(issued.digest, 1, "rejected", "input_unavailable")
    record(first)

    with pytest.raises(ReportAttemptGapError, match="required attempt 2"):
        record(_report(issued.digest, 3, "apply-started", "started"))
    stale = _report(issued.digest, 2, "apply-started", "started").model_copy(
        update={"reported_at": first.reported_at - timedelta(seconds=1)}
    )

    assert record(stale)
    assert [
        (report.attempt, report.reported_at)
        for report in registered.reports(installation.installation_id)
    ] == [(1, first.reported_at), (2, stale.reported_at)]


def test_terminal_report_rejects_followup(
    registered: HubStore, installation: Installation, issued: IssuedPlan, now: datetime
) -> None:
    record = partial(
        registered.record_report, installation.installation_id, issued.plan_id, now=now
    )
    record(_report(issued.digest, 1, "dry-run-admitted", "dry_run_computed"))

    with pytest.raises(ReportProgressionError, match="terminal"):
        record(_report(issued.digest, 2, "rejected", "changed_result"))


@pytest.mark.parametrize("terminal", ["dry-run-admitted", "plan_expired", "applied"])
def test_terminal_attempt_conflicts_cannot_be_reconciled_by_a_successor(
    registered: HubStore,
    installation: Installation,
    issued: IssuedPlan,
    now: datetime,
    terminal: str,
) -> None:
    record = partial(
        registered.record_report, installation.installation_id, issued.plan_id, now=now
    )
    if terminal == "dry-run-admitted":
        terminal_report = _report(issued.digest, 1, terminal, "dry_run_computed")
    else:
        record(_report(issued.digest, 1, "apply-started", "apply_started"))
        terminal_report = (
            PlanReport(
                attempt=2,
                outcome="rejected",
                reason_code="plan_expired",
                exact_plan_digest=None,
                summary="",
                reported_at=now,
            )
            if terminal == "plan_expired"
            else _report(issued.digest, 2, "applied", "applied")
        )
    record(terminal_report)

    with pytest.raises(ReportConflictError):
        record(terminal_report.model_copy(update={"reason_code": "conflicting_terminal"}))
    with pytest.raises(ReportProgressionError, match="terminal"):
        record(
            PlanReport(
                attempt=terminal_report.attempt + 1,
                outcome="rejected",
                reason_code="invalid_successor",
                exact_plan_digest=None,
                summary="",
                reported_at=now,
            )
        )


def test_applied_report_holds_nothing(
    registered: HubStore, installation: Installation, issued: IssuedPlan, now: datetime
) -> None:
    for attempt, outcome, reason in ((1, "apply-started", "started"), (2, "applied", "applied")):
        report = _report(issued.digest, attempt, outcome, reason)
        registered.record_report(installation.installation_id, issued.plan_id, report, now=now)

    assert registered.load(installation.installation_id).suppressions == ()
    assert [r.outcome for r in registered.reports(installation.installation_id)] == [
        "apply-started",
        "applied",
    ]


@pytest.fixture
def client(registered: HubStore, now: datetime) -> TestClient:
    return TestClient(create_app(registered, clock=lambda: now))


def _state_body(installation: Installation, **changes: object) -> dict[str, Any]:
    body: dict[str, Any] = reported_state_json.dump_python(installation.reported, mode="json")
    return body | changes


def test_reported_state_is_accepted_and_becomes_current(
    client: TestClient, registered: HubStore, installation: Installation, now: datetime
) -> None:
    body = _state_body(installation, digest="c" * 64, observed_at=now.isoformat())
    body["entities"]["core"]["release_id"] = "1.6.0"

    response = client.post(STATE_URL, json=body)

    assert response.status_code == 202
    reported = registered.load(installation.installation_id).reported
    assert (reported.digest, reported.entities["core"].release_id) == ("c" * 64, "1.6.0")


def test_state_that_is_not_newer_returns_409(
    client: TestClient, installation: Installation
) -> None:
    response = client.post(STATE_URL, json=_state_body(installation))

    assert (response.status_code, response.json()) == (409, {"error": "stale_state"})


@pytest.mark.parametrize(
    "change",
    [
        {"digest": "sha256:" + "c" * 64},
        {"observed_at": "2026-10-05T03:00:00"},
        {"schema_revision": -1},
        {"entities": {"core": {"release_id": "v1", "artifact_digests": [], "health": "healthy"}}},
        {"entities": {}},
    ],
)
def test_invalid_state_returns_422(
    client: TestClient, installation: Installation, now: datetime, change: dict[str, object]
) -> None:
    body = _state_body(installation, observed_at=now.isoformat()) | change

    response = client.post(STATE_URL, json=body)

    assert (response.status_code, response.json()) == (422, {"error": "state_invalid"})


def test_state_naming_an_unknown_entity_returns_422(
    client: TestClient, installation: Installation, now: datetime
) -> None:
    body = _state_body(installation, observed_at=now.isoformat())
    body["entities"]["ghost"] = body["entities"]["core"]

    response = client.post(STATE_URL, json=body)

    assert (response.status_code, response.json()) == (422, {"error": "state_invalid"})


def test_state_for_an_unknown_or_pending_installation_returns_404(
    hub_store: HubStore,
    installation: Installation,
    enrollment: EnrollmentRequest,
    now: datetime,
) -> None:
    client = TestClient(create_app(hub_store, clock=lambda: now))
    body = _state_body(installation, observed_at=now.isoformat())

    unknown = client.post(STATE_URL, json=body)
    hub_store.request_enrollment(enrollment, verify=verify_key_proof, now=now)
    pending = client.post(STATE_URL, json=body)

    assert (unknown.status_code, unknown.json()) == (404, {"error": "not_found"})
    assert (pending.status_code, pending.json()) == (404, {"error": "not_found"})


def test_oversized_state_returns_413(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        yield b"x" * MAX_STATE_BYTES
        yield b"x"

    response = client.post(STATE_URL, content=chunks())

    assert (response.status_code, response.json()) == (413, {"error": "state_too_large"})


def test_rolled_back_report_over_http_withdraws_the_plan(
    client: TestClient, installation: Installation, issued: IssuedPlan
) -> None:
    reports_url = f"/v1/installations/installation-alpha/plans/{issued.plan_id}/reports"
    plan_url = "/v1/installations/installation-alpha/plan"
    started = _report(issued.digest, 1, "apply-started", "started").model_dump(mode="json")
    rolled_back = _report(issued.digest, 2, "rolled-back", "health_check_failed")

    assert client.get(plan_url).status_code == 200
    assert client.post(reports_url, json=started).status_code == 202
    assert client.post(reports_url, json=rolled_back.model_dump(mode="json")).status_code == 202
    assert client.get(plan_url).status_code == 204
