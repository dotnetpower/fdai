"""Persist the Hub data model.

Every write locks the installation row first, so one installation's changes are serialized, and
appends to the hash-chained audit in the same transaction.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from itertools import groupby
from operator import attrgetter
from typing import Self, assert_never

from fdai_deployment_cli.lifecycle_plan import ConstraintBlock
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from fdai_lifecycle_hub import audit, domain, models, schemas
from fdai_lifecycle_hub.models import PlanEventKind

_UNIQUE_VIOLATION = "23505"


class HubStoreError(Exception):
    """A request the Hub data model refuses. Never a database or programming fault."""


class UnknownInstallationError(HubStoreError, LookupError):
    pass


class InstallationExistsError(HubStoreError):
    pass


class UnknownPlanError(HubStoreError, LookupError):
    pass


class ReportConflictError(HubStoreError):
    pass


class PlanDigestMismatchError(HubStoreError):
    pass


class ConcurrentWriteError(HubStoreError):
    """Another writer committed first, for example the next audit sequence. Retry."""


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
            row = _installation_model(session, installation, now)
            session.add(row)
            session.flush()
            row.state_reports.add(_state_report_model(installation_id, installation.reported, now))
            audit.append(session, now, "installation.registered", installation_id, installation_id)

    def record_state(
        self, installation_id: str, state: domain.ReportedState, *, now: datetime
    ) -> None:
        with self._write() as session:
            row = _lock_installation(session, installation_id)
            updated = _to_domain(session, row).with_reported(state)
            row.state_reports.add(_state_report_model(installation_id, updated.reported, now))
            row.recorded_at = now
            audit.append(session, now, "state.recorded", installation_id, state.digest)

    def load(self, installation_id: str) -> domain.Installation:
        with self._sessions() as session:
            return _to_domain(session, _get_installation(session, installation_id))

    def recompute(
        self, installation_id: str, planner: domain.Planner, *, now: datetime
    ) -> domain.PlanOutcome:
        """Plan under the installation lock and record the outcome and every check."""

        with self._write() as session:
            row = _lock_installation(session, installation_id)
            installation = _to_domain(session, row)
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
                    issued = _plan_model(domain.IssuedPlan.from_signed(plan), now)
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
        """The open Plan, unless it has expired."""

        with self._sessions() as session:
            _get_installation(session, installation_id)
            plan = _open_plan(session, installation_id)
            return plan if plan is not None and now < plan.expires_at else None

    def record_report(
        self, installation_id: str, plan_id: str, report: schemas.PlanReport, *, now: datetime
    ) -> bool:
        """Store one report. Returns False when the identical report already exists."""

        with self._write() as session:
            _lock_installation(session, installation_id)
            plan = session.get(models.Plan, plan_id)
            if plan is None or plan.installation_id != installation_id:
                raise UnknownPlanError(plan_id)
            if report.exact_plan_digest not in {None, _issued_plan(plan).digest}:
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
            results = sorted(evaluation.results, key=attrgetter("id"))
            return domain.Evaluation(
                outcome=evaluation.outcome,
                target_release_id=evaluation.target_release_id,
                plan_id=evaluation.plan_id,
                checks=tuple(
                    domain.CandidateCheck(
                        release_id,
                        tuple(
                            ConstraintBlock(result.reason_code, tuple(result.details))
                            for result in group
                            if result.reason_code is not None
                        ),
                    )
                    for release_id, group in groupby(results, key=attrgetter("release_id"))
                ),
                evaluated_at=evaluation.evaluated_at,
            )

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


def _open_plan(session: Session, installation_id: str) -> domain.IssuedPlan | None:
    superseded = (
        select(models.PlanEvent.id)
        .where(models.PlanEvent.plan_id == models.Plan.plan_id)
        .where(models.PlanEvent.kind == PlanEventKind.SUPERSEDED)
    )
    row = session.scalars(
        select(models.Plan)
        .where(models.Plan.installation_id == installation_id)
        .where(~superseded.exists())
        .order_by(models.Plan.sequence.desc())
        .limit(1)
    ).one_or_none()
    return _issued_plan(row) if row is not None else None


def _issued_plan(row: models.Plan) -> domain.IssuedPlan:
    return domain.IssuedPlan(
        plan_id=row.plan_id,
        sequence=row.sequence,
        target_release_id=row.target_release_id,
        source_state_digest=row.source_state_digest,
        configuration_digest=row.configuration_digest,
        hub_key_id=row.hub_key_id,
        entity_ids=frozenset(row.entity_ids),
        expires_at=row.expires_at,
        signed_payload=row.signed_payload,
        signature=row.signature,
    )


def _supersede(session: Session, plan: domain.IssuedPlan | None, now: datetime) -> None:
    if plan is not None:
        session.add(
            models.PlanEvent(plan_id=plan.plan_id, kind=PlanEventKind.SUPERSEDED, recorded_at=now)
        )


def _to_domain(session: Session, row: models.Installation) -> domain.Installation:
    latest = session.scalars(
        row.state_reports.select().order_by(models.StateReport.observed_at.desc()).limit(1)
    ).one()
    return domain.Installation(
        installation_id=row.installation_id,
        settings=schemas.settings_json.validate_python(row.settings),
        entities=frozenset(
            domain.Entity(entity_id=entity.entity_id, kind=entity.kind, managed=entity.managed)
            for entity in row.entities
        ),
        configuration=schemas.configuration_json.validate_python(row.configuration.body),
        reported=domain.ReportedState(
            digest=latest.digest,
            schema_revision=latest.schema_revision,
            entities={
                state.entity_id: domain.EntityState(
                    release_id=state.release_id,
                    artifact_digests=frozenset(state.artifact_digests),
                    health=state.health,
                )
                for state in latest.entity_states
            },
            observed_at=latest.observed_at,
        ),
        suppressions=schemas.suppressions_json.validate_python(row.suppressions),
        last_sequence=row.last_sequence,
        open_plan=_open_plan(session, row.installation_id),
    )


def _installation_model(
    session: Session, installation: domain.Installation, now: datetime
) -> models.Installation:
    configuration = installation.configuration
    return models.Installation(
        installation_id=installation.installation_id,
        settings=schemas.settings_json.dump_python(installation.settings, mode="json"),
        suppressions=schemas.suppressions_json.dump_python(installation.suppressions, mode="json"),
        # Revisions are content-addressed, so an existing digest already holds this content.
        configuration=session.get(models.ConfigurationRevision, configuration.digest)
        or models.ConfigurationRevision(
            digest=configuration.digest,
            body=schemas.configuration_json.dump_python(configuration, mode="json"),
            imported_at=now,
        ),
        enrolled_at=now,
        recorded_at=now,
        entities=[
            models.Entity(
                entity_id=entity.entity_id,
                kind=entity.kind,
                managed=entity.managed,
                recorded_at=now,
            )
            for entity in installation.entities
        ],
    )


def _plan_model(plan: domain.IssuedPlan, now: datetime) -> models.Plan:
    return models.Plan(
        plan_id=plan.plan_id,
        sequence=plan.sequence,
        target_release_id=plan.target_release_id,
        source_state_digest=plan.source_state_digest,
        configuration_digest=plan.configuration_digest,
        hub_key_id=plan.hub_key_id,
        entity_ids=sorted(plan.entity_ids),
        signed_payload=plan.signed_payload,
        signature=plan.signature,
        issued_at=now,
        expires_at=plan.expires_at,
    )


def _state_report_model(
    installation_id: str, state: domain.ReportedState, now: datetime
) -> models.StateReport:
    return models.StateReport(
        digest=state.digest,
        schema_revision=state.schema_revision,
        observed_at=state.observed_at,
        recorded_at=now,
        entity_states=[
            models.EntityReportedState(
                installation_id=installation_id,
                entity_id=entity_id,
                release_id=entity.release_id,
                artifact_digests=sorted(entity.artifact_digests),
                health=entity.health,
            )
            for entity_id, entity in sorted(state.entities.items())
        ],
    )
