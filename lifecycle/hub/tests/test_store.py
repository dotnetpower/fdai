from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import datetime, time, timedelta
from functools import partial

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fdai_lifecycle_hub import audit, models
from fdai_lifecycle_hub.domain import (
    DailyWindow,
    EntityState,
    Health,
    Installation,
    Issued,
    IssuedPlan,
    OutcomeKind,
    Planner,
    PlanOutcome,
    StaleStateError,
    Unchanged,
    Waiting,
)
from fdai_lifecycle_hub.schemas import PlanReport
from fdai_lifecycle_hub.store import (
    ConcurrentWriteError,
    HubStore,
    InstallationExistsError,
    PlanDigestMismatchError,
    ReportConflictError,
    UnknownInstallationError,
    UnknownPlanError,
)

type Recompute = Callable[..., PlanOutcome]


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.integration)])
def hub_store(request: pytest.FixtureRequest, store: HubStore) -> Iterator[HubStore]:
    if request.param == "sqlite":
        yield store
        return
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is not set")
    postgres = HubStore.connect(url.replace("postgresql://", "postgresql+psycopg://", 1))
    postgres.drop_schema()
    postgres.create_schema()
    yield postgres
    postgres.drop_schema()


@pytest.fixture
def registered(hub_store: HubStore, installation: Installation, now: datetime) -> HubStore:
    hub_store.register(installation, now=now)
    return hub_store


@pytest.fixture
def recompute(registered: HubStore, installation: Installation, planner: Planner) -> Recompute:
    return partial(registered.recompute, installation.installation_id, planner)


def _report(issued: Issued, /, **changes: object) -> PlanReport:
    fields: dict[str, object] = {
        "attempt": 1,
        "outcome": "dry-run-admitted",
        "reason_code": "admitted",
        "exact_plan_digest": IssuedPlan.from_signed(issued.plan).digest,
        "summary": "dry run admitted",
        "reported_at": "2026-10-05T03:01:00Z",
    }
    return PlanReport.model_validate(fields | changes)


def test_registered_installation_round_trips(
    registered: HubStore, installation: Installation
) -> None:
    assert registered.load(installation.installation_id) == installation


def test_duplicate_registration_is_rejected(
    registered: HubStore, installation: Installation, now: datetime
) -> None:
    with pytest.raises(InstallationExistsError):
        registered.register(installation, now=now)


def test_unknown_installation_is_rejected(hub_store: HubStore, now: datetime) -> None:
    with pytest.raises(UnknownInstallationError):
        hub_store.load("missing")
    with pytest.raises(UnknownInstallationError):
        hub_store.current_plan("missing", now=now)


def test_issued_plan_is_served_and_advances_sequence(
    registered: HubStore, installation: Installation, recompute: Recompute, now: datetime
) -> None:
    outcome = recompute(now=now)

    assert isinstance(outcome, Issued)
    served = registered.current_plan(installation.installation_id, now=now)
    assert served is not None
    assert (served.plan_id, served.signed_payload, served.signature) == (
        outcome.plan.plan_id,
        outcome.plan.signed_payload,
        outcome.plan.signature,
    )
    assert registered.load(installation.installation_id).last_sequence == 1


def test_repeated_recompute_keeps_the_open_plan(
    registered: HubStore, installation: Installation, recompute: Recompute, now: datetime
) -> None:
    first = recompute(now=now)
    second = recompute(now=now)

    assert isinstance(first, Issued)
    assert isinstance(second, Unchanged)
    assert second.plan.plan_id == first.plan.plan_id
    assert registered.load(installation.installation_id).last_sequence == 1


def test_new_state_supersedes_the_open_plan(
    registered: HubStore, installation: Installation, recompute: Recompute, now: datetime
) -> None:
    recompute(now=now)
    moved = replace(installation.reported, digest="e" * 64, observed_at=now)
    registered.record_state(installation.installation_id, moved, now=now)

    second = recompute(now=now)

    assert isinstance(second, Issued)
    served = registered.current_plan(installation.installation_id, now=now)
    assert served is not None
    assert served.sequence == 2


def test_closed_window_withdraws_the_plan_and_records_why(
    registered: HubStore, installation: Installation, recompute: Recompute, now: datetime
) -> None:
    recompute(now=now)
    later = now + timedelta(hours=2)

    outcome = recompute(now=later)

    assert isinstance(outcome, Waiting)
    assert registered.current_plan(installation.installation_id, now=later) is None
    evaluation = registered.last_evaluation(installation.installation_id)
    assert evaluation is not None
    assert (evaluation.outcome, evaluation.target_release_id, evaluation.plan_id) == (
        OutcomeKind.WAITING,
        "1.6.0",
        None,
    )
    assert evaluation.checks == outcome.checks


def test_passing_candidate_is_recorded_without_blocks(
    registered: HubStore, installation: Installation, recompute: Recompute, now: datetime
) -> None:
    outcome = recompute(now=now)

    evaluation = registered.last_evaluation(installation.installation_id)
    assert isinstance(outcome, Issued)
    assert evaluation is not None
    assert evaluation.plan_id == outcome.plan.plan_id
    assert evaluation.checks == outcome.checks


def test_expired_plan_is_not_served(
    registered: HubStore, installation: Installation, recompute: Recompute, now: datetime
) -> None:
    outcome = recompute(now=now)

    assert isinstance(outcome, Issued)
    assert (
        registered.current_plan(installation.installation_id, now=outcome.plan.expires_at) is None
    )


