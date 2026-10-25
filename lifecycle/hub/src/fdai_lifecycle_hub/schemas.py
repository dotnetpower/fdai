"""JSON boundary: request bodies, operator input files, and the JSON form of Hub records."""

from __future__ import annotations

import binascii
from base64 import b64decode, b64encode
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Self, assert_never

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_enrollment import sign_enrollment_payload
from fdai_deployment_cli.lifecycle_plan import SuppressionWindow
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    TypeAdapter,
    model_validator,
)

from fdai_lifecycle_hub.domain import (
    CandidateCheck,
    Configuration,
    DailyWindow,
    Evaluation,
    Installation,
    InstallationOverview,
    Issued,
    IssuedPlan,
    NoEligibleRelease,
    NoManagedEntity,
    PendingEnrollment,
    PlanOutcome,
    PlanRecord,
    ReportedState,
    Settings,
    Unchanged,
    UpToDate,
    Waiting,
)
from fdai_lifecycle_hub.enrollment import EnrollmentRequest
from fdai_lifecycle_hub.entity import Entity, EntitySettings, OwnershipEvidence
from fdai_lifecycle_hub.reports import FINAL_REASONS, ReportOutcome

Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")]
ReasonCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")]
Actor = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")]
InstallationKeyId = Annotated[str, Field(pattern=r"^installation-[0-9a-f]{16}$")]


