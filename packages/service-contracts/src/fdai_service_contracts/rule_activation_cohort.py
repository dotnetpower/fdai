"""Dormant replica-cohort contracts for Rule activation version 2."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.rule_activation_identity import (
    RuleActivationGenerationIdentityV2,
)


class RuleReplicaDisposition(StrEnum):
    ACKNOWLEDGED = "acknowledged"
    REFUSED = "refused"


class RuleReplicaDepartureKind(StrEnum):
    DRAINED = "drained"
    LEASE_EXPIRED = "lease_expired"


class RuleReplicaIdentity(ContractBase):
    """One authenticated serving replica frozen into a preparation cohort."""

    replica_id: Annotated[str, Field(min_length=1, max_length=256)]
    principal_id: Annotated[str, Field(min_length=1, max_length=256)]
    release_id: Annotated[str, Field(min_length=1, max_length=256)]
    startup_epoch: Annotated[str, Field(min_length=1, max_length=256)]
    serving_lease_id: Annotated[str, Field(min_length=1, max_length=256)]
    serving_lease_expires_at: datetime

    @field_validator(
        "replica_id",
        "principal_id",
        "release_id",
        "startup_epoch",
        "serving_lease_id",
        mode="before",
    )
    @classmethod
    def _exact_text(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Rule replica identity text MUST be exact")
        return value

    @field_validator("serving_lease_expires_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Rule replica lease expiry MUST include a timezone")
        return value.astimezone(UTC)


class RuleReplicaDepartureEvidence(ContractBase):
    """Authenticated evidence allowing one exact frozen identity to leave a cohort."""

    replica: RuleReplicaIdentity
    kind: RuleReplicaDepartureKind
    serving_inventory_digest: Digest
    authentication_receipt_digest: Digest
    observed_at: datetime
    evidence_digest: Digest

    @field_validator("observed_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _canonical_evidence(self) -> Self:
        expected = rule_replica_departure_evidence_digest(
            replica=self.replica,
            kind=self.kind,
            serving_inventory_digest=self.serving_inventory_digest,
            authentication_receipt_digest=self.authentication_receipt_digest,
            observed_at=self.observed_at,
        )
        if self.evidence_digest != expected:
            raise ValueError("Rule replica departure evidence digest mismatch")
        return self

    @property
    def replica_id(self) -> str:
        return self.replica.replica_id


class RuleCohortPrepareV2(ContractBase):
    """Frozen inert cohort for one exact generation preparation."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    generation: RuleActivationGenerationIdentityV2
    predecessor_prepare_digest: Digest | None = None
    serving_inventory_digest: Digest
    revision_registry_root: Digest
    catalog_manifest_digest: Digest
    replicas: Annotated[tuple[RuleReplicaIdentity, ...], Field(min_length=1, max_length=1_000)]
    departures: Annotated[tuple[RuleReplicaDepartureEvidence, ...], Field(max_length=1_000)] = ()
    prepared_at: datetime
    prepare_digest: Digest
    approval_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("prepared_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Rule cohort prepare time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _canonical_prepare(self) -> Self:
        replica_ids = tuple(replica.replica_id for replica in self.replicas)
        principals = tuple(replica.principal_id for replica in self.replicas)
        if replica_ids != tuple(sorted(replica_ids)) or len(set(replica_ids)) != len(replica_ids):
            raise ValueError("Rule cohort replicas MUST be unique and sorted")
        if len(set(principals)) != len(principals):
            raise ValueError("Rule cohort replica principals MUST be unique")
        departure_ids = tuple(item.replica_id for item in self.departures)
        if departure_ids != tuple(sorted(departure_ids)) or len(set(departure_ids)) != len(
            departure_ids
        ):
            raise ValueError("Rule cohort departure evidence MUST be unique and sorted")
        if any(replica.serving_lease_expires_at <= self.prepared_at for replica in self.replicas):
            raise ValueError("Rule cohort serving leases MUST outlive preparation")
        expected = rule_cohort_prepare_digest(
            generation=self.generation,
            predecessor_prepare_digest=self.predecessor_prepare_digest,
            serving_inventory_digest=self.serving_inventory_digest,
            revision_registry_root=self.revision_registry_root,
            catalog_manifest_digest=self.catalog_manifest_digest,
            replicas=self.replicas,
            departures=self.departures,
            prepared_at=self.prepared_at,
        )
        if self.prepare_digest != expected:
            raise ValueError("Rule cohort prepare digest mismatch")
        return self


class RuleReplicaAcknowledgementV2(ContractBase):
    """Authenticated replica acknowledgement or refusal for one preparation."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    prepare_digest: Digest
    replica_id: Annotated[str, Field(min_length=1, max_length=256)]
    principal_id: Annotated[str, Field(min_length=1, max_length=256)]
    release_id: Annotated[str, Field(min_length=1, max_length=256)]
    startup_epoch: Annotated[str, Field(min_length=1, max_length=256)]
    serving_lease_id: Annotated[str, Field(min_length=1, max_length=256)]
    revision_registry_root: Digest
    catalog_manifest_digest: Digest
    profile_snapshot_digest: Digest
    generation_digest: Digest
    disposition: RuleReplicaDisposition
    reason: Annotated[str, Field(min_length=1, max_length=512)]
    authentication_receipt_digest: Digest
    observed_at: datetime
    acknowledgement_digest: Digest
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator(
        "replica_id",
        "principal_id",
        "release_id",
        "startup_epoch",
        "serving_lease_id",
        "reason",
        mode="before",
    )
    @classmethod
    def _exact_text(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Rule replica acknowledgement text MUST be exact")
        return value

    @field_validator("observed_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Rule replica acknowledgement time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _canonical_acknowledgement(self) -> Self:
        expected = rule_replica_acknowledgement_digest(
            prepare_digest=self.prepare_digest,
            replica_id=self.replica_id,
            principal_id=self.principal_id,
            release_id=self.release_id,
            startup_epoch=self.startup_epoch,
            serving_lease_id=self.serving_lease_id,
            revision_registry_root=self.revision_registry_root,
            catalog_manifest_digest=self.catalog_manifest_digest,
            profile_snapshot_digest=self.profile_snapshot_digest,
            generation_digest=self.generation_digest,
            disposition=self.disposition,
            reason=self.reason,
            authentication_receipt_digest=self.authentication_receipt_digest,
            observed_at=self.observed_at,
        )
        if self.acknowledgement_digest != expected:
            raise ValueError("Rule replica acknowledgement digest mismatch")
        return self


class RuleCohortCandidateActiveV2(ContractBase):
    """Authority-neutral candidate selected only after a complete acknowledgement set."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    prepare_digest: Digest
    generation_digest: Digest
    acknowledgement_set_digest: Digest
    activated_at: datetime
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("activated_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Rule cohort candidate activation time MUST include a timezone")
        return value.astimezone(UTC)


class RuleReplicaAppliedV2(ContractBase):
    """Replica readback after replacing its complete local T0 generation."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    prepare_digest: Digest
    acknowledgement_set_digest: Digest
    replica_id: Annotated[str, Field(min_length=1, max_length=256)]
    principal_id: Annotated[str, Field(min_length=1, max_length=256)]
    release_id: Annotated[str, Field(min_length=1, max_length=256)]
    startup_epoch: Annotated[str, Field(min_length=1, max_length=256)]
    serving_lease_id: Annotated[str, Field(min_length=1, max_length=256)]
    generation_digest: Digest
    applied_at: datetime
    activation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator(
        "replica_id",
        "principal_id",
        "release_id",
        "startup_epoch",
        "serving_lease_id",
        mode="before",
    )
    @classmethod
    def _exact_text(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Rule replica applied identity text MUST be exact")
        return value

    @field_validator("applied_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Rule replica applied time MUST include a timezone")
        return value.astimezone(UTC)


def build_rule_cohort_prepare_v2(
    *,
    generation: RuleActivationGenerationIdentityV2,
    predecessor_prepare_digest: str | None = None,
    serving_inventory_digest: str,
    revision_registry_root: str,
    catalog_manifest_digest: str,
    replicas: tuple[RuleReplicaIdentity, ...],
    departures: tuple[RuleReplicaDepartureEvidence, ...] = (),
    prepared_at: datetime,
) -> RuleCohortPrepareV2:
    return RuleCohortPrepareV2(
        generation=generation,
        predecessor_prepare_digest=predecessor_prepare_digest,
        serving_inventory_digest=serving_inventory_digest,
        revision_registry_root=revision_registry_root,
        catalog_manifest_digest=catalog_manifest_digest,
        replicas=replicas,
        departures=departures,
        prepared_at=prepared_at,
        prepare_digest=rule_cohort_prepare_digest(
            generation=generation,
            predecessor_prepare_digest=predecessor_prepare_digest,
            serving_inventory_digest=serving_inventory_digest,
            revision_registry_root=revision_registry_root,
            catalog_manifest_digest=catalog_manifest_digest,
            replicas=replicas,
            departures=departures,
            prepared_at=prepared_at,
        ),
    )


def rule_cohort_prepare_digest(
    *,
    generation: RuleActivationGenerationIdentityV2,
    predecessor_prepare_digest: str | None,
    serving_inventory_digest: str,
    revision_registry_root: str,
    catalog_manifest_digest: str,
    replicas: tuple[RuleReplicaIdentity, ...],
    departures: tuple[RuleReplicaDepartureEvidence, ...],
    prepared_at: datetime,
) -> str:
    return canonical_digest(
        {
            "generation": generation.model_dump(mode="json"),
            "predecessor_prepare_digest": predecessor_prepare_digest,
            "serving_inventory_digest": serving_inventory_digest,
            "revision_registry_root": revision_registry_root,
            "catalog_manifest_digest": catalog_manifest_digest,
            "replicas": [replica.model_dump(mode="json") for replica in replicas],
            "departures": [departure.model_dump(mode="json") for departure in departures],
            "prepared_at": _utc(prepared_at).isoformat(),
        }
    )


def rule_replica_acknowledgement_digest(**values: object) -> str:
    canonical = {
        key: _utc(value).isoformat()
        if isinstance(value, datetime)
        else value.value
        if isinstance(value, StrEnum)
        else value
        for key, value in values.items()
    }
    return canonical_digest(canonical)


def build_rule_replica_departure_evidence(
    *,
    replica: RuleReplicaIdentity,
    kind: RuleReplicaDepartureKind,
    serving_inventory_digest: str,
    authentication_receipt_digest: str,
    observed_at: datetime,
) -> RuleReplicaDepartureEvidence:
    return RuleReplicaDepartureEvidence(
        replica=replica,
        kind=kind,
        serving_inventory_digest=serving_inventory_digest,
        authentication_receipt_digest=authentication_receipt_digest,
        observed_at=observed_at,
        evidence_digest=rule_replica_departure_evidence_digest(
            replica=replica,
            kind=kind,
            serving_inventory_digest=serving_inventory_digest,
            authentication_receipt_digest=authentication_receipt_digest,
            observed_at=observed_at,
        ),
    )


def rule_replica_departure_evidence_digest(
    *,
    replica: RuleReplicaIdentity,
    kind: RuleReplicaDepartureKind,
    serving_inventory_digest: str,
    authentication_receipt_digest: str,
    observed_at: datetime,
) -> str:
    return canonical_digest(
        {
            "replica": replica.model_dump(mode="json"),
            "kind": kind.value,
            "serving_inventory_digest": serving_inventory_digest,
            "authentication_receipt_digest": authentication_receipt_digest,
            "observed_at": _utc(observed_at).isoformat(),
        }
    )


def rule_acknowledgement_set_digest(
    acknowledgements: tuple[RuleReplicaAcknowledgementV2, ...],
) -> str:
    ordered = tuple(sorted(acknowledgements, key=lambda item: item.replica_id))
    if not ordered or len({item.replica_id for item in ordered}) != len(ordered):
        raise ValueError("Rule acknowledgement set MUST be non-empty and unique")
    return canonical_digest([item.acknowledgement_digest for item in ordered])


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Rule cohort digest time MUST include a timezone")
    return value.astimezone(UTC)


__all__ = [
    "RuleCohortCandidateActiveV2",
    "RuleCohortPrepareV2",
    "RuleReplicaAcknowledgementV2",
    "RuleReplicaAppliedV2",
    "RuleReplicaDepartureEvidence",
    "RuleReplicaDepartureKind",
    "RuleReplicaDisposition",
    "RuleReplicaIdentity",
    "build_rule_replica_departure_evidence",
    "build_rule_cohort_prepare_v2",
    "rule_acknowledgement_set_digest",
    "rule_cohort_prepare_digest",
    "rule_replica_acknowledgement_digest",
    "rule_replica_departure_evidence_digest",
]