def test_recorded_state_becomes_current(
    registered: HubStore, installation: Installation, now: datetime
) -> None:
    core = EntityState(release_id="1.6.0", artifact_digests=frozenset(), health=Health.HEALTHY)
    upgraded = replace(
        installation.reported,
        entities={**installation.reported.entities, "core": core},
        observed_at=now,
    )

    registered.record_state(installation.installation_id, upgraded, now=now)

    assert registered.load(installation.installation_id).reported == upgraded


def test_stale_or_incomplete_state_is_rejected(
    registered: HubStore, installation: Installation, now: datetime
) -> None:
    with pytest.raises(StaleStateError):
        registered.record_state(installation.installation_id, installation.reported, now=now)
    partial_state = replace(
        installation.reported,
        entities={"console": installation.reported.entities["console"]},
        observed_at=now,
    )
    with pytest.raises(ValueError, match="lacks managed entities"):
        registered.record_state(installation.installation_id, partial_state, now=now)


def test_reports_are_idempotent_and_conflicts_are_rejected(
    registered: HubStore, installation: Installation, recompute: Recompute, now: datetime
) -> None:
    outcome = recompute(now=now)
    assert isinstance(outcome, Issued)
    record = partial(
        registered.record_report, installation.installation_id, outcome.plan.plan_id, now=now
    )

    assert record(_report(outcome)) is True
    assert record(_report(outcome)) is False
    with pytest.raises(ReportConflictError):
        record(_report(outcome, outcome="rejected"))
    rejected = _report(outcome, attempt=2, outcome="rejected", reason_code="signature_invalid")
    assert record(rejected) is True


def test_report_for_other_plan_bytes_is_rejected(
    registered: HubStore, installation: Installation, recompute: Recompute, now: datetime
) -> None:
    outcome = recompute(now=now)
    assert isinstance(outcome, Issued)

    with pytest.raises(PlanDigestMismatchError):
        registered.record_report(
            installation.installation_id,
            outcome.plan.plan_id,
            _report(outcome, exact_plan_digest="sha256:" + "d" * 64),
            now=now,
        )


def test_report_for_unknown_or_foreign_plan_is_rejected(
    registered: HubStore,
    installation: Installation,
    recompute: Recompute,
    now: datetime,
) -> None:
    outcome = recompute(now=now)
    assert isinstance(outcome, Issued)
    other = replace(installation, installation_id="installation-beta")
    registered.register(other, now=now)

    with pytest.raises(UnknownPlanError):
        registered.record_report(installation.installation_id, "missing", _report(outcome), now=now)
    with pytest.raises(UnknownPlanError):
        registered.record_report(
            "installation-beta", outcome.plan.plan_id, _report(outcome), now=now
        )


def test_every_change_extends_an_intact_audit_chain(
    registered: HubStore,
    installation: Installation,
    recompute: Recompute,
    now: datetime,
) -> None:
    outcome = recompute(now=now)
    assert isinstance(outcome, Issued)
    registered.record_report(
        installation.installation_id, outcome.plan.plan_id, _report(outcome), now=now
    )

    assert registered.audit_chain_intact()
    with Session(registered.engine) as session, session.begin():
        session.execute(
            update(models.AuditRecord)
            .where(models.AuditRecord.sequence == 2)
            .values(subject="tampered")
        )
    assert not registered.audit_chain_intact()


def test_timestamps_read_back_as_aware_utc(
    registered: HubStore, installation: Installation, recompute: Recompute, now: datetime
) -> None:
    recompute(now=now)
    served = registered.current_plan(installation.installation_id, now=now)

    assert served is not None
    assert served.expires_at.utcoffset() == timedelta(0)


def test_daily_window_round_trips_as_local_time(
    hub_store: HubStore, installation: Installation, now: datetime
) -> None:
    window = DailyWindow(time(23, 30), timedelta(hours=2), "Asia/Seoul")
    custom = replace(installation, settings=replace(installation.settings, windows=(window,)))

    hub_store.register(custom, now=now)

    assert hub_store.load(custom.installation_id).settings.windows == (window,)


def test_configuration_revisions_are_addressed_by_content(
    registered: HubStore, installation: Installation, now: datetime
) -> None:
    twin = replace(installation, installation_id="installation-beta")
    registered.register(twin, now=now)

    stored = registered.load("installation-beta").configuration
    assert stored == installation.configuration
    assert stored.digest == installation.configuration.digest
    changed = replace(installation.configuration, environment={"replicas": 3})
    assert changed.digest != installation.configuration.digest


def test_lost_audit_race_is_reported_as_a_retryable_conflict(
    registered: HubStore,
    installation: Installation,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def collide(session: Session, *args: object, **kwargs: object) -> None:
        session.add(
            models.AuditRecord(
                sequence=1,
                recorded_at=now,
                action="collision",
                installation_id="other",
                subject="other",
                payload={},
                previous_hash="0" * 64,
                record_hash="f" * 64,
            )
        )

    monkeypatch.setattr(audit, "append", collide)
    state = replace(installation.reported, observed_at=now)

    with pytest.raises(ConcurrentWriteError):
        registered.record_state(installation.installation_id, state, now=now)
    assert registered.audit_chain_intact()


def test_other_integrity_faults_are_not_reported_as_retryable(
    registered: HubStore,
    installation: Installation,
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(session: Session, *args: object, **kwargs: object) -> None:
        session.add(models.AuditRecord(sequence=99, recorded_at=now))

    monkeypatch.setattr(audit, "append", broken)
    state = replace(installation.reported, observed_at=now)

    with pytest.raises(IntegrityError):
        registered.record_state(installation.installation_id, state, now=now)
