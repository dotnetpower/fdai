"""Persist the Hub data model.

Every write locks the installation row first, so one installation's changes are serialized, and
appends to the hash-chained audit in the same transaction.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from typing import Literal, Self, assert_never

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from fdai_deployment_cli.lifecycle_configuration import (
    ConfigurationValidationError,
    resolve_configuration_layers,
)
from fdai_deployment_cli.lifecycle_configuration_sealing import encryption_key_digest
from fdai_deployment_cli.lifecycle_plan import SuppressionWindow
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from fdai_lifecycle_hub import audit, domain, mapping, models, rows, schemas, signing
from fdai_lifecycle_hub.catalog import LocalCurationEvidence, ReleaseCatalog
from fdai_lifecycle_hub.configuration import ConfigurationRevisionCandidate
from fdai_lifecycle_hub.configuration_consumer import persisted_candidate
from fdai_lifecycle_hub.configuration_import_models import (
    ConfigurationImport,
    ConfigurationPlanImport,
)
from fdai_lifecycle_hub.configuration_key_store import resolve_binding
from fdai_lifecycle_hub.configuration_keys import KeyBindingError
from fdai_lifecycle_hub.enrollment import EnrollmentRequest, EnrollmentStatus, KeyProofVerifier
from fdai_lifecycle_hub.entitlement_handoff import (
    GovernedEntitlementRotationReceipt,
    HubEntitlementHandoffStore,
    OpaqueEntitlementCarrierHandoff,
)
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
    ReportAttemptGapError,
    ReportConflictError,
    ReportProgressionError,
    SchemaMismatchError,
    StateRejectedError,
    UnknownPlanError,
)
from fdai_lifecycle_hub.execution_settings import (
    ApplicationBindingRequest,
    ExecutionSettingsError,
    ExecutionSettingsRequest,
    settings_digest,
    settings_record,
)
from fdai_lifecycle_hub.migrations import _versions, require_writable_schema
from fdai_lifecycle_hub.models import PlanEventKind
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.reports import (
    ROLLED_BACK,
    failure_suppressions,
    validate_report_progress,
)

_UNIQUE_VIOLATION = "23505"


class HubStore:
    """The Hub's repository. Each public method is one transaction."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self.entitlement_handoffs = HubEntitlementHandoffStore()

    def with_connection(self, connection: Connection) -> HubStore:
        """Join an owning catalog transaction without committing it from a nested store method."""
        bound = HubStore(self.engine)
        bound._sessions = sessionmaker(
            connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        bound.entitlement_handoffs = self.entitlement_handoffs
        return bound

    def stage_entitlement_handoff(
        self,
        handoff: OpaqueEntitlementCarrierHandoff | None = None,
        **kwargs: object,
    ) -> OpaqueEntitlementCarrierHandoff:
        """Stage an opaque entitlement carrier handoff onto a Hub Plan."""
        return self.entitlement_handoffs.stage_plan_handoff(handoff, **kwargs)

    def record_governed_entitlement_rotation(
        self,
        receipt: GovernedEntitlementRotationReceipt | None = None,
        **kwargs: object,
    ) -> GovernedEntitlementRotationReceipt:
        """Record a separately governed entitlement rotation receipt."""
        return self.entitlement_handoffs.record_governed_rotation(receipt, **kwargs)

    def entitlement_handoff(self, installation_id: str) -> OpaqueEntitlementCarrierHandoff | None:
        """Return the active staged entitlement carrier handoff for an installation."""
        return self.entitlement_handoffs.get_handoff(installation_id)

    def plan_entitlement_handoff(self, plan_id: str) -> OpaqueEntitlementCarrierHandoff | None:
        """Return the opaque entitlement carrier handoff staged for a Plan ID."""
        return self.entitlement_handoffs.get_plan_handoff(plan_id)

    @classmethod
    def connect(cls, url: str) -> Self:
        return cls(create_engine(url))

    def create_schema(self) -> None:
        """Create missing tables, and refuse a schema that an earlier Hub created."""

        if stale := models.stale_tables(self.engine):
            raise SchemaMismatchError(f"recreate the Hub database; earlier schema in {stale}")
        models.Base.metadata.create_all(self.engine)

    def execution_settings(self, installation_id: str) -> dict[str, object]:
        with self._sessions.begin() as session:
            row = rows.get_installation(session, installation_id)
            if row.enrollment is not EnrollmentStatus.ENROLLED:
                raise NotEnrolledError(installation_id)
            return settings_record(schemas.settings_json.validate_python(row.settings))

    def update_execution_settings(
        self,
        installation_id: str,
        command: ExecutionSettingsRequest,
        *,
        operator: str,
        now: datetime,
    ) -> dict[str, object]:
        """Change only scheduling, atomically with its audit and retry identity."""
        return self._update_settings(installation_id, command, operator=operator, now=now)

    def bind_application(
        self,
        installation_id: str,
        command: ApplicationBindingRequest,
        *,
        operator: str,
        now: datetime,
    ) -> dict[str, object]:
        """Bind an enrolled installation once, without granting ownership or issuing a Plan."""
        return self._update_settings(installation_id, command, operator=operator, now=now)

    def _update_settings(
        self,
        installation_id: str,
        command: ExecutionSettingsRequest | ApplicationBindingRequest,
        *,
        operator: str,
        now: datetime,
    ) -> dict[str, object]:
        operator = schemas.actor_name.validate_python(operator)
        binding = isinstance(command, ApplicationBindingRequest)
        prefix = "application_binding" if binding else "execution_settings"
        subject = ("application-" if binding else "settings-") + command.request_id.hex
        action = (
            "installation.application_bound"
            if binding
            else "installation.execution_settings_changed"
        )
        with self._write() as session:
            row = rows.lock_enrolled(session, installation_id)
            previous = session.scalars(
                select(models.AuditRecord).where(
                    models.AuditRecord.installation_id == installation_id,
                    models.AuditRecord.action == action,
                    models.AuditRecord.subject == subject,
                )
            ).one_or_none()
            if previous is not None:
                if (
                    previous.payload["request_digest"] != command.digest
                    or previous.payload["operator"] != operator
                ):
                    raise ExecutionSettingsError(f"{prefix}_request_conflict")
                return {
                    "changed": False,
                    "settings_digest": previous.payload["settings_digest"],
                }
            installation = mapping.to_domain(session, row)
            before = settings_digest(installation.settings)
            if command.expected_settings_digest != before:
                raise ExecutionSettingsError(f"{prefix}_revision_conflict")
            confirmation = (
                f"bind application {installation_id} {command.product} {before}"
                if isinstance(command, ApplicationBindingRequest)
                else f"update execution settings {installation_id} {before}"
            )
            if command.confirmation != confirmation:
                raise ExecutionSettingsError(f"{prefix}_confirmation_mismatch")
            if installation.open_plan is not None:
                raise ExecutionSettingsError(f"{prefix}_plan_pending")
            if isinstance(command, ApplicationBindingRequest):
                if installation.settings.product not in (None, command.product):
                    raise ExecutionSettingsError("application_binding_already_bound")
                updated = replace(installation.settings, product=command.product)
            else:
                updated = replace(
                    installation.settings,
                    windows=tuple(window.to_window() for window in command.windows),
                    plan_duration=timedelta(minutes=command.plan_duration_minutes),
                )
            digest = settings_digest(updated)
            if before != digest:
                row.settings = schemas.settings_json.dump_python(updated, mode="json")
                row.recorded_at = now
            audit.append(
                session,
                now,
                action,
                installation_id,
                subject,
                {
                    "operator": operator,
                    "request_digest": command.digest,
                    "previous_settings_digest": before,
                    "settings_digest": digest,
                    "product": updated.product,
                    "reason_code": command.reason_code,
                    "changed": before != digest,
                },
            )
            return {"changed": before != digest, "settings_digest": digest}

    def configuration_inventory(self) -> dict[str, object]:
        """Stored revision metadata only; enrollment bodies carry no signature provenance."""
        with self._sessions.begin() as session:
            installations: dict[str, list[str]] = {}
            for installation_id, digest in session.execute(
                select(
                    models.Installation.installation_id,
                    models.Installation.configuration_digest,
                )
                .where(models.Installation.enrollment == EnrollmentStatus.ENROLLED)
                .order_by(models.Installation.installation_id)
            ):
                installations.setdefault(digest, []).append(installation_id)
            revisions = session.scalars(
                select(models.ConfigurationRevision).order_by(
                    models.ConfigurationRevision.imported_at.desc(),
                    models.ConfigurationRevision.digest,
                )
            )
            return {
                "configurations": [
                    {
                        "digest": revision.digest,
                        "imported_at": revision.imported_at.isoformat(),
                        "schema_key_count": len(revision.body["schema"]),
                        "override_count": len(revision.body["entity_overrides"]),
                        "installation_ids": installations.get(revision.digest, []),
                        "signature_status": "not-recorded",
                    }
                    for revision in revisions
                ]
            }

    def drop_schema(self) -> None:
        with self.engine.begin() as connection:
            models.Base.metadata.drop_all(connection)
            _versions("lifecycle_hub").drop(connection, checkfirst=True)

    @contextmanager
    def _write(self) -> Iterator[Session]:
        try:
            with self._sessions.begin() as session:
                require_writable_schema(session.connection())
                yield session
        except IntegrityError as error:
            if not _is_unique_violation(error):
                raise
            raise ConcurrentWriteError("a concurrent write committed first; retry") from error

    def request_enrollment(
        self,
        request: EnrollmentRequest,
        *,
        verify: KeyProofVerifier,
        now: datetime,
        requested_by: str | None = None,
        requested_via: Literal["agent", "operator"] | None = None,
    ) -> None:
        """Record a pending request, or audit why its key proof fails and raise."""

        installation_id = request.installation.installation_id
        details = {"installation_key_id": request.installation_key_id}
        if requested_by is not None:
            details["requested_by"] = schemas.actor_name.validate_python(requested_by)
            details["requested_via"] = requested_via or "operator"
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
            row = rows.lock_pending(session, installation_id)
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
            row = rows.lock_pending(session, installation_id)
            row.enrollment = EnrollmentStatus.REJECTED
            row.recorded_at = now
            audit.append(
                session, now, "enrollment.rejected", installation_id, installation_id, details
            )

    def enrollment_status(self, installation_id: str) -> EnrollmentStatus:
        with self._sessions() as session:
            return rows.get_installation(session, installation_id).enrollment

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

        if evidence.native_creation_receipt_digest is not None:
            raise ValueError("native ownership requires separate verified operator acceptance")
        operator = schemas.actor_name.validate_python(operator)
        recorded = schemas.ownership_json.dump_python(
            evidence, mode="json", exclude={"native_creation_receipt_digest"}
        )
        with self._write() as session:
            rows.lock_enrolled(session, installation_id)
            row = rows.entity_row(session, installation_id, entity_id)
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
        initial_release: str | None = None,
    ) -> str:
        """Give an Entity with proven ownership its settings, which makes it managed.

        Returns the override range covering the running or explicitly selected first Release.
        """

        operator = schemas.actor_name.validate_python(operator)
        with self._write() as session:
            installation = mapping.to_domain(session, rows.lock_enrolled(session, installation_id))
            row = rows.entity_row(session, installation_id, entity_id)
            if (gap := mapping.domain_entity(row).ownership_gap) is not None:
                raise OwnershipUnprovenError(f"{entity_id}: {gap}")
            if (state := installation.reported.entities.get(entity_id)) is None:
                raise EntityNotReportedError(entity_id)
            release_id = state.release_id
            if release_id is None:
                if initial_release is None:
                    raise EntitySettingsRejectedError("initial_release_required")
                release_id = initial_release
            elif initial_release is not None:
                raise EntitySettingsRejectedError("initial_release_requires_uninstalled_entity")
            try:
                covering = resolve_configuration_layers(
                    release_version=release_id,
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
            if initial_release is not None:
                details["initial_release"] = initial_release
            audit.append(session, now, "entity.managed", installation_id, entity_id, details)
            return covering

    def record_state(
        self, installation_id: str, state: domain.ReportedState, *, now: datetime
    ) -> None:
        """Make `state` current, or raise StateRejectedError for a stale or mismatched one."""

        with self._write() as session:
            row = rows.lock_enrolled(session, installation_id)
            installation = mapping.to_domain(session, row)
            try:
                updated = installation.with_reported(state)
            except domain.StaleStateError as error:
                raise StateRejectedError(str(error), stale=True) from error
            except ValueError as error:
                raise StateRejectedError(str(error), stale=False) from error
            row.state_reports.add(mapping.state_report_row(installation_id, updated.reported, now))
            row.recorded_at = now
            audit.append(session, now, "state.recorded", installation_id, state.digest)

    def add_suppression(
        self, installation_id: str, window: SuppressionWindow, *, now: datetime
    ) -> None:
        """Add a suppression. The API stops serving a Plan it covers while it is active."""

        with self._write() as session:
            row = rows.lock_enrolled(session, installation_id)
            installation = mapping.to_domain(session, row).suppressed(window, now)
            rows.store_suppressions(row, installation, now)
            _audit_suppression(session, now, installation_id, window)

    def lift_suppressions(self, installation_id: str, scope: str, *, now: datetime) -> None:
        with self._write() as session:
            row = rows.lock_enrolled(session, installation_id)
            rows.store_suppressions(row, mapping.to_domain(session, row).lifted(scope, now), now)
            audit.append(session, now, "suppression.lifted", installation_id, scope)

    def load(self, installation_id: str) -> domain.Installation:
        with self._sessions() as session:
            return mapping.to_domain(session, rows.get_installation(session, installation_id))

    def list_installations(self) -> tuple[domain.InstallationOverview, ...]:
        """Every enrolled installation and its latest recompute outcome, for the list screen."""

        with self._sessions() as session:
            installation_rows = session.scalars(
                select(models.Installation)
                .where(models.Installation.enrollment == EnrollmentStatus.ENROLLED)
                .order_by(models.Installation.installation_id)
            ).all()
            return tuple(
                domain.InstallationOverview(
                    installation=mapping.to_domain(session, row),
                    last_evaluation=_latest_evaluation(session, row),
                )
                for row in installation_rows
            )

    def list_pending_enrollments(self) -> tuple[domain.PendingEnrollment, ...]:
        """Every pending enrollment request, oldest first, for an approver to review."""

        with self._sessions() as session:
            pending_rows = session.scalars(
                select(models.Installation)
                .where(models.Installation.enrollment == EnrollmentStatus.PENDING)
                .order_by(models.Installation.requested_at)
            )
            return tuple(_pending_enrollment(session, row) for row in pending_rows)

    def pending_enrollment(self, installation_id: str) -> domain.PendingEnrollment:
        with self._sessions() as session:
            row = rows.get_installation(session, installation_id)
            if row.enrollment is not EnrollmentStatus.PENDING:
                raise NotPendingError(f"{installation_id} is {row.enrollment.value}")
            return _pending_enrollment(session, row)

    def plan_detail(self, installation_id: str, plan_id: str) -> domain.PlanRecord:
        """A Plan's status, events, and the recomputes that targeted it, by id."""

        with self._sessions() as session:
            plan = session.get(models.Plan, plan_id)
            if plan is None or plan.installation_id != installation_id:
                raise UnknownPlanError(plan_id)
            event_rows = session.scalars(plan.events.select().order_by(models.PlanEvent.id)).all()
            status = (
                domain.PlanStatus.SUPERSEDED
                if any(event.kind == PlanEventKind.SUPERSEDED for event in event_rows)
                else domain.PlanStatus.OPEN
            )
            evaluation_rows = session.scalars(
                select(models.PlanEvaluation)
                .where(models.PlanEvaluation.plan_id == plan_id)
                .order_by(models.PlanEvaluation.id)
            )
            return domain.PlanRecord(
                plan=mapping.issued_plan(plan),
                status=status,
                events=tuple(
                    domain.PlanEventRecord(kind=event.kind, recorded_at=event.recorded_at)
                    for event in event_rows
                ),
                evaluations=tuple(mapping.evaluation(row) for row in evaluation_rows),
            )

    def plan_reports(self, plan_id: str) -> tuple[schemas.RecordedReport, ...]:
        """Every execution report on one Plan, in the order received."""

        with self._sessions() as session:
            return _plan_reports(session, plan_id)

    def plan_detail_view(self, installation_id: str, plan_id: str) -> dict[str, object]:
        """Load one Plan's detail and execution reports in a single database session."""

        with self._sessions() as session:
            plan = session.get(models.Plan, plan_id)
            if plan is None or plan.installation_id != installation_id:
                raise UnknownPlanError(plan_id)
            event_rows = session.scalars(plan.events.select().order_by(models.PlanEvent.id)).all()
            status = (
                domain.PlanStatus.SUPERSEDED
                if any(event.kind == PlanEventKind.SUPERSEDED for event in event_rows)
                else domain.PlanStatus.OPEN
            )
            evaluation_rows = session.scalars(
                select(models.PlanEvaluation)
                .where(models.PlanEvaluation.plan_id == plan_id)
                .order_by(models.PlanEvaluation.id)
            )
            record = domain.PlanRecord(
                plan=mapping.issued_plan(plan),
                status=status,
                events=tuple(
                    domain.PlanEventRecord(kind=event.kind, recorded_at=event.recorded_at)
                    for event in event_rows
                ),
                evaluations=tuple(mapping.evaluation(row) for row in evaluation_rows),
            )
            return schemas.plan_record(
                record,
                installation_id=installation_id,
                reports=_plan_reports(session, plan_id),
            )

    def enrollment_statuses(self, installation_ids: frozenset[str]) -> dict[str, str]:
        """Fetch enrollment status for bound installations in one lightweight query."""

        if not installation_ids:
            return {}
        with self._sessions() as session:
            matched = session.execute(
                select(models.Installation.installation_id, models.Installation.enrollment).where(
                    models.Installation.installation_id.in_(installation_ids),
                    models.Installation.enrollment.in_(
                        (EnrollmentStatus.PENDING, EnrollmentStatus.ENROLLED)
                    ),
                )
            )
            return {installation_id: enrollment.value for installation_id, enrollment in matched}

    def recompute(
        self, installation_id: str, planner: domain.Planner, *, now: datetime
    ) -> domain.PlanOutcome:
        """Plan under the installation lock and record the outcome and every check."""

        return self._recompute(
            installation_id,
            lambda _session, _row, installation: planner(installation, now),
            now=now,
        )

    def recompute_configuration(
        self,
        installation_id: str,
        candidate: ConfigurationRevisionCandidate,
        *,
        binding_version: int,
        catalog: ReleaseCatalog,
        key: signing.HubSigningKey,
        now: datetime,
    ) -> domain.PlanOutcome:
        """Plan using durable approved keys, never the transient candidate's asserted trust.

        Entity mappings, classification and retained history remain independent composition
        inputs. This does not import a package or advance a durable configuration chain head.
        """

        def evaluate(
            session: Session,
            row: models.Installation,
            installation: domain.Installation,
        ) -> domain.PlanOutcome:
            binding = resolve_binding(session, row, binding_version, now)
            recipient = X25519PublicKey.from_public_bytes(
                bytes.fromhex(binding.installation_encryption_key)
            )
            trusted_key = Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(binding.configuration_signing_key)
            )
            if (
                candidate.installation_id != installation_id
                or candidate.configuration_key.public_bytes_raw() != trusted_key.public_bytes_raw()
                or candidate.installation_key_digest != encryption_key_digest(recipient)
            ):
                raise KeyBindingError("configuration_binding_mismatch")
            bound = replace(
                candidate,
                configuration_key=trusted_key,
                installation_key_digest=encryption_key_digest(recipient),
            )
            if now + installation.settings.plan_duration > binding.binding_expires_at:
                raise KeyBindingError("configuration_binding_expires_before_plan")
            if installation.open_plan is not None:
                previous_trust = session.get(
                    models.ConfigurationPlanTrust, installation.open_plan.plan_id
                )
                if previous_trust is None or previous_trust.request_digest != binding.digest:
                    installation = replace(installation, open_plan=None)
            return plan_next(
                installation,
                now,
                catalog=catalog,
                key=key,
                configuration_revision=bound,
            )

        return self._recompute(
            installation_id,
            evaluate,
            now=now,
            configuration_binding_version=binding_version,
            local_curation=catalog.local_curation,
        )

    def recompute_persisted(
        self,
        installation_id: str,
        *,
        catalog: ReleaseCatalog,
        key: signing.HubSigningKey,
        now: datetime,
    ) -> domain.PlanOutcome:
        """The configured default: durable activation selects an upgrade input, not authority."""

        def evaluate(
            session: Session,
            row: models.Installation,
            installation: domain.Installation,
        ) -> domain.PlanOutcome:
            selected = persisted_candidate(session, row, catalog, now)
            candidate = selected[0] if selected else None
            if selected is not None:
                binding = resolve_binding(session, row, selected[1], now)
                if now + installation.settings.plan_duration > binding.binding_expires_at:
                    raise KeyBindingError("configuration_binding_expires_before_plan")
                if (
                    installation.open_plan is not None
                    and installation.open_plan.configuration_digest == selected[0].package.digest
                ):
                    retained = session.get(ConfigurationPlanImport, installation.open_plan.plan_id)
                    imported = session.get(ConfigurationImport, selected[0].package.digest)
                    if (
                        retained is None
                        or imported is None
                        or retained.import_digest != imported.digest
                        or retained.receipt_digest != imported.receipt_digest
                        or session.get(
                            models.ConfigurationPlanTrust, installation.open_plan.plan_id
                        )
                        is None
                    ):
                        raise KeyBindingError("configuration_plan_receipt_unprovable")
            return plan_next(
                installation, now, catalog=catalog, key=key, configuration_revision=candidate
            )

        return self._recompute(
            installation_id, evaluate, now=now, local_curation=catalog.local_curation
        )

    def _recompute(
        self,
        installation_id: str,
        evaluate: Callable[[Session, models.Installation, domain.Installation], domain.PlanOutcome],
        *,
        now: datetime,
        configuration_binding_version: int | None = None,
        local_curation: LocalCurationEvidence | None = None,
    ) -> domain.PlanOutcome:
        failure: KeyBindingError | None = None
        with self._write() as session:
            row = rows.lock_enrolled(session, installation_id)
            installation = mapping.to_domain(session, row)
            outcome: domain.PlanOutcome
            if _native_transition_holds_planning(session, installation, now):
                outcome = domain.NoEligibleRelease(())
            else:
                try:
                    outcome = evaluate(session, row, installation)
                except KeyBindingError as error:
                    failure = error
                    # Keep the denial durable without withdrawing an unrelated legacy Plan.
                    outcome = domain.NoEligibleRelease(())
                    audit.append(
                        session,
                        now,
                        "configuration.keys.denied",
                        installation_id,
                        installation_id,
                        {"operation": "planning", "reason": str(error)},
                    )
            evaluation = mapping.evaluation_row(outcome, now)
            match outcome:
                case domain.Issued(plan=plan):
                    rows.supersede(session, installation.open_plan, now)
                    issued = mapping.plan_row(domain.IssuedPlan.from_signed(plan), now)
                    row.plans.add(issued)
                    issued.events.add(models.PlanEvent(kind=PlanEventKind.ISSUED, recorded_at=now))
                    imported = session.get(ConfigurationImport, plan.configuration_revision_digest)
                    if imported is not None:
                        session.add(
                            ConfigurationPlanImport(
                                plan_id=plan.plan_id,
                                import_digest=imported.digest,
                                receipt_digest=imported.receipt_digest,
                            )
                        )
                    selected_version = (
                        imported.binding_version if imported else configuration_binding_version
                    )
                    if selected_version is not None:
                        binding = resolve_binding(session, row, selected_version, now)
                        session.add(
                            models.ConfigurationPlanTrust(
                                plan_id=plan.plan_id,
                                installation_id=installation_id,
                                binding_version=binding.version,
                                request_digest=binding.digest,
                            )
                        )
                    row.last_sequence = plan.sequence
                    evaluation.plan_id = plan.plan_id
                    evaluation.target_release_id = plan.target_release_id
                case domain.Unchanged(plan=open_plan):
                    evaluation.plan_id = open_plan.plan_id
                    evaluation.target_release_id = open_plan.target_release_id
                case domain.Waiting(release_id=release_id):
                    rows.supersede(session, installation.open_plan, now)
                    evaluation.target_release_id = release_id
                case domain.NoEligibleRelease() | domain.UpToDate() | domain.NoManagedEntity():
                    if (
                        failure is None
                        or installation.open_plan is None
                        or session.get(
                            models.ConfigurationPlanTrust, installation.open_plan.plan_id
                        )
                        is not None
                        or session.get(ConfigurationPlanImport, installation.open_plan.plan_id)
                        is not None
                    ):
                        rows.supersede(session, installation.open_plan, now)
                case _:
                    assert_never(outcome)
            row.evaluations.add(evaluation)
            audit.append(
                session,
                now,
                "plan.evaluated",
                installation_id,
                evaluation.plan_id or installation_id,
                {
                    "outcome": outcome.kind,
                    "target": evaluation.target_release_id,
                    **({"local_curation": asdict(local_curation)} if local_curation else {}),
                },
            )
        if failure is not None:
            raise failure
        return outcome

    def current_plan(self, installation_id: str, *, now: datetime) -> domain.IssuedPlan | None:
        """Read an eligible open Plan serialized with key approval, rotation and revocation."""

        with self._sessions() as session:
            row = rows.lock_installation(session, installation_id)
            if row.enrollment is not EnrollmentStatus.ENROLLED:
                return None
            plan = mapping.open_plan(session, installation_id)
            suppressions = schemas.suppressions_json.validate_python(row.suppressions)
            return _eligible_open_plan(session, row, plan, suppressions=suppressions, now=now)

    def installation_detail_view(self, installation_id: str, *, now: datetime) -> dict[str, object]:
        """Load enrolled installation detail, open Plan, evaluation, and reports in one session."""

        with self._sessions() as session:
            row = rows.lock_installation(session, installation_id)
            if row.enrollment is not EnrollmentStatus.ENROLLED:
                raise NotEnrolledError(installation_id)
            installation = mapping.to_domain(session, row)
            open_plan = _eligible_open_plan(
                session,
                row,
                installation.open_plan,
                suppressions=installation.suppressions,
                now=now,
            )
            last_evaluation = _latest_evaluation(session, row)
            report_rows = session.scalars(
                select(models.PlanReport)
                .join(models.Plan)
                .where(models.Plan.installation_id == installation_id)
                .order_by(models.PlanReport.id)
            )
            reports = tuple(
                schemas.RecordedReport.model_validate(record, from_attributes=True)
                for record in report_rows
            )
            return schemas.installation_detail_record(
                installation,
                enrollment=row.enrollment,
                open_plan=open_plan,
                last_evaluation=last_evaluation,
                reports=reports,
                now=now,
            )

    def record_report(
        self, installation_id: str, plan_id: str, report: schemas.PlanReport, *, now: datetime
    ) -> bool:
        """Store one report. Returns False when the identical report already exists.

        A new `rolled-back` report also holds every Entity of the Plan in the same transaction.
        """

        with self._write() as session:
            row = rows.lock_installation(session, installation_id)
            plan = session.get(models.Plan, plan_id)
            if plan is None or plan.installation_id != installation_id:
                raise UnknownPlanError(plan_id)
            issued = mapping.issued_plan(plan)
            if report.exact_plan_digest not in {None, issued.digest}:
                raise PlanDigestMismatchError(f"report names other bytes than Plan {plan_id}")
            existing = session.scalars(
                plan.reports.select().where(models.PlanReport.attempt == report.attempt)
            ).one_or_none()
            if existing is not None:
                if schemas.PlanReport.model_validate(existing, from_attributes=True) != report:
                    raise ReportConflictError(f"attempt {report.attempt} was already reported")
                return False
            previous = session.scalars(
                plan.reports.select().order_by(models.PlanReport.attempt.desc()).limit(1)
            ).one_or_none()
            expected_attempt = 1 if previous is None else previous.attempt + 1
            if report.attempt > expected_attempt:
                raise ReportAttemptGapError(f"report skipped required attempt {expected_attempt}")
            try:
                validate_report_progress(previous, report)
            except ValueError as error:
                raise ReportProgressionError(str(error)) from error
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
            if report.outcome == ROLLED_BACK:
                installation = mapping.to_domain(session, row)
                for window in failure_suppressions(issued, now):
                    installation = installation.suppressed(window, now)
                    _audit_suppression(session, now, installation_id, window)
                rows.store_suppressions(row, installation, now)
            return True

    def last_evaluation(self, installation_id: str) -> domain.Evaluation | None:
        with self._sessions() as session:
            row = rows.get_installation(session, installation_id)
            return _latest_evaluation(session, row)

    def reports(self, installation_id: str) -> tuple[schemas.RecordedReport, ...]:
        """Every execution report on the installation's Plans, in the order received."""

        with self._sessions() as session:
            rows.get_installation(session, installation_id)
            records = session.scalars(
                select(models.PlanReport)
                .join(models.Plan)
                .where(models.Plan.installation_id == installation_id)
                .order_by(models.PlanReport.id)
            )
            return tuple(
                schemas.RecordedReport.model_validate(record, from_attributes=True)
                for record in records
            )

    def audit_chain_intact(self) -> bool:
        with self._sessions() as session:
            return audit.chain_intact(session)

    def audit_records(
        self, *, installation_id: str | None = None, limit: int = 100
    ) -> dict[str, object]:
        """Read-only hash-chained audit records, newest first, with chain integrity state."""

        if not 1 <= limit <= 200:
            raise ValueError("audit limit must be between 1 and 200")
        with self._sessions() as session:
            intact = audit.chain_intact(session)
            stmt = select(models.AuditRecord).order_by(models.AuditRecord.sequence.desc())
            if installation_id is not None:
                stmt = stmt.where(models.AuditRecord.installation_id == installation_id)
            records = session.scalars(stmt.limit(limit)).all()
            return {
                "chain_intact": intact,
                "records": [
                    {
                        "sequence": record.sequence,
                        "recorded_at": record.recorded_at.isoformat(),
                        "action": record.action,
                        "installation_id": record.installation_id,
                        "subject": record.subject,
                        "previous_hash": record.previous_hash,
                        "record_hash": record.record_hash,
                    }
                    for record in records
                ],
            }


