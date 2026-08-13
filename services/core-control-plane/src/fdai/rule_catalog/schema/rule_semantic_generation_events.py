"""Compact typed events for the governed Rule semantic generation lifecycle."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from fdai.rule_catalog.schema.rule_semantic_retrieval import RuleCorpus
from fdai.shared.contracts.models import ContractBase, SemVer
from fdai.shared.providers.catalog_search import CatalogGenerationMetadata

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_ID_PATTERN = r"^rule-generation:[a-f0-9]{64}$"
_IDEMPOTENCY_PATTERN = r"^rule-generation:[a-z-]+:[a-f0-9]{64}$"
_MAX_DOCUMENTS = 20_000
_MAX_DOCUMENT_CHUNKS = 79
RULE_GENERATION_BUILD_REQUEST_TOPIC = "object.rule-generation-build-request"
RULE_GENERATION_BUILD_RESULT_TOPIC = "object.rule-generation-build-result"


class RuleGenerationActivationStatus(StrEnum):
    """Stable activation outcomes exposed to audit and read projections."""

    ACTIVATED = "activated"
    ALREADY_ACTIVE = "already_active"
    FAILED = "failed"


class RuleGenerationOutboxDeliveryState(StrEnum):
    """Durable publication state for one activation result."""

    PENDING = "pending"
    CLAIMED = "claimed"
    PUBLISHED = "published"


class RuleGenerationIdentity(ContractBase):
    """Bounded exact identity for one complete Rule search generation."""

    generation_id: Annotated[str, Field(min_length=1, max_length=512)]
    generation_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    corpus: RuleCorpus
    catalog_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    semantic_schema_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    ontology_release_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    embedding_space_id: Annotated[str, Field(min_length=1, max_length=256)]
    embedding_model_version: Annotated[str, Field(min_length=1, max_length=256)]
    embedding_dimension: int = Field(ge=1, le=4096)
    document_count: int = Field(ge=1, le=_MAX_DOCUMENTS)
    document_digest_root: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    document_digest_chunks: Annotated[
        tuple[str, ...], Field(min_length=1, max_length=_MAX_DOCUMENT_CHUNKS)
    ]
    manifest_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @classmethod
    def from_metadata(cls, metadata: CatalogGenerationMetadata) -> Self:
        manifest = metadata.document_digest_manifest
        chunks = tuple(chunk.digest for chunk in manifest.chunks)
        return cls(
            generation_id=metadata.generation_id,
            generation_digest=metadata.generation_digest,
            corpus=RuleCorpus(metadata.corpus),
            catalog_digest=metadata.catalog_digest,
            semantic_schema_digest=metadata.semantic_schema_digest,
            ontology_release_digest=metadata.ontology_release_digest,
            embedding_space_id=metadata.embedding_space_id,
            embedding_model_version=metadata.embedding_model_version,
            embedding_dimension=metadata.embedding_dimension,
            document_count=manifest.document_count,
            document_digest_root=manifest.document_digest_root,
            document_digest_chunks=chunks,
            manifest_digest=_canonical_digest(
                {
                    "document_count": manifest.document_count,
                    "document_digest_root": manifest.document_digest_root,
                    "document_digest_chunks": chunks,
                }
            ),
        )

    @model_validator(mode="after")
    def _manifest_summary_is_canonical(self) -> RuleGenerationIdentity:
        if len(self.document_digest_chunks) != len(set(self.document_digest_chunks)):
            raise ValueError("Rule generation manifest chunk digests MUST be unique")
        expected = _canonical_digest(
            {
                "document_count": self.document_count,
                "document_digest_root": self.document_digest_root,
                "document_digest_chunks": self.document_digest_chunks,
            }
        )
        if self.manifest_digest != expected:
            raise ValueError("Rule generation manifest digest does not match content")
        return self


class RuleGenerationBuildRequestEvent(ContractBase):
    """Mimir-owned request for a mechanical worker to build one candidate generation."""

    schema_version: SemVer = "1.0.0"
    event_type: Literal["rule.semantic_generation.build.requested.v1"] = (
        "rule.semantic_generation.build.requested.v1"
    )
    generation_request_id: Annotated[str, Field(pattern=_ID_PATTERN)]
    idempotency_key: Annotated[str, Field(pattern=_IDEMPOTENCY_PATTERN)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    corpus: RuleCorpus
    catalog_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    semantic_schema_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    ontology_release_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    embedding_space_id: Annotated[str, Field(min_length=1, max_length=256)]
    embedding_model_version: Annotated[str, Field(min_length=1, max_length=256)]
    embedding_dimension: int = Field(ge=1, le=4096)
    requested_at: datetime
    request_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    grants_authority: Literal[False] = False

    @classmethod
    def create(
        cls,
        *,
        correlation_id: str,
        corpus: RuleCorpus,
        catalog_digest: str,
        semantic_schema_digest: str,
        ontology_release_digest: str,
        embedding_space_id: str,
        embedding_model_version: str,
        embedding_dimension: int,
        requested_at: datetime,
    ) -> Self:
        content = {
            "correlation_id": correlation_id,
            "corpus": corpus.value,
            "catalog_digest": catalog_digest,
            "semantic_schema_digest": semantic_schema_digest,
            "ontology_release_digest": ontology_release_digest,
            "embedding_space_id": embedding_space_id,
            "embedding_model_version": embedding_model_version,
            "embedding_dimension": embedding_dimension,
        }
        request_id = "rule-generation:" + _canonical_digest(content)[7:]
        prototype = cls.model_construct(
            generation_request_id=request_id,
            idempotency_key=f"rule-generation:build:{request_id[16:]}",
            correlation_id=correlation_id,
            corpus=corpus,
            catalog_digest=catalog_digest,
            semantic_schema_digest=semantic_schema_digest,
            ontology_release_digest=ontology_release_digest,
            embedding_space_id=embedding_space_id,
            embedding_model_version=embedding_model_version,
            embedding_dimension=embedding_dimension,
            requested_at=requested_at,
            request_digest="sha256:" + "0" * 64,
        )
        return cls(
            **prototype.model_dump(exclude={"request_digest"}),
            request_digest=_event_digest(prototype, "request_digest"),
        )

    @model_validator(mode="after")
    def _request_is_canonical(self) -> RuleGenerationBuildRequestEvent:
        _require_aware("requested_at", self.requested_at)
        expected_id = (
            "rule-generation:"
            + _canonical_digest(
                {
                    "correlation_id": self.correlation_id,
                    "corpus": self.corpus.value,
                    "catalog_digest": self.catalog_digest,
                    "semantic_schema_digest": self.semantic_schema_digest,
                    "ontology_release_digest": self.ontology_release_digest,
                    "embedding_space_id": self.embedding_space_id,
                    "embedding_model_version": self.embedding_model_version,
                    "embedding_dimension": self.embedding_dimension,
                }
            )[7:]
        )
        if self.generation_request_id != expected_id:
            raise ValueError("Rule generation request id does not match content")
        if self.idempotency_key != f"rule-generation:build:{expected_id[16:]}":
            raise ValueError("Rule generation build idempotency key does not match content")
        if self.request_digest != _event_digest(self, "request_digest"):
            raise ValueError("Rule generation request digest does not match content")
        return self


class RuleGenerationBuildResultEvent(ContractBase):
    """Mechanical build result carrying bounded generation identity only."""

    schema_version: SemVer = "1.0.0"
    event_type: Literal["rule.semantic_generation.build.completed.v1"] = (
        "rule.semantic_generation.build.completed.v1"
    )
    idempotency_key: Annotated[str, Field(pattern=_IDEMPOTENCY_PATTERN)]
    request: RuleGenerationBuildRequestEvent
    generation: RuleGenerationIdentity
    built_at: datetime
    result_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    grants_authority: Literal[False] = False

    @classmethod
    def create(
        cls,
        *,
        request: RuleGenerationBuildRequestEvent,
        metadata: CatalogGenerationMetadata,
        built_at: datetime,
    ) -> Self:
        prototype = cls.model_construct(
            idempotency_key=(f"rule-generation:build-result:{request.generation_request_id[16:]}"),
            request=request,
            generation=RuleGenerationIdentity.from_metadata(metadata),
            built_at=built_at,
            result_digest="sha256:" + "0" * 64,
        )
        return cls(
            **prototype.model_dump(exclude={"result_digest"}),
            result_digest=_event_digest(prototype, "result_digest"),
        )

    @model_validator(mode="after")
    def _result_is_canonical(self) -> RuleGenerationBuildResultEvent:
        _require_aware("built_at", self.built_at)
        request = self.request
        generation = self.generation
        if self.built_at < request.requested_at:
            raise ValueError("Rule generation build cannot precede its request")
        expected_key = f"rule-generation:build-result:{request.generation_request_id[16:]}"
        if self.idempotency_key != expected_key:
            raise ValueError("Rule generation build result idempotency key does not match")
        if (
            generation.corpus is not request.corpus
            or generation.catalog_digest != request.catalog_digest
            or generation.semantic_schema_digest != request.semantic_schema_digest
            or generation.ontology_release_digest != request.ontology_release_digest
            or generation.embedding_space_id != request.embedding_space_id
            or generation.embedding_model_version != request.embedding_model_version
            or generation.embedding_dimension != request.embedding_dimension
        ):
            raise ValueError("Rule generation build result does not match its request")
        if self.result_digest != _event_digest(self, "result_digest"):
            raise ValueError("Rule generation build result digest does not match content")
        return self


class RuleGenerationValidationResultEvent(ContractBase):
    """Independent validation evidence with no activation authority."""

    schema_version: SemVer = "1.0.0"
    event_type: Literal["rule.semantic_generation.validation.completed.v1"] = (
        "rule.semantic_generation.validation.completed.v1"
    )
    idempotency_key: Annotated[str, Field(pattern=_IDEMPOTENCY_PATTERN)]
    build_result: RuleGenerationBuildResultEvent
    valid: bool
    validation_receipt_digest: Annotated[str | None, Field(pattern=_DIGEST_PATTERN)] = None
    validator_artifact_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    failure_reason: Annotated[str | None, Field(min_length=1, max_length=128)] = None
    validated_at: datetime
    result_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    grants_authority: Literal[False] = False

    @classmethod
    def create_valid(
        cls,
        *,
        build_result: RuleGenerationBuildResultEvent,
        validation_receipt_digest: str,
        validator_artifact_digest: str,
        validated_at: datetime,
    ) -> Self:
        request_id = build_result.request.generation_request_id
        prototype = cls.model_construct(
            idempotency_key=f"rule-generation:validation:{request_id[16:]}",
            build_result=build_result,
            valid=True,
            validation_receipt_digest=validation_receipt_digest,
            validator_artifact_digest=validator_artifact_digest,
            failure_reason=None,
            validated_at=validated_at,
            result_digest="sha256:" + "0" * 64,
        )
        return cls(
            **prototype.model_dump(exclude={"result_digest"}),
            result_digest=_event_digest(prototype, "result_digest"),
        )

    @classmethod
    def create_invalid(
        cls,
        *,
        build_result: RuleGenerationBuildResultEvent,
        validator_artifact_digest: str,
        failure_reason: str,
        validated_at: datetime,
    ) -> Self:
        request_id = build_result.request.generation_request_id
        prototype = cls.model_construct(
            idempotency_key=f"rule-generation:validation:{request_id[16:]}",
            build_result=build_result,
            valid=False,
            validation_receipt_digest=None,
            validator_artifact_digest=validator_artifact_digest,
            failure_reason=failure_reason,
            validated_at=validated_at,
            result_digest="sha256:" + "0" * 64,
        )
        return cls(
            **prototype.model_dump(exclude={"result_digest"}),
            result_digest=_event_digest(prototype, "result_digest"),
        )

    @model_validator(mode="after")
    def _validation_result_is_canonical(self) -> RuleGenerationValidationResultEvent:
        _require_aware("validated_at", self.validated_at)
        if self.validated_at < self.build_result.built_at:
            raise ValueError("Rule generation validation cannot precede its build")
        if self.valid != (self.validation_receipt_digest is not None):
            raise ValueError("valid Rule generation evidence requires exactly one receipt")
        if self.valid == (self.failure_reason is not None):
            raise ValueError("invalid Rule generation evidence requires exactly one reason")
        request_id = self.build_result.request.generation_request_id
        expected_key = f"rule-generation:validation:{request_id[16:]}"
        if self.idempotency_key != expected_key:
            raise ValueError("Rule generation validation idempotency key does not match")
        if self.result_digest != _event_digest(self, "result_digest"):
            raise ValueError("Rule generation validation result digest does not match content")
        return self


class RuleGenerationActivationCommandEvent(ContractBase):
    """Governed command to activate one exact independently validated generation."""

    schema_version: SemVer = "1.0.0"
    event_type: Literal["rule.semantic_generation.activation.commanded.v1"] = (
        "rule.semantic_generation.activation.commanded.v1"
    )
    idempotency_key: Annotated[str, Field(pattern=_IDEMPOTENCY_PATTERN)]
    validation_result: RuleGenerationValidationResultEvent
    expected_active_generation: RuleGenerationIdentity | None
    commanded_at: datetime
    command_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    grants_execution_authority: Literal[False] = False

    @classmethod
    def create(
        cls,
        *,
        validation_result: RuleGenerationValidationResultEvent,
        expected_active_generation: RuleGenerationIdentity | None,
        commanded_at: datetime,
    ) -> Self:
        if not validation_result.valid:
            raise ValueError("invalid Rule generation validation cannot authorize activation")
        request_id = validation_result.build_result.request.generation_request_id
        prototype = cls.model_construct(
            idempotency_key=f"rule-generation:activation:{request_id[16:]}",
            validation_result=validation_result,
            expected_active_generation=expected_active_generation,
            commanded_at=commanded_at,
            command_digest="sha256:" + "0" * 64,
        )
        return cls(
            **prototype.model_dump(exclude={"command_digest"}),
            command_digest=_event_digest(prototype, "command_digest"),
        )

    @model_validator(mode="after")
    def _activation_command_is_canonical(self) -> RuleGenerationActivationCommandEvent:
        _require_aware("commanded_at", self.commanded_at)
        if not self.validation_result.valid:
            raise ValueError("invalid Rule generation validation cannot authorize activation")
        if self.commanded_at < self.validation_result.validated_at:
            raise ValueError("Rule generation activation cannot precede validation")
        target = self.validation_result.build_result.generation
        prior = self.expected_active_generation
        if prior is not None:
            if prior.corpus is not target.corpus:
                raise ValueError("Rule generation prior active corpus does not match target")
            if prior.generation_id == target.generation_id:
                raise ValueError("Rule generation target cannot be its own prior active generation")
        request_id = self.validation_result.build_result.request.generation_request_id
        expected_key = f"rule-generation:activation:{request_id[16:]}"
        if self.idempotency_key != expected_key:
            raise ValueError("Rule generation activation idempotency key does not match")
        if self.command_digest != _event_digest(self, "command_digest"):
            raise ValueError("Rule generation activation command digest does not match content")
        return self


class RuleGenerationActivationResultEvent(ContractBase):
    """Audit and Operator projection payload for one bounded activation outcome."""

    schema_version: SemVer = "1.0.0"
    event_type: Literal["rule.semantic_generation.activation.completed.v1"] = (
        "rule.semantic_generation.activation.completed.v1"
    )
    idempotency_key: Annotated[str, Field(pattern=_IDEMPOTENCY_PATTERN)]
    command: RuleGenerationActivationCommandEvent
    status: RuleGenerationActivationStatus
    failure_reason: Annotated[str | None, Field(min_length=1, max_length=128)] = None
    completed_at: datetime
    result_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    projection_only: Literal[True] = True
    grants_execution_authority: Literal[False] = False

    @classmethod
    def create(
        cls,
        *,
        command: RuleGenerationActivationCommandEvent,
        status: RuleGenerationActivationStatus,
        completed_at: datetime,
        failure_reason: str | None = None,
    ) -> Self:
        request_id = command.validation_result.build_result.request.generation_request_id
        prototype = cls.model_construct(
            idempotency_key=f"rule-generation:activation-result:{request_id[16:]}",
            command=command,
            status=status,
            failure_reason=failure_reason,
            completed_at=completed_at,
            result_digest="sha256:" + "0" * 64,
        )
        return cls(
            **prototype.model_dump(exclude={"result_digest"}),
            result_digest=_event_digest(prototype, "result_digest"),
        )

    @model_validator(mode="after")
    def _activation_result_is_canonical(self) -> RuleGenerationActivationResultEvent:
        _require_aware("completed_at", self.completed_at)
        if self.completed_at < self.command.commanded_at:
            raise ValueError("Rule generation activation result cannot precede its command")
        if (self.status is RuleGenerationActivationStatus.FAILED) != (
            self.failure_reason is not None
        ):
            raise ValueError("failed Rule generation activation requires exactly one reason")
        request_id = self.command.validation_result.build_result.request.generation_request_id
        expected_key = f"rule-generation:activation-result:{request_id[16:]}"
        if self.idempotency_key != expected_key:
            raise ValueError("Rule generation activation result idempotency key does not match")
        if self.result_digest != _event_digest(self, "result_digest"):
            raise ValueError("Rule generation activation result digest does not match content")
        return self


class RuleGenerationOutboxRecord(ContractBase):
    """Lease-fenced delivery state retaining one immutable activation result."""

    event: RuleGenerationActivationResultEvent
    state: RuleGenerationOutboxDeliveryState = RuleGenerationOutboxDeliveryState.PENDING
    attempts: int = Field(default=0, ge=0)
    available_at: datetime | None = None
    claimant_id: Annotated[str | None, Field(min_length=1, max_length=256)] = None
    claimed_at: datetime | None = None
    lease_until: datetime | None = None
    published_at: datetime | None = None
    last_error: Annotated[str | None, Field(min_length=1, max_length=128)] = None

    @model_validator(mode="after")
    def _delivery_state_is_consistent(self) -> RuleGenerationOutboxRecord:
        for name, value in (
            ("available_at", self.available_at),
            ("claimed_at", self.claimed_at),
            ("lease_until", self.lease_until),
            ("published_at", self.published_at),
        ):
            if value is not None:
                _require_aware(name, value)
        claimed = self.claimant_id is not None
        has_lease = self.claimed_at is not None and self.lease_until is not None
        if self.state is RuleGenerationOutboxDeliveryState.CLAIMED:
            if not claimed or not has_lease or self.published_at is not None:
                raise ValueError("claimed Rule generation outbox requires exactly one live lease")
            if self.claimed_at is None or self.lease_until is None:
                raise ValueError("claimed Rule generation outbox requires exactly one live lease")
            if self.lease_until <= self.claimed_at:
                raise ValueError("Rule generation outbox lease MUST end after claim time")
            if self.attempts < 1:
                raise ValueError("claimed Rule generation outbox requires an attempt")
            if self.last_error is not None:
                raise ValueError("claimed Rule generation outbox MUST NOT retain an error")
        elif claimed or self.claimed_at is not None or self.lease_until is not None:
            raise ValueError("unclaimed Rule generation outbox MUST NOT retain a lease")
        if self.state is RuleGenerationOutboxDeliveryState.PUBLISHED:
            if self.published_at is None or self.attempts < 1 or self.last_error is not None:
                raise ValueError("published Rule generation outbox requires clean acknowledgement")
        elif self.published_at is not None:
            raise ValueError("unpublished Rule generation outbox MUST NOT have acknowledgement")
        if self.state is RuleGenerationOutboxDeliveryState.PENDING and (
            (self.attempts > 0) != (self.last_error is not None)
        ):
            raise ValueError("retried Rule generation outbox requires exactly one error")
        return self


def _event_digest(event: ContractBase, digest_field: str) -> str:
    return _canonical_digest(event.model_dump(mode="json", exclude={digest_field}))


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Rule generation {name} MUST be timezone-aware")


__all__ = [
    "RULE_GENERATION_BUILD_REQUEST_TOPIC",
    "RULE_GENERATION_BUILD_RESULT_TOPIC",
    "RuleGenerationActivationCommandEvent",
    "RuleGenerationActivationResultEvent",
    "RuleGenerationActivationStatus",
    "RuleGenerationBuildRequestEvent",
    "RuleGenerationBuildResultEvent",
    "RuleGenerationIdentity",
    "RuleGenerationOutboxDeliveryState",
    "RuleGenerationOutboxRecord",
    "RuleGenerationValidationResultEvent",
]
