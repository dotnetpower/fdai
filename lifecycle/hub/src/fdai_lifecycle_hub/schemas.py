"""JSON boundary: request bodies, operator input files, and the JSON form of Hub records."""

from __future__ import annotations

import binascii
from base64 import b64decode, b64encode
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal, Self, assert_never

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.contracts import canonical_bytes
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
    Evaluation,
    Installation,
    Issued,
    NoEligibleRelease,
    NoManagedEntity,
    PlanOutcome,
    ReportedState,
    Settings,
    Unchanged,
    UpToDate,
    Waiting,
)
from fdai_lifecycle_hub.enrollment import EnrollmentRequest
from fdai_lifecycle_hub.entity import Entity, EntitySettings, OwnershipEvidence
from fdai_lifecycle_hub.signing import raw_public_key

Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")]
ReasonCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")]
Actor = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")]


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


def sign_enrollment(
    template: Mapping[str, object], key: Ed25519PrivateKey, at: datetime
) -> EnrollmentRequest:
    """Add the installation key and `at` to `template`, sign the result, and parse it."""

    fields = {
        "installation_key": b64encode(raw_public_key(key)).decode("ascii"),
        "requested_at": at.isoformat(),
    }
    payload = canonical_bytes({**template, **fields})
    return enrollment_request(payload, key.sign(payload))


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
    outcome: Literal["dry-run-admitted", "rejected"]
    reason_code: ReasonCode
    exact_plan_digest: Digest | None
    summary: str = Field(max_length=2000)
    reported_at: AwareDatetime

    @model_validator(mode="after")
    def _admitted_names_the_plan_bytes(self) -> Self:
        if self.outcome == "dry-run-admitted" and self.exact_plan_digest is None:
            raise ValueError("an admitted report must carry exact_plan_digest")
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
