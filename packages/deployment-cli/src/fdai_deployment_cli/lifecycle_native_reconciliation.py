"""Contracts for one bounded legacy native-transition state reconciliation."""

from __future__ import annotations

import base64
import binascii
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_native import Digest, NativeApproval, PathId
from fdai_deployment_cli.lifecycle_native_transition import (
    HexDigest,
    NativeScopeTransitionCompletionReceipt,
    NativeScopeTransitionEntityState,
    NativeScopeTransitionReportedState,
    hub_key_id,
)

Actor = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9@._ -]{0,127}$")]


def _serialize_reported_state_timestamp(value: datetime) -> str:
    timespec = "milliseconds" if value.microsecond % 1000 == 0 else "microseconds"
    return value.astimezone(UTC).isoformat(timespec=timespec).replace("+00:00", "Z")


LegacyReportedStateTimestamp = Annotated[
    AwareDatetime,
    PlainSerializer(
        _serialize_reported_state_timestamp,
        return_type=str,
    ),
]

_IMMUTABLE_RECEIPT_TIMESTAMP_PATTERN = re.compile(
    (
        r"(?P<instant>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:"
        r"[0-9]{2}\.(?:[0-9]{3}|[0-9]{6}))(?P<zone>Z|\+00:00)"
    ),
    flags=re.ASCII,
)


