"""Private native-scope identity and crash-safe resource UID history."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Self

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest
from fdai_deployment_cli.lifecycle_native import (
    Digest,
    NativeApproval,
    NativeScope,
    SignedNativeScope,
)
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from fdai_lifecycle_agent.state import write_json_atomically
from fdai_lifecycle_agent.strict_json import load_json, read_limited
from fdai_lifecycle_agent.workload import WorkloadError

type ResourceUid = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
NATIVE_STATE_FILE = "lifecycle-native-scope.json"


class NativeState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["fdai.lifecycle-native-state.v1"]
    scope: NativeScope
    approval_digest: Digest
    anchor_uid: ResourceUid | None = None
    anchor_resource_version: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    proof: SignedNativeScope | None = None
    resources: dict[str, ResourceUid] = Field(default_factory=dict)
    deleting: frozenset[str] = frozenset()
    pending: str | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        allowed = {f"{kind}/{name}" for kind, name in self.scope.resources}
        anchor = f"Service/{self.scope.anchor_name}"
        if not set(self.resources) <= allowed or not self.deleting <= self.resources.keys():
            raise ValueError("native resource history exceeds the approved scope")
        if self.pending is not None and (
            self.pending not in allowed | {anchor}
            or self.pending in self.resources
            or self.pending in self.deleting
        ):
            raise ValueError("native pending creation is invalid")
        if (self.anchor_uid is None) != (self.anchor_resource_version is None):
            raise ValueError("native anchor identity is incomplete")
        if self.proof is not None:
            claim = self.proof.claim
            if (
                self.anchor_uid is None
                or claim.installation_id != self.scope.installation_id
                or claim.entity_id != self.scope.entity_id
                or claim.product != self.scope.product
                or claim.scope_digest != self.scope.digest
                or claim.approval_digest != self.approval_digest
                or claim.creation_receipt_digest != self.creation_receipt_digest
            ):
                raise ValueError("native proof does not match its private scope")
        elif self.resources or self.deleting:
            raise ValueError("native workload history requires a completed anchor proof")
        return self

    @property
    def creation_receipt_digest(self) -> str:
        if self.anchor_uid is None or self.anchor_resource_version is None:
            raise ValueError("native anchor creation has not completed")
        return "sha256:" + canonical_digest(
            {
                "schema_version": "fdai.lifecycle-native-anchor-created.v1",
                "scope_digest": self.scope.digest,
                "approval_digest": self.approval_digest,
                "anchor_uid": self.anchor_uid,
                "anchor_resource_version": self.anchor_resource_version,
            }
        )


class NativeStateStore:
    def __init__(self, directory: Path) -> None:
        self.path = directory / NATIVE_STATE_FILE

    def load(self) -> NativeState | None:
        try:
            raw = read_limited(self.path, limit=128 * 1024, label="native scope state")
        except FileNotFoundError:
            return None
        except OSError as error:
            raise WorkloadError("native_scope_state_unavailable") from error
        try:
            document = load_json(raw, label="native scope state")
            return NativeState.model_validate_json(canonical_bytes(document))
        except ValueError as error:
            raise WorkloadError("native_scope_state_invalid") from error

    def save(self, state: NativeState) -> None:
        try:
            validated = NativeState.model_validate_json(state.model_dump_json())
            write_json_atomically(self.path, validated.model_dump(mode="json"))
        except OSError as error:
            raise WorkloadError("native_scope_state_unavailable") from error


def load_native_approval(path: Path) -> NativeApproval:
    try:
        document = load_json(
            read_limited(path, limit=64 * 1024, label="native approval"),
            label="native approval",
        )
        return NativeApproval.model_validate_json(canonical_bytes(document))
    except (OSError, ValueError) as error:
        raise WorkloadError("native_scope_approval_invalid") from error