def _is_unique_violation(error: IntegrityError) -> bool:
    """Only a duplicate key means another writer won. Other violations are faults."""

    if getattr(error.orig, "sqlstate", None) == _UNIQUE_VIOLATION:  # PostgreSQL
        return True
    return str(error.orig).startswith("UNIQUE constraint failed")  # SQLite


def _pending_enrollment(session: Session, row: models.Installation) -> domain.PendingEnrollment:
    # Records written before `requested_via` existed came only from the operator route.
    payload = session.scalars(
        select(models.AuditRecord.payload)
        .where(
            models.AuditRecord.action == "enrollment.requested",
            models.AuditRecord.installation_id == row.installation_id,
        )
        .order_by(models.AuditRecord.sequence.desc())
        .limit(1)
    ).one_or_none()
    requested_by = (payload or {}).get("requested_by")
    requested_via = (payload or {}).get("requested_via", "operator")
    return domain.PendingEnrollment(
        installation=mapping.to_domain(session, row),
        installation_key_id=signing.installation_key_id(row.installation_key),
        requested_at=row.requested_at,
        requested_by=requested_by if isinstance(requested_by, str) else None,
        requested_via=requested_via
        if requested_by and requested_via in ("agent", "operator")
        else None,
    )


def _native_transition_holds_planning(
    session: Session, installation: domain.Installation, now: datetime
) -> bool:
    """Keep an approved transition or state repair Plan-free until completion or expiry."""

    records = session.scalars(
        select(models.AuditRecord)
        .where(
            models.AuditRecord.action.in_(
                (
                    "entity.native_transition_approved",
                    "entity.native_transition_state_reconciliation_approved",
                )
            ),
            models.AuditRecord.installation_id == installation.installation_id,
        )
        .order_by(models.AuditRecord.sequence.desc())
        .limit(2)
    )
    for record in records:
        if record.action == "entity.native_transition_state_reconciliation_approved":
            completed = session.scalar(
                select(models.AuditRecord.sequence).where(
                    models.AuditRecord.installation_id == installation.installation_id,
                    models.AuditRecord.action == "entity.native_transition_state_reconciled",
                    models.AuditRecord.subject == record.subject,
                )
            )
            if completed is not None:
                continue
        payload = record.payload
        source_digest = payload.get(
            "reported_state_digest",
            payload.get("source_hub_reported_state_digest"),
        )
        if source_digest != installation.reported.digest:
            continue
        expires_at = payload.get("expires_at")
        if not isinstance(expires_at, str):
            return True
        try:
            expires = datetime.fromisoformat(expires_at)
        except ValueError:
            return True
        if expires.utcoffset() is None or now < expires:
            return True
    return False


