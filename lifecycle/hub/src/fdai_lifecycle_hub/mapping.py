"""Map between Hub ORM rows and domain records."""

from __future__ import annotations

from datetime import datetime
from itertools import groupby
from operator import attrgetter
from typing import cast

from fdai_deployment_cli.lifecycle_plan import ConstraintBlock, PlanType
from sqlalchemy import select
from sqlalchemy.orm import Session

from fdai_lifecycle_hub import domain, models, schemas
from fdai_lifecycle_hub.models import PlanEventKind


def to_domain(session: Session, row: models.Installation) -> domain.Installation:
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
        open_plan=open_plan(session, row.installation_id),
    )


def open_plan(session: Session, installation_id: str) -> domain.IssuedPlan | None:
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
    return issued_plan(row) if row is not None else None


def issued_plan(row: models.Plan) -> domain.IssuedPlan:
    return domain.IssuedPlan(
        plan_id=row.plan_id,
        sequence=row.sequence,
        plan_type=cast(PlanType, row.plan_type),
        target_release_id=row.target_release_id,
        source_state_digest=row.source_state_digest,
        configuration_digest=row.configuration_digest,
        hub_key_id=row.hub_key_id,
        entity_ids=frozenset(row.entity_ids),
        expires_at=row.expires_at,
        signed_payload=row.signed_payload,
        signature=row.signature,
    )


def evaluation(row: models.PlanEvaluation) -> domain.Evaluation:
    results = sorted(row.results, key=attrgetter("id"))
    return domain.Evaluation(
        outcome=row.outcome,
        target_release_id=row.target_release_id,
        plan_id=row.plan_id,
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
        evaluated_at=row.evaluated_at,
    )


def installation_row(
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


def plan_row(plan: domain.IssuedPlan, now: datetime) -> models.Plan:
    return models.Plan(
        plan_id=plan.plan_id,
        sequence=plan.sequence,
        plan_type=plan.plan_type,
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


def state_report_row(
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
