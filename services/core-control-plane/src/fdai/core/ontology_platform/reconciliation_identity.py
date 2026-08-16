"""Principal-free observer identity record for effect reconciliation attribution.

operational-hypothesis-loop.md requires that an independent outcome names who observed the
effect, who executed the action, which source produced the evidence, and who authenticated
it, so a replayed episode can prove role separation without re-reading raw principals. This
module owns that record: a bounded, content-addressed projection of the authenticated
observation context that carries stable identity handles and the derived independence
findings instead of the identity strings themselves.

The record is evidence, not authority. It never closes an effect, promotes a hypothesis, or
grants execution authority; the coordinator still decides scorability from its own rules.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from fdai.shared.contracts.models import ContractBase, SemVer

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"


def observer_identity_handle(value: str) -> str:
    """Return the stable, correlation-safe handle for one identity or credential lineage.

    The handle is a digest of the case-folded, whitespace-trimmed value, so the same
    principal produces the same handle across episodes while the record itself carries no
    directory name, credential, or endpoint. The handle is pseudonymous linkage evidence,
    not a confidentiality control: a caller that already knows a candidate identity can
    confirm it, so a handle MUST NOT be treated as a secret.
    """

    encoded = json.dumps(
        {"identity": value.strip().casefold()},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ObserverIdentityRecord(ContractBase):
    """Replay-stable attribution record for one authenticated effect observation."""

    schema_version: SemVer = "1.0.0"
    source_authority: Annotated[str, Field(pattern=r"^[a-z][a-z_]{0,31}$")]
    observer_handle: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    executor_handle: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    source_handle: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    verifier_handle: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    observer_credential_handle: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    executor_credential_handle: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    source_credential_handle: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    verifier_credential_handle: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    distinct_identities: int = Field(ge=1, le=4)
    distinct_credentials: int = Field(ge=1, le=4)
    identities_independent: bool
    credentials_independent: bool
    verifier_independent_of_executor: bool
    signature_algorithm: Literal["ed25519"]
    verified_at: datetime
    grants_authority: Literal[False] = False

    @classmethod
    def from_identities(
        cls,
        *,
        source_authority: str,
        observer_identity: str,
        observer_credential_lineage: str,
        executor_identity: str,
        executor_credential_lineage: str,
        source_identity: str,
        source_credential_lineage: str,
        verifier_identity: str,
        verifier_credential_lineage: str,
        signature_algorithm: Literal["ed25519"],
        verified_at: datetime,
    ) -> Self:
        """Project one authenticated observation into its attribution record."""

        identities = (observer_identity, executor_identity, source_identity)
        credentials = (
            observer_credential_lineage,
            executor_credential_lineage,
            source_credential_lineage,
        )
        distinct_identities = len({value.strip().casefold() for value in identities})
        distinct_credentials = len({value.strip().casefold() for value in credentials})
        return cls(
            source_authority=source_authority,
            observer_handle=observer_identity_handle(observer_identity),
            executor_handle=observer_identity_handle(executor_identity),
            source_handle=observer_identity_handle(source_identity),
            verifier_handle=observer_identity_handle(verifier_identity),
            observer_credential_handle=observer_identity_handle(observer_credential_lineage),
            executor_credential_handle=observer_identity_handle(executor_credential_lineage),
            source_credential_handle=observer_identity_handle(source_credential_lineage),
            verifier_credential_handle=observer_identity_handle(verifier_credential_lineage),
            distinct_identities=distinct_identities,
            distinct_credentials=distinct_credentials,
            identities_independent=distinct_identities == len(identities),
            credentials_independent=distinct_credentials == len(credentials),
            verifier_independent_of_executor=(
                verifier_identity.strip().casefold() != executor_identity.strip().casefold()
            ),
            signature_algorithm=signature_algorithm,
            verified_at=verified_at,
        )

    @model_validator(mode="after")
    def _findings_match_handles(self) -> ObserverIdentityRecord:
        """Reject a record whose independence findings contradict its own handles."""

        if self.verified_at.tzinfo is None or self.verified_at.utcoffset() is None:
            raise ValueError("observer identity record verification time MUST be absolute")
        identity_handles = {self.observer_handle, self.executor_handle, self.source_handle}
        credential_handles = {
            self.observer_credential_handle,
            self.executor_credential_handle,
            self.source_credential_handle,
        }
        if self.distinct_identities != len(identity_handles):
            raise ValueError("observer identity record distinct identity count does not match")
        if self.distinct_credentials != len(credential_handles):
            raise ValueError("observer identity record distinct credential count does not match")
        if self.identities_independent != (len(identity_handles) == 3):
            raise ValueError("observer identity record independence finding does not match")
        if self.credentials_independent != (len(credential_handles) == 3):
            raise ValueError("observer identity record credential finding does not match")
        if self.verifier_independent_of_executor != (self.verifier_handle != self.executor_handle):
            raise ValueError("observer identity record verifier finding does not match")
        return self


__all__ = ["ObserverIdentityRecord", "observer_identity_handle"]
