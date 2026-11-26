"""Row lookups, locks, and small row writes that the store's transactions share."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from fdai_lifecycle_hub import domain, models, schemas
from fdai_lifecycle_hub.enrollment import EnrollmentStatus
from fdai_lifecycle_hub.errors import (
    NotEnrolledError,
    NotPendingError,
    UnknownEntityError,
    UnknownInstallationError,
)


def get_installation(session: Session, installation_id: str) -> models.Installation:
    if (row := session.get(models.Installation, installation_id)) is None:
        raise UnknownInstallationError(installation_id)
    return row


def lock_installation(session: Session, installation_id: str) -> models.Installation:
    row = session.get(models.Installation, installation_id, with_for_update=True)
    if row is None:
        raise UnknownInstallationError(installation_id)
    return row


def lock_enrolled(session: Session, installation_id: str) -> models.Installation:
    row = lock_installation(session, installation_id)
    if row.enrollment is not EnrollmentStatus.ENROLLED:
        raise NotEnrolledError(installation_id)
    return row


def lock_pending(session: Session, installation_id: str) -> models.Installation:
    row = lock_installation(session, installation_id)
    if row.enrollment is not EnrollmentStatus.PENDING:
        raise NotPendingError(f"{installation_id} is {row.enrollment.value}")
    return row


def entity_row(session: Session, installation_id: str, entity_id: str) -> models.Entity:
    """An Entity row. Callers hold the installation lock, which serializes Entity changes."""

    if (row := session.get(models.Entity, (installation_id, entity_id))) is None:
        raise UnknownEntityError(entity_id)
    return row


def store_suppressions(
    row: models.Installation, installation: domain.Installation, now: datetime
) -> None:
    row.suppressions = schemas.suppressions_json.dump_python(installation.suppressions, mode="json")
    row.recorded_at = now


def supersede(session: Session, plan: domain.IssuedPlan | None, now: datetime) -> None:
    if plan is not None:
        session.add(
            models.PlanEvent(
                plan_id=plan.plan_id, kind=models.PlanEventKind.SUPERSEDED, recorded_at=now
            )
        )
