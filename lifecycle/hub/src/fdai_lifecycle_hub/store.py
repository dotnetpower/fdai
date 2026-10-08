"""Persist the Hub data model.

Every write locks the installation row first, so one installation's changes are serialized, and
appends to the hash-chained audit in the same transaction.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Self, assert_never

from fdai_deployment_cli.lifecycle_configuration import (
    ConfigurationValidationError,
    resolve_configuration_layers,
)
from fdai_deployment_cli.lifecycle_plan import SuppressionWindow
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from fdai_lifecycle_hub import audit, domain, mapping, models, schemas, signing
from fdai_lifecycle_hub.enrollment import EnrollmentRequest, EnrollmentStatus, KeyProofVerifier
from fdai_lifecycle_hub.entity import EntitySettings, OwnershipEvidence
from fdai_lifecycle_hub.errors import (
    ConcurrentWriteError,
    EnrollmentProofError,
    EntityManagedError,
    EntityNotReportedError,
    EntitySettingsRejectedError,
    InstallationExistsError,
    InstallationKeyMismatchError,
    NotEnrolledError,
    NotPendingError,
    OwnershipUnprovenError,
    PlanDigestMismatchError,
    ReportConflictError,
    SchemaMismatchError,
    UnknownEntityError,
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
        """Create missing tables, and refuse a schema that an earlier Hub created."""

        if stale := models.stale_tables(self.engine):
            raise SchemaMismatchError(f"recreate the Hub database; earlier schema in {stale}")
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

    def request_enrollment(
        self, request: EnrollmentRequest, *, verify: KeyProofVerifier, now: datetime
    ) -> None:
        """Record a pending request, or audit why its key proof fails and raise."""

        installation_id = request.installation.installation_id
        details = {"installation_key_id": request.installation_key_id}
        if (failure := request.proof_failure(verify, now)) is not None:
            with self._write() as session:
                audit.append(
                    session,
                    now,
                    "enrollment.proof_failed",
                    installation_id,
                    installation_id,
                    details | {"reason": failure},
                )
            raise EnrollmentProofError(failure)
        with self._write() as session:
            if session.get(models.Installation, installation_id) is not None:
                raise InstallationExistsError(installation_id)
            row = mapping.pending_installation_row(session, request, now)
            session.add(row)
            session.flush()
            reported = request.installation.reported
            row.state_reports.add(mapping.state_report_row(installation_id, reported, now))
            audit.append(
                session, now, "enrollment.requested", installation_id, installation_id, details
            )

    def approve(
        self, installation_id: str, *, approver: str, installation_key_id: str, now: datetime
    ) -> None:
        """Enroll a pending installation. Every Entity starts unmanaged."""

        approver = schemas.actor_name.validate_python(approver)
        with self._write() as session:
            row = _lock_pending(session, installation_id)
            if signing.installation_key_id(row.installation_key) != installation_key_id:
                raise InstallationKeyMismatchError(installation_key_id)
            row.enrollment = EnrollmentStatus.ENROLLED
            row.enrolled_at = row.recorded_at = now
            details = {
                "approver": approver,
                "installation_key_id": installation_key_id,
                "unmanaged_entities": sorted(entity.entity_id for entity in row.entities),
            }
            audit.append(
                session, now, "enrollment.approved", installation_id, installation_id, details
            )

    def reject(self, installation_id: str, *, approver: str, reason: str, now: datetime) -> None:
        details = {
            "approver": schemas.actor_name.validate_python(approver),
            "reason": schemas.reason_code.validate_python(reason),
        }
        with self._write() as session:
            row = _lock_pending(session, installation_id)
            row.enrollment = EnrollmentStatus.REJECTED
            row.recorded_at = now
            audit.append(
                session, now, "enrollment.rejected", installation_id, installation_id, details
            )

    def enrollment_status(self, installation_id: str) -> EnrollmentStatus:
        with self._sessions() as session:
            return _get_installation(session, installation_id).enrollment

    def record_ownership(
        self,
        installation_id: str,
        entity_id: str,
        evidence: OwnershipEvidence,
        *,
        operator: str,
        now: datetime,
    ) -> None:
        """Record an unmanaged Entity's ownership evidence, who supplied it, and its shortfall."""

        operator = schemas.actor_name.validate_python(operator)
        recorded = schemas.ownership_json.dump_python(evidence, mode="json")
        with self._write() as session:
            _lock_enrolled(session, installation_id)
            row = _entity_row(session, installation_id, entity_id)
            if mapping.domain_entity(row).managed:
                raise EntityManagedError(entity_id)
            row.ownership = recorded
            row.recorded_at = now
            details = {"operator": operator, "evidence": recorded, "reason": evidence.gap}
            audit.append(
                session, now, "entity.ownership_recorded", installation_id, entity_id, details
            )

    def manage(
        self,
        installation_id: str,
        entity_id: str,
        settings: EntitySettings,
        *,
        operator: str,
        now: datetime,
    ) -> str:
        """Give an Entity with proven ownership its settings, which makes it managed.

        Returns the override range that covers the Entity's running Release.
        """

        operator = schemas.actor_name.validate_python(operator)
        with self._write() as session:
            installation = mapping.to_domain(session, _lock_enrolled(session, installation_id))
            row = _entity_row(session, installation_id, entity_id)
            if (gap := mapping.domain_entity(row).ownership_gap) is not None:
                raise OwnershipUnprovenError(f"{entity_id}: {gap}")
            if (state := installation.reported.entities.get(entity_id)) is None:
                raise EntityNotReportedError(entity_id)
            try:
                covering = resolve_configuration_layers(
                    release_version=state.release_id,
                    configuration_schema=installation.configuration.schema,
                    environment_config=installation.configuration.environment,
                    entity_overrides=settings.overrides,
                ).version_range
            except ConfigurationValidationError as error:
                raise EntitySettingsRejectedError(f"{entity_id}: {error.code}") from error
            row.settings = schemas.entity_settings_json.dump_python(settings, mode="json")
            row.recorded_at = now
            details = {
                "operator": operator,
                "settings_digest": settings.digest,
                "covering_range": covering,
            }
            audit.append(session, now, "entity.managed", installation_id, entity_id, details)
            return covering

    def record_state(
        self, installation_id: str, state: domain.ReportedState, *, now: datetime
    ) -> None:
        with self._write() as session:
            row = _lock_enrolled(session, installation_id)
            updated = mapping.to_domain(session, row).with_reported(state)
            row.state_reports.add(mapping.state_report_row(installation_id, updated.reported, now))
            row.recorded_at = now
            audit.append(session, now, "state.recorded", installation_id, state.digest)

    def add_suppression(
        self, installation_id: str, window: SuppressionWindow, *, now: datetime
    ) -> None:
        """Add a suppression. The API stops serving a Plan it covers while it is active."""

        with self._write() as session:
            row = _lock_enrolled(session, installation_id)
            _store_suppressions(row, mapping.to_domain(session, row).suppressed(window, now), now)
            details = {"ends_at": window.ends_at.isoformat()}
            audit.append(session, now, "suppression.added", installation_id, window.scope, details)

    def lift_suppressions(self, installation_id: str, scope: str, *, now: datetime) -> None:
        with self._write() as session:
            row = _lock_enrolled(session, installation_id)
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
            row = _lock_enrolled(session, installation_id)
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
                case domain.NoEligibleRelease() | domain.UpToDate() | domain.NoManagedEntity():
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
        """An enrolled installation's open Plan, unless it expired or a suppression holds it."""

        with self._sessions() as session:
            row = _get_installation(session, installation_id)
            if row.enrollment is not EnrollmentStatus.ENROLLED:
                return None
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


def _lock_enrolled(session: Session, installation_id: str) -> models.Installation:
    row = _lock_installation(session, installation_id)
    if row.enrollment is not EnrollmentStatus.ENROLLED:
        raise NotEnrolledError(installation_id)
    return row


def _lock_pending(session: Session, installation_id: str) -> models.Installation:
    row = _lock_installation(session, installation_id)
    if row.enrollment is not EnrollmentStatus.PENDING:
        raise NotPendingError(f"{installation_id} is {row.enrollment.value}")
    return row


def _entity_row(session: Session, installation_id: str, entity_id: str) -> models.Entity:
    """An Entity row. Callers hold the installation lock, which serializes Entity changes."""

    if (row := session.get(models.Entity, (installation_id, entity_id))) is None:
        raise UnknownEntityError(entity_id)
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
