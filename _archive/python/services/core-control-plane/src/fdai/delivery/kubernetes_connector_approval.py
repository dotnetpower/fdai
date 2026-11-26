"""Identity-bound observer approvals: a registered approver signs, a distinct executor runs.

An approval flag typed by the same invocation that executes it proves nothing about who approved.
A signed approval is verified against a deployment-owned approver grant, names the one executor
allowed to use it, and is rejected when the approver and executor are the same identity.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fdai_service_contracts.cluster_connector import ConnectorContract, Digest, connector_time
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import TargetRef
from pydantic import Field, field_validator, model_validator

from fdai.delivery.kubernetes_connector_apply import ObserverApplyApproval
from fdai.delivery.kubernetes_connector_runtime import private_file

Operation = Literal["apply", "activate", "verify", "deactivate", "recover", "rollback", "uninstall"]
_IDENTITY = r"^[A-Za-z0-9][A-Za-z0-9@._:/=+-]*$"


class ObserverApproverGrant(ConnectorContract):
    """Deployment-owned enrollment of one approver key for one target and operation set."""

    approver_ref: Annotated[str, Field(min_length=1, max_length=256, pattern=_IDENTITY)]
    key_ref: Digest
    public_key: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    target_ref: TargetRef
    operations: Annotated[tuple[Operation, ...], Field(min_length=1, max_length=7)]
    valid_from: datetime
    expires_at: datetime
    revoked: Annotated[bool, Field(strict=True)] = False

    @field_validator("valid_from", "expires_at", mode="before")
    @classmethod
    def _clock(cls, value: object) -> datetime:
        return connector_time(value)

    @model_validator(mode="after")
    def _integrity(self) -> Self:
        if self.key_ref != "sha256:" + hashlib.sha256(bytes.fromhex(self.public_key)).hexdigest():
            raise ValueError("observer approver key digest is invalid")
        if self.expires_at <= self.valid_from or len(set(self.operations)) != len(self.operations):
            raise ValueError("observer approver grant is invalid")
        return self


class SignedObserverApproval(ConnectorContract):
    """One approval, bound to its executor and signed by a registered approver key."""

    approval: ObserverApplyApproval
    executor_ref: Annotated[str, Field(min_length=1, max_length=256, pattern=_IDENTITY)]
    key_ref: Digest
    signature: Annotated[str, Field(pattern=r"^[0-9a-f]{128}$")]

    def signing_bytes(self) -> bytes:
        return (
            "fdai.observer-approval.v1:"
            + canonical_digest(self.model_dump(mode="json", exclude={"signature"}))
        ).encode("ascii")


def load_approver_grants(path: Path) -> tuple[ObserverApproverGrant, ...]:
    value = json.loads(private_file(path))
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        raise ValueError("observer approver grants must be a list of 1 to 64 entries")
    return tuple(ObserverApproverGrant.model_validate(item) for item in value)


def sign_approval(
    approval: ObserverApplyApproval, *, executor_ref: str, signing_key: Path
) -> SignedObserverApproval:
    private = load_pem_private_key(private_file(signing_key), None)
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError("observer approval requires an Ed25519 signing key")
    key_ref = "sha256:" + hashlib.sha256(private.public_key().public_bytes_raw()).hexdigest()
    unsigned = {
        "approval": approval.model_dump(mode="json"),
        "executor_ref": executor_ref,
        "key_ref": key_ref,
        "signature": "0" * 128,
    }
    shell = SignedObserverApproval.model_validate(unsigned)
    return shell.model_copy(update={"signature": private.sign(shell.signing_bytes()).hex()})


def verify_signed_approval(
    signed: SignedObserverApproval,
    *,
    grants: Sequence[ObserverApproverGrant],
    executor_ref: str,
    now: datetime,
) -> ObserverApplyApproval:
    """Return the approval only for the enrolled approver, the named executor, and a live window."""
    signed = SignedObserverApproval.model_validate_json(signed.model_dump_json())
    approval, cutoff = signed.approval, connector_time(now)
    grant = next(
        (
            item
            for item in grants
            if (item.approver_ref, item.key_ref, item.target_ref)
            == (approval.approver_ref, signed.key_ref, approval.target_ref)
        ),
        None,
    )
    if (
        grant is None
        or grant.revoked
        or approval.operation not in grant.operations
        or not grant.valid_from <= connector_time(approval.approved_at) <= cutoff < grant.expires_at
    ):
        raise ValueError("the observer approval is not signed by an enrolled approver")
    if (
        signed.executor_ref != executor_ref
        or executor_ref.casefold() == approval.approver_ref.casefold()
    ):
        raise ValueError("the observer approver and executor must be distinct identities")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(grant.public_key)).verify(
            bytes.fromhex(signed.signature), signed.signing_bytes()
        )
    except InvalidSignature as exc:
        raise ValueError("the observer approval signature is invalid") from exc
    return approval