def _strict_base64(value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("expected base64 text")
    try:
        return b64decode(value, validate=True)
    except binascii.Error as error:
        raise ValueError("invalid base64") from error


Base64 = Annotated[
    bytes,
    BeforeValidator(_strict_base64),
    PlainSerializer(lambda value: b64encode(value).decode("ascii"), return_type=str),
]

settings_json = TypeAdapter(Settings)
configuration_json = TypeAdapter(Configuration)
reported_state_json = TypeAdapter(ReportedState)
ownership_json = TypeAdapter(OwnershipEvidence)
entity_settings_json = TypeAdapter(EntitySettings)
suppressions_json = TypeAdapter(tuple[SuppressionWindow, ...])
checks_json = TypeAdapter(tuple[CandidateCheck, ...])
evaluation_json = TypeAdapter(Evaluation)
actor_name = TypeAdapter(Actor)
reason_code = TypeAdapter(ReasonCode)


def maintenance_window_record(window: DailyWindow) -> dict[str, object]:
    return {
        "start": window.start.isoformat(),
        "duration_minutes": window.duration.total_seconds() / 60,
        "timezone": window.timezone,
        "allows_downtime": window.allows_downtime,
    }


class EntityDeclaration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: Identifier
    kind: Identifier


class EnrollmentPayload(BaseModel):
    """What an installation signs with its installation key to request enrollment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    installation_id: Identifier
    installation_key: Base64
    requested_at: AwareDatetime
    settings: Settings
    configuration: Configuration
    entities: tuple[EntityDeclaration, ...] = Field(min_length=1)
    reported: ReportedState

    @model_validator(mode="after")
    def _entities_are_declared_once_and_reported(self) -> Self:
        declared = [entity.entity_id for entity in self.entities]
        if len(set(declared)) != len(declared):
            raise ValueError("entity ids must be unique")
        if set(declared) != self.reported.entities.keys():
            raise ValueError("declared entities must be exactly the reported entities")
        return self


class SignedEnrollment(BaseModel):
    """The wire form of an enrollment request: the payload bytes and the proof over them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signed_payload: Base64
    proof: Base64


class ApprovalRequest(BaseModel):
    """An operator's request body to enroll a pending installation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approver: Actor
    installation_key_id: InstallationKeyId


class RejectionRequest(BaseModel):
    """An operator's request body to reject a pending enrollment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approver: Actor
    reason: ReasonCode


def sign_enrollment(
    template: Mapping[str, object], key: Ed25519PrivateKey, at: datetime
) -> EnrollmentRequest:
    """Add the installation key and `at` to `template`, sign the result, and parse it."""

    payload, proof = sign_enrollment_payload(template, key, at)
    return enrollment_request(payload, proof)


def enrollment_request(signed_payload: bytes, proof: bytes) -> EnrollmentRequest:
    """Parse the signed payload. The proof is checked later, against these exact bytes."""

    payload = EnrollmentPayload.model_validate_json(signed_payload)
    return EnrollmentRequest(
        installation=Installation(
            installation_id=payload.installation_id,
            settings=payload.settings,
            entities=frozenset(
                Entity(entity_id=entity.entity_id, kind=entity.kind) for entity in payload.entities
            ),
            configuration=payload.configuration,
            reported=payload.reported,
        ),
        installation_key=payload.installation_key,
        requested_at=payload.requested_at,
        signed_payload=signed_payload,
        proof=proof,
    )


class PlanReport(BaseModel):
    """What the installation agent reports after one attempt at one Plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt: int = Field(ge=1)
    outcome: ReportOutcome
    reason_code: ReasonCode
    exact_plan_digest: Digest | None
    summary: str = Field(max_length=2000)
    reported_at: AwareDatetime

    @model_validator(mode="after")
    def _outcome_rules(self) -> Self:
        if self.outcome != "rejected" and self.exact_plan_digest is None:
            raise ValueError(f"a {self.outcome} report must carry exact_plan_digest")
        allowed = FINAL_REASONS.get(self.outcome)
        if allowed is not None and self.reason_code not in allowed:
            raise ValueError(f"a {self.outcome} report needs reason_code in {sorted(allowed)}")
        return self


class RecordedReport(PlanReport):
    """A stored report, with the Plan it belongs to and when the Hub received it."""

    plan_id: str
    received_at: AwareDatetime


def outcome_record(outcome: PlanOutcome) -> dict[str, Any]:
    record: dict[str, Any] = {
        "outcome": outcome.kind,
        "checks": checks_json.dump_python(outcome.checks, mode="json"),
    }
    match outcome:
        case Issued(plan=plan) | Unchanged(plan=plan):
            record |= {"plan_id": plan.plan_id, "target": plan.target_release_id}
        case Waiting(release_id=release_id):
            record |= {"target": release_id}
        case NoEligibleRelease() | UpToDate() | NoManagedEntity():
            pass
        case _:
            assert_never(outcome)
    return record


def installation_summary_record(overview: InstallationOverview, *, now: datetime) -> dict[str, Any]:
    """One row of the operator's installation list: subscription, target, and health."""

    installation = overview.installation
    evaluation = overview.last_evaluation
    window = installation.next_window(now)
    return {
        "installation_id": installation.installation_id,
        "channel": installation.settings.channel,
        "version_range": installation.settings.version_range,
        "current_release": (
            installation.current_release if installation.managed_entity_ids else None
        ),
        "target_release_id": evaluation.target_release_id if evaluation else None,
        "outcome": evaluation.outcome if evaluation else None,
        "health": installation.overall_health,
        "next_window_starts_at": window.starts_at.isoformat() if window else None,
        "next_window_ends_at": window.ends_at.isoformat() if window else None,
        # An operator can't tell "about to start" from "already open" by starts_at alone, since
        # a currently open daily window's starts_at already lies in the past.
        "next_window_open": window is not None and window.starts_at <= now,
        "last_evaluated_at": evaluation.evaluated_at.isoformat() if evaluation else None,
    }


def installation_detail_record(
    installation: Installation,
    *,
    enrollment: str,
    open_plan: IssuedPlan | None,
    last_evaluation: Evaluation | None,
    reports: tuple[RecordedReport, ...],
    now: datetime,
) -> dict[str, Any]:
    """Everything the installation detail screen shows: settings, Entities, and the open Plan."""

    reported = installation.reported
    return {
        "installation_id": installation.installation_id,
        "enrollment": enrollment,
        "settings": {
            "channel": installation.settings.channel,
            "version_range": installation.settings.version_range,
            "region": installation.settings.region,
            "allowed_regions": sorted(installation.settings.allowed_regions),
            "windows": [
                maintenance_window_record(window) for window in installation.settings.windows
            ],
        },
        "configuration_digest": installation.configuration.digest,
        "reported_at": reported.observed_at.isoformat(),
        "schema_revision": reported.schema_revision,
        "current_release": (
            installation.current_release if installation.managed_entity_ids else None
        ),
        "health": installation.overall_health,
        "entities": [_entity_record(entity, reported) for entity in _sorted_entities(installation)],
        "suppressions": suppressions_json.dump_python(
            tuple(
                window
                for window in installation.suppressions
                if window.starts_at <= now < window.ends_at
            ),
            mode="json",
        ),
        "open_plan": (
            {
                "plan_id": open_plan.plan_id,
                "sequence": open_plan.sequence,
                "target_release_id": open_plan.target_release_id,
                "expires_at": open_plan.expires_at.isoformat(),
            }
            if open_plan
            else None
        ),
        "last_evaluation": (
            evaluation_json.dump_python(last_evaluation, mode="json") if last_evaluation else None
        ),
        "reports": [report.model_dump(mode="json") for report in reports],
    }


def plan_record(
    record: PlanRecord, *, installation_id: str, reports: tuple[RecordedReport, ...]
) -> dict[str, Any]:
    """The Plan detail screen: its status, phase events, reports, and the recomputes behind it."""

    plan = record.plan
    return {
        "plan_id": plan.plan_id,
        "installation_id": installation_id,
        "sequence": plan.sequence,
        "plan_type": plan.plan_type,
        "target_release_id": plan.target_release_id,
        "source_state_digest": plan.source_state_digest,
        "configuration_digest": plan.configuration_digest,
        "hub_key_id": plan.hub_key_id,
        "entity_ids": sorted(plan.entity_ids),
        "expires_at": plan.expires_at.isoformat(),
        "status": record.status,
        "events": [
            {"kind": event.kind, "recorded_at": event.recorded_at.isoformat()}
            for event in record.events
        ],
        "evaluations": [
            evaluation_json.dump_python(evaluation, mode="json")
            for evaluation in record.evaluations
        ],
        "reports": [report.model_dump(mode="json") for report in reports],
    }


def pending_enrollment_record(pending: PendingEnrollment) -> dict[str, Any]:
    """The enrollment approval screen: the request, its declared Entities, and reported state."""

    installation = pending.installation
    reported = installation.reported
    return {
        "installation_id": installation.installation_id,
        "installation_key_id": pending.installation_key_id,
        "requested_at": pending.requested_at.isoformat(),
        "requested_by": pending.requested_by,
        "requested_via": pending.requested_via,
        "channel": installation.settings.channel,
        "version_range": installation.settings.version_range,
        "region": installation.settings.region,
        "entities": [_entity_record(entity, reported) for entity in _sorted_entities(installation)],
        "reported_at": reported.observed_at.isoformat(),
        "schema_revision": reported.schema_revision,
    }


def _sorted_entities(installation: Installation) -> list[Entity]:
    return sorted(installation.entities, key=lambda entity: entity.entity_id)


def _entity_record(entity: Entity, reported: ReportedState) -> dict[str, Any]:
    state = reported.entities.get(entity.entity_id)
    return {
        "entity_id": entity.entity_id,
        "kind": entity.kind,
        "managed": entity.managed,
        "ownership_gap": entity.ownership_gap,
        "release_id": state.release_id if state else None,
        "health": state.health if state else None,
    }