class LegacyNativeScopeTransitionReportedState(BaseModel):
    """Exact legacy state whose artifact inventory retains its stored sequence."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    digest: HexDigest
    schema_revision: Annotated[int, Field(ge=0, le=2**31 - 1)]
    entities: dict[PathId, NativeScopeTransitionEntityState]
    observed_at: LegacyReportedStateTimestamp
    available_artifact_digests: tuple[Digest, ...] | None = None

    @model_validator(mode="after")
    def validate_stored_digest(self) -> Self:
        document = self.model_dump(mode="json", exclude={"digest"})
        if self.available_artifact_digests is None:
            document.pop("available_artifact_digests")
        if self.digest != canonical_digest(document):
            raise ValueError("legacy transition reported state digest is invalid")
        return self


def _strict_reported_state(value: object) -> object:
    if isinstance(value, dict):
        return NativeScopeTransitionReportedState.model_validate_json(canonical_bytes(value))
    return value


def _legacy_reported_state(value: object) -> object:
    if isinstance(value, dict):
        return LegacyNativeScopeTransitionReportedState.model_validate_json(canonical_bytes(value))
    return value


def _native_approval(value: object) -> object:
    if isinstance(value, dict):
        return NativeApproval.model_validate_json(canonical_bytes(value))
    return value


def _reconciliation_request(value: object) -> object:
    if isinstance(value, dict):
        return NativeScopeTransitionStateReconciliationRequest.model_validate_json(
            canonical_bytes(value)
        )
    return value


def _reconciliation_approval(value: object) -> object:
    if isinstance(value, dict):
        return NativeScopeTransitionStateReconciliationApproval.model_validate_json(
            canonical_bytes(value)
        )
    return value


def _signed_reconciliation_approval(value: object) -> object:
    if isinstance(value, dict):
        return SignedNativeScopeTransitionStateReconciliationApproval.model_validate_json(
            canonical_bytes(value)
        )
    return value


StrictReportedStateReadback = Annotated[
    NativeScopeTransitionReportedState,
    BeforeValidator(_strict_reported_state),
]
LegacyReportedStateReadback = Annotated[
    LegacyNativeScopeTransitionReportedState,
    BeforeValidator(_legacy_reported_state),
]


def _immutable_receipt_timestamp(value: object) -> object:
    if isinstance(value, str):
        if _IMMUTABLE_RECEIPT_TIMESTAMP_PATTERN.fullmatch(value) is None:
            raise ValueError("immutable transition timestamp must use exact UTC precision")
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, datetime) and value.utcoffset() != timedelta(0):
        raise ValueError("immutable transition timestamp must use UTC")
    return value


ImmutableReceiptTimestamp = Annotated[
    AwareDatetime,
    BeforeValidator(_immutable_receipt_timestamp),
    PlainSerializer(
        _serialize_reported_state_timestamp,
        return_type=str,
    ),
]


def _immutable_receipt_record_digests(
    document: dict[str, Any],
) -> tuple[str, str] | None:
    """Digest the same exact UTC receipt with its legacy and Hub timestamp spellings."""

    completed_at = document.get("completed_at")
    if not isinstance(completed_at, str):
        return None
    match = _IMMUTABLE_RECEIPT_TIMESTAMP_PATTERN.fullmatch(completed_at)
    if match is None:
        return None
    instant = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    if instant.utcoffset() != timedelta(0):
        return None
    timestamp = match.group("instant")
    legacy_document = {**document, "completed_at": timestamp + "+00:00"}
    hub_document = {**document, "completed_at": timestamp + "Z"}
    return (
        "sha256:" + canonical_digest(legacy_document),
        "sha256:" + canonical_digest(hub_document),
    )


def transition_reported_state_document(
    state: LegacyNativeScopeTransitionReportedState | NativeScopeTransitionReportedState,
    *,
    observed_at: datetime | None = None,
    milliseconds: bool = False,
) -> dict[str, object]:
    """Return canonical state fields with an explicitly selected timestamp representation."""

    timestamp = (observed_at or state.observed_at).astimezone(UTC)
    document: dict[str, object] = {
        "schema_revision": state.schema_revision,
        "entities": {
            entity_id: {
                "release_id": entity.release_id,
                "artifact_digests": list(entity.artifact_digests),
                "health": entity.health,
            }
            for entity_id, entity in sorted(state.entities.items())
        },
        "observed_at": (
            timestamp.isoformat(timespec="milliseconds") if milliseconds else timestamp.isoformat()
        ).replace("+00:00", "Z"),
    }
    if state.available_artifact_digests is not None:
        document["available_artifact_digests"] = list(state.available_artifact_digests)
    return document


def transition_reported_state_digest(
    state: LegacyNativeScopeTransitionReportedState | NativeScopeTransitionReportedState,
    *,
    observed_at: datetime | None = None,
    milliseconds: bool = False,
) -> str:
    return canonical_digest(
        transition_reported_state_document(
            state,
            observed_at=observed_at,
            milliseconds=milliseconds,
        )
    )


def same_transition_state_fields(
    left: LegacyNativeScopeTransitionReportedState | NativeScopeTransitionReportedState,
    right: LegacyNativeScopeTransitionReportedState | NativeScopeTransitionReportedState,
) -> bool:
    """Compare non-time fields while preserving exact artifact multiplicity."""

    left_artifacts = left.available_artifact_digests
    right_artifacts = right.available_artifact_digests
    return (
        left.schema_revision == right.schema_revision
        and left.entities == right.entities
        and (
            left_artifacts is None
            and right_artifacts is None
            or left_artifacts is not None
            and right_artifacts is not None
            and Counter(left_artifacts) == Counter(right_artifacts)
        )
    )


def same_transition_state_semantic_inventory(
    left: LegacyNativeScopeTransitionReportedState | NativeScopeTransitionReportedState,
    right: LegacyNativeScopeTransitionReportedState | NativeScopeTransitionReportedState,
) -> bool:
    """Compare a legacy source with its deduplicated authoritative target."""

    left_artifacts = left.available_artifact_digests
    right_artifacts = right.available_artifact_digests
    return (
        left.schema_revision == right.schema_revision
        and left.entities == right.entities
        and left.observed_at == right.observed_at
        and (
            left_artifacts is None
            and right_artifacts is None
            or left_artifacts is not None
            and right_artifacts is not None
            and set(left_artifacts) == set(right_artifacts)
        )
    )


def canonical_transition_reported_state(
    source: LegacyNativeScopeTransitionReportedState,
) -> NativeScopeTransitionReportedState:
    """Build the strict target without mutating or normalizing the legacy source."""

    inventory = source.available_artifact_digests
    document = source.model_dump(mode="python")
    document["digest"] = "0" * 64
    document["observed_at"] = source.observed_at
    document["available_artifact_digests"] = (
        None if inventory is None else tuple(sorted(set(inventory)))
    )
    provisional = NativeScopeTransitionReportedState.model_validate(document)
    document["digest"] = transition_reported_state_digest(provisional)
    return NativeScopeTransitionReportedState.model_validate(document)


def _require_strict_target_inventory(state: NativeScopeTransitionReportedState) -> None:
    inventory = state.available_artifact_digests
    if inventory is not None and tuple(sorted(set(inventory))) != inventory:
        raise ValueError("authoritative transition artifacts must be unique and sorted")


class LegacyNativeScopeTransitionReceipt(BaseModel):
    """Immutable pre-fix receipt whose stored bytes retain their original precision."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["fdai.lifecycle-native-transition-receipt.v1"]
    request_digest: Digest
    hub_approval_digest: Digest
    installation_id: PathId
    old_entity_id: PathId
    new_entity_id: PathId
    old_scope_digest: Digest
    new_scope_digest: Digest
    old_reported_state_digest: HexDigest
    new_reported_state_digest: HexDigest
    ownership_claim_digest: Digest
    recovery_request_digest: Digest
    existing_resources_digest: Digest
    rollback_record_digest: Digest
    completed_at: ImmutableReceiptTimestamp
    record_digest: Digest

    @model_validator(mode="before")
    @classmethod
    def validate_record_digest(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        document = dict(value)
        digest = document.pop("record_digest", None)
        expected = _immutable_receipt_record_digests(document)
        if expected is None:
            raise ValueError("legacy native transition receipt digest is invalid")
        legacy_digest, hub_digest = expected
        serialized_digest = (
            hub_digest if str(document["completed_at"]).endswith("Z") else legacy_digest
        )
        if digest != legacy_digest or serialized_digest != "sha256:" + canonical_digest(document):
            raise ValueError("legacy native transition receipt digest is invalid")
        return value


def regenerated_transition_receipt_digest(
    receipt: LegacyNativeScopeTransitionReceipt,
    *,
    new_reported_state_digest: str,
) -> str:
    """Reproduce the Hub transition receipt without changing the immutable receipt."""

    document = receipt.model_dump(mode="json", exclude={"record_digest"})
    document["new_reported_state_digest"] = new_reported_state_digest
    return "sha256:" + canonical_digest(document)


class NativeScopeTransitionStateReconciliationRequest(BaseModel):
    """Operator request carrying all immutable legacy and Hub completion evidence."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["fdai.lifecycle-native-transition-state-reconciliation-request.v1"]
    request_id: UUID
    transition_receipt: LegacyNativeScopeTransitionReceipt
    completion_receipt: NativeScopeTransitionCompletionReceipt
    native_approval: Annotated[NativeApproval, BeforeValidator(_native_approval)]
    legacy_reported_state: LegacyReportedStateReadback
    requested_at: AwareDatetime
    expires_at: AwareDatetime
    confirmation: Annotated[str, StringConstraints(min_length=1, max_length=1024)]

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if not self.requested_at < self.expires_at <= self.requested_at + timedelta(minutes=10):
            raise ValueError("native transition reconciliation window is invalid")
        return self

    @property
    def installation_id(self) -> str:
        return self.transition_receipt.installation_id

    @property
    def digest(self) -> str:
        return "sha256:" + canonical_digest(self.model_dump(mode="json"))

    def require_current(self, now: datetime) -> None:
        if now.utcoffset() is None or not self.requested_at <= now < self.expires_at:
            raise ValueError("native transition reconciliation request is not current")


class NativeScopeTransitionStateReconciliationApproval(BaseModel):
    """Hub-authoritative state correction signed after completion-audit verification."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["fdai.lifecycle-native-transition-state-reconciliation-approval.v1"]
    request: Annotated[
        NativeScopeTransitionStateReconciliationRequest,
        BeforeValidator(_reconciliation_request),
    ]
    source_hub_reported_state: LegacyReportedStateReadback
    authoritative_reported_state: StrictReportedStateReadback
    approved_by: Actor
    approved_at: AwareDatetime
    expires_at: AwareDatetime
    completion_audit_digest: Digest
    hub_key_id: Annotated[str, StringConstraints(pattern=r"^hub-[0-9a-f]{16}$")]
    hub_key_epoch: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        _require_strict_target_inventory(self.authoritative_reported_state)
        if (
            self.expires_at != self.request.expires_at
            or not self.request.requested_at <= self.approved_at < self.expires_at
        ):
            raise ValueError("native transition reconciliation approval window is invalid")
        return self

    @property
    def digest(self) -> str:
        return "sha256:" + canonical_digest(self.model_dump(mode="json"))

    @property
    def payload(self) -> bytes:
        return b"fdai.lifecycle-native-transition-state-reconciliation-approval.v1\n" + (
            canonical_bytes(self.model_dump(mode="json"))
        )

    def require_current(self, now: datetime) -> None:
        self.request.require_current(now)
        if now.utcoffset() is None or not self.approved_at <= now < self.expires_at:
            raise ValueError("native transition reconciliation approval is not current")


class SignedNativeScopeTransitionStateReconciliationApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    approval: Annotated[
        NativeScopeTransitionStateReconciliationApproval,
        BeforeValidator(_reconciliation_approval),
    ]
    hub_signature: Annotated[str, StringConstraints(min_length=88, max_length=88)]

    @model_validator(mode="after")
    def validate_signature_encoding(self) -> Self:
        _signature_bytes(self.hub_signature)
        return self

    def verify(self, public_key: bytes, *, key_id: str, key_epoch: int) -> bool:
        approval = self.approval
        if (
            approval.hub_key_id != key_id
            or approval.hub_key_epoch != key_epoch
            or hub_key_id(public_key) != key_id
        ):
            return False
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(
                _signature_bytes(self.hub_signature),
                approval.payload,
            )
        except (InvalidSignature, ValueError):
            return False
        return True


class NativeScopeTransitionStateReconciliationCompletion(BaseModel):
    """Agent-authenticated proof that only its durable current-state file was corrected."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["fdai.lifecycle-native-transition-state-reconciliation-completion.v1"]
    approval: Annotated[
        SignedNativeScopeTransitionStateReconciliationApproval,
        BeforeValidator(_signed_reconciliation_approval),
    ]
    reported_state: NativeScopeTransitionReportedState

    @model_validator(mode="after")
    def validate_target_inventory(self) -> Self:
        _require_strict_target_inventory(self.reported_state)
        return self

    @property
    def digest(self) -> str:
        return "sha256:" + canonical_digest(self.model_dump(mode="json"))


class NativeScopeTransitionStateReconciliationReceipt(BaseModel):
    """Hub readback retained unchanged by both Hub and Agent for exact retries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["fdai.lifecycle-native-transition-state-reconciliation-receipt.v1"]
    completion_digest: Digest
    request_digest: Digest
    approval_digest: Digest
    transition_receipt_digest: Digest
    hub_completion_receipt_digest: Digest
    installation_id: PathId
    old_reported_state_digest: HexDigest
    new_reported_state_digest: HexDigest
    agent_principal: Actor
    authoritative_reported_state: StrictReportedStateReadback
    completed_at: AwareDatetime
    receipt_digest: Digest

    @model_validator(mode="before")
    @classmethod
    def validate_receipt_digest(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        document = dict(value)
        digest = document.pop("receipt_digest", None)
        if digest != "sha256:" + canonical_digest(document):
            raise ValueError("native transition reconciliation receipt digest is invalid")
        return value


def sign_transition_state_reconciliation_approval(
    approval: NativeScopeTransitionStateReconciliationApproval,
    key: Ed25519PrivateKey,
) -> SignedNativeScopeTransitionStateReconciliationApproval:
    return SignedNativeScopeTransitionStateReconciliationApproval(
        approval=approval,
        hub_signature=base64.b64encode(key.sign(approval.payload)).decode("ascii"),
    )


def _signature_bytes(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Hub signature encoding is invalid") from error
    if len(decoded) != 64 or base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("Hub signature must contain canonical Ed25519 bytes")
    return decoded