def _latest_evaluation(session: Session, row: models.Installation) -> domain.Evaluation | None:
    evaluation = session.scalars(
        row.evaluations.select().order_by(models.PlanEvaluation.id.desc()).limit(1)
    ).one_or_none()
    return mapping.evaluation(evaluation) if evaluation is not None else None


def _plan_reports(session: Session, plan_id: str) -> tuple[schemas.RecordedReport, ...]:
    records = session.scalars(
        select(models.PlanReport)
        .where(models.PlanReport.plan_id == plan_id)
        .order_by(models.PlanReport.id)
    )
    return tuple(
        schemas.RecordedReport.model_validate(record, from_attributes=True) for record in records
    )


def _eligible_open_plan(
    session: Session,
    row: models.Installation,
    plan: domain.IssuedPlan | None,
    *,
    suppressions: tuple[SuppressionWindow, ...],
    now: datetime,
) -> domain.IssuedPlan | None:
    if plan is None or now >= plan.expires_at:
        return None
    trust = session.get(models.ConfigurationPlanTrust, plan.plan_id)
    import_pin = session.get(ConfigurationPlanImport, plan.plan_id)
    imported = session.get(ConfigurationImport, plan.configuration_digest)
    if (
        imported is not None
        and import_pin is None
        or import_pin is not None
        and (
            trust is None
            or imported is None
            or import_pin.import_digest != plan.configuration_digest
            or import_pin.receipt_digest != imported.receipt_digest
        )
    ):
        return None
    if trust is not None:
        try:
            binding = resolve_binding(session, row, trust.binding_version, now)
        except ValueError:
            return None
        if binding.digest != trust.request_digest:
            return None
        if import_pin is not None:
            try:
                selected = persisted_candidate(session, row, None, now)
                if selected is None or selected[0].package.digest != plan.configuration_digest:
                    return None
            except ValueError:
                return None
    return None if plan.held_by(suppressions, now) else plan


def _audit_suppression(
    session: Session, now: datetime, installation_id: str, window: SuppressionWindow
) -> None:
    details = {"ends_at": window.ends_at.isoformat(), "origin": window.origin}
    if window.failed_plan_id is not None:
        details["failed_plan_id"] = window.failed_plan_id
    audit.append(session, now, "suppression.added", installation_id, window.scope, details)
