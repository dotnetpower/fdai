"""Persist the Hub data model.

Every write locks the installation row first, so one installation's changes are serialized, and
appends to the hash-chained audit in the same transaction.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Self, assert_never

from fdai_deployment_cli.lifecycle_plan import SuppressionWindow
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from fdai_lifecycle_hub import audit, domain, mapping, models, schemas
from fdai_lifecycle_hub.errors import (
    ConcurrentWriteError,
    InstallationExistsError,
    PlanDigestMismatchError,
    ReportConflictError,
    UnknownInstallationError,
    UnknownPlanError,
)
from fdai_lifecycle_hub.models import PlanEventKind

_UNIQUE_VIOLATION = "23505"


class HubStore:
    """The Hub's repository. Each public method is one transaction."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def connect(cls, url: str) -> Self:
        return cls(create_engine(url))

    def create_schema(self) -> None:
        models.Base.metadata.create_all(self.engine)

    def drop_schema(self) -> None:
        models.Base.metadata.drop_all(self.engine)

    @contextmanager
    def _write(self) -> Iterator[Session]:
        try:
            with self._sessions.begin() as session:
                yield session
        except IntegrityError as error:
            if not _is_unique_violation(error):
                raise
            raise ConcurrentWriteError("a concurrent write committed first; retry") from error

    def register(self, installation: domain.Installation, *, now: datetime) -> None:
        if installation.open_plan is not None or installation.last_sequence:
            raise ValueError("a newly registered installation has no Plans")
        installation_id = installation.installation_id
        with self._write() as session:
            if session.get(models.Installation, installation_id) is not None:
                raise InstallationExistsError(installation_id)
            row = mapping.installation_row(session, installation, now)
            session.add(row)
            session.flush()
            row.state_reports.add(
                mapping.state_report_row(installation_id, installation.reported, now)
            )
            audit.append(session, now, "installation.registered", installation_id, installation_id)

    def record_state(
        self, installation_id: str, state: domain.ReportedState, *, now: datetime
    ) -> None:
        with self._write() as session:
            row = _lock_installation(session, installation_id)
            updated = mapping.to_domain(session, row).with_reported(state)
            row.state_reports.add(mapping.state_report_row(installation_id, updated.reported, now))
            row.recorded_at = now
            audit.append(session, now, "state.recorded", installation_id, state.digest)

    def add_suppression(
        self, installation_id: str, window: SuppressionWindow, *, now: datetime
    ) -> None:
        """Add a suppression. The API stops serving a Plan it covers while it is active."""

        with self._write() as session:
            row = _lock_installation(session, installation_id)
            _store_suppressions(row, mapping.to_domain(session, row).suppressed(window, now), now)
            details = {"ends_at": window.ends_at.isoformat()}
            audit.append(session, now, "suppression.added", installation_id, window.scope, details)

    def lift_suppressions(self, installation_id: str, scope: str, *, now: datetime) -> None:
        with self._write() as session:
            row = _lock_installation(session, installation_id)
            _store_suppressions(row, mapping.to_domain(session, row).lifted(scope, now), now)
            audit.append(session, now, "suppression.lifted", installation_id, scope)

    def load(self, installation_id: str) -> domain.Installation:
        with self._sessions() as session:
            return mapping.to_domain(session, _get_installation(session, installation_id))

    def recompute(
        self, installation_id: str, planner: domain.Planner, *, now: datetime
    ) -> domain.PlanOutcome:
        """Plan under the installation lock and record the outcome and every check."""

        with self._write() as session:
            row = _lock_installation(session, installation_id)
            installation = mapping.to_domain(session, row)
            outcome = planner(installation, now)
            evaluation = models.PlanEvaluation(
                outcome=outcome.kind,
                evaluated_at=now,
                results=[
                    models.PlanConstraintResult(
                        release_id=check.release_id,
                        reason_code=block.reason_code if block else None,
                        details=list(block.details) if block else [],
                    )
                    for check in outcome.checks
                    for block in check.blocks or (None,)
                ],
            )
            match outcome:
                case domain.Issued(plan=plan):
                    _supersede(session, installation.open_plan, now)
                    issued = mapping.plan_row(domain.IssuedPlan.from_signed(plan), now)
                    row.plans.add(issued)
                    issued.events.add(models.PlanEvent(kind=PlanEventKind.ISSUED, recorded_at=now))
                    row.last_sequence = plan.sequence
                    evaluation.plan_id = plan.plan_id
                    evaluation.target_release_id = plan.target_release_id
                case domain.Unchanged(plan=open_plan):
                    evaluation.plan_id = open_plan.plan_id
                    evaluation.target_release_id = open_plan.target_release_id
                case domain.Waiting(release_id=release_id):
                    _supersede(session, installation.open_plan, now)
                    evaluation.target_release_id = release_id
                case domain.NoEligibleRelease() | domain.UpToDate():
                    _supersede(session, installation.open_plan, now)
                case _:
                    assert_never(outcome)
            row.evaluations.add(evaluation)
            audit.append(
                session,
                now,
                "plan.evaluated",
                installation_id,
                evaluation.plan_id or installation_id,
                {"outcome": outcome.kind, "target": evaluation.target_release_id},
            )
            return outcome

    def current_plan(self, installation_id: str, *, now: datetime) -> domain.IssuedPlan | None:
        """The open Plan, unless it has expired or an active suppression covers it."""

        with self._sessions() as session:
            row = _get_installation(session, installation_id)
            plan = mapping.open_plan(session, installation_id)
            if plan is None or now >= plan.expires_at:
                return None
            suppressions = schemas.suppressions_json.validate_python(row.suppressions)
            return None if plan.held_by(suppressions, now) else plan

    def record_report(
        self, installation_id: str, plan_id: str, report: schemas.PlanReport, *, now: datetime
    ) -> bool:
        """Store one report. Returns False when the identical report already exists."""

        with self._write() as session:
            _lock_installation(session, installation_id)
            plan = session.get(models.Plan, plan_id)
            if plan is None or plan.installation_id != installation_id:
                raise UnknownPlanError(plan_id)
            if report.exact_plan_digest not in {None, mapping.issued_plan(plan).digest}:
                raise PlanDigestMismatchError(f"report names other bytes than Plan {plan_id}")
            existing = session.scalars(
                plan.reports.select().where(models.PlanReport.attempt == report.attempt)
            ).one_or_none()
            if existing is not None:
                if schemas.PlanReport.model_validate(existing, from_attributes=True) != report:
                    raise ReportConflictError(f"attempt {report.attempt} was already reported")
                return False
            plan.reports.add(models.PlanReport(**report.model_dump(), received_at=now))
            plan.events.add(models.PlanEvent(kind=PlanEventKind.REPORTED, recorded_at=now))
            audit.append(
                session,
                now,
                "plan.report_recorded",
                installation_id,
                plan_id,
                {"attempt": report.attempt, "outcome": report.outcome},
            )
            return True

    def last_evaluation(self, installation_id: str) -> domain.Evaluation | None:
        with self._sessions() as session:
            row = _get_installation(session, installation_id)
            evaluation = session.scalars(
                row.evaluations.select().order_by(models.PlanEvaluation.id.desc()).limit(1)
            ).one_or_none()
            if evaluation is None:
                return None
            return mapping.evaluation(evaluation)

    def audit_chain_intact(self) -> bool:
        with self._sessions() as session:
            return audit.chain_intact(session)


def _is_unique_violation(error: IntegrityError) -> bool:
    """Only a duplicate key means another writer won. Other violations are faults."""

    if getattr(error.orig, "sqlstate", None) == _UNIQUE_VIOLATION:  # PostgreSQL
        return True
    return str(error.orig).startswith("UNIQUE constraint failed")  # SQLite


def _get_installation(session: Session, installation_id: str) -> models.Installation:
    if (row := session.get(models.Installation, installation_id)) is None:
        raise UnknownInstallationError(installation_id)
    return row


def _lock_installation(session: Session, installation_id: str) -> models.Installation:
    row = session.get(models.Installation, installation_id, with_for_update=True)
    if row is None:
        raise UnknownInstallationError(installation_id)
    return row


def _store_suppressions(
    row: models.Installation, installation: domain.Installation, now: datetime
) -> None:
    row.suppressions = schemas.suppressions_json.dump_python(installation.suppressions, mode="json")
    row.recorded_at = now


def _supersede(session: Session, plan: domain.IssuedPlan | None, now: datetime) -> None:
    if plan is not None:
        session.add(
            models.PlanEvent(plan_id=plan.plan_id, kind=PlanEventKind.SUPERSEDED, recorded_at=now)
        )
