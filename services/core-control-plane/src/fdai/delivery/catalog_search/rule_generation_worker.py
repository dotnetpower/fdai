"""Durable mechanical workers for Rule semantic generation build and validation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.delivery.catalog_search.generation import SemanticGenerationBuild
from fdai.delivery.catalog_search.rule_generation import (
    build_rule_semantic_generation,
    validate_rule_semantic_generation,
)
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RuleGenerationBuildRequestEvent,
    RuleGenerationBuildResultEvent,
    RuleGenerationIdentity,
    RuleGenerationValidationResultEvent,
)
from fdai.shared.providers.catalog_search import (
    CatalogSearchDocument,
    CatalogSemanticIndex,
    catalog_search_document_digest,
)
from fdai.shared.providers.state_store import StateStore

_BUILD_KEY_PREFIX = "rule-semantic-generation:build:"
_VALIDATION_KEY_PREFIX = "rule-semantic-generation:validation:"
_SCHEMA_VERSION = "1.0.0"
RULE_GENERATION_VALIDATOR_ARTIFACT_DIGEST = (
    "sha256:" + hashlib.sha256(b"fdai-rule-semantic-generation-validator:1.0.0").hexdigest()
)


class RuleGenerationDocumentResolver(Protocol):
    """Resolve exact candidate rows for one content-addressed build request."""

    async def resolve(
        self,
        request: RuleGenerationBuildRequestEvent,
    ) -> Sequence[CatalogSearchDocument]: ...


@dataclass(frozen=True, slots=True)
class ExactRuleGenerationDocumentResolver:
    """Return one startup snapshot only for its exact generation identity."""

    active_documents: tuple[CatalogSearchDocument, ...]
    discovery_documents: tuple[CatalogSearchDocument, ...]
    catalog_digest: str
    semantic_schema_digest: str
    ontology_release_digest: str
    embedding_space_id: str
    embedding_model_version: str
    embedding_dimension: int

    async def resolve(
        self,
        request: RuleGenerationBuildRequestEvent,
    ) -> tuple[CatalogSearchDocument, ...]:
        expected = {
            "catalog_digest": self.catalog_digest,
            "semantic_schema_digest": self.semantic_schema_digest,
            "ontology_release_digest": self.ontology_release_digest,
            "embedding_space_id": self.embedding_space_id,
            "embedding_model_version": self.embedding_model_version,
            "embedding_dimension": self.embedding_dimension,
        }
        mismatches = tuple(
            field for field, value in expected.items() if getattr(request, field) != value
        )
        if mismatches:
            raise ValueError(
                "Rule generation request identity does not match startup snapshot: "
                + ", ".join(mismatches)
            )
        if request.corpus.value == "active":
            return self.active_documents
        return self.discovery_documents


@dataclass(frozen=True, slots=True)
class RuleGenerationBuildWorker:
    """Build and stage one Mimir-owned generation without activation authority."""

    index: CatalogSemanticIndex
    resolver: RuleGenerationDocumentResolver
    store: StateStore
    clock: Any = lambda: datetime.now(UTC)

    async def handle(
        self,
        request: RuleGenerationBuildRequestEvent,
    ) -> RuleGenerationBuildResultEvent:
        validated = RuleGenerationBuildRequestEvent.model_validate(request.model_dump())
        key = f"{_BUILD_KEY_PREFIX}{validated.generation_request_id}"
        existing = await self.store.read_state(key)
        if existing is not None:
            return _parse_result(
                existing,
                event_type=RuleGenerationBuildResultEvent,
                expected_request_digest=validated.request_digest,
            )

        documents = tuple(await self.resolver.resolve(validated))
        build = build_rule_semantic_generation(
            documents=documents,
            corpus=validated.corpus.value,
            catalog_digest=validated.catalog_digest,
            semantic_schema_digest=validated.semantic_schema_digest,
            ontology_release_digest=validated.ontology_release_digest,
            embedding_space_id=validated.embedding_space_id,
            embedding_model_version=validated.embedding_model_version,
            embedding_dimension=validated.embedding_dimension,
        )
        await self.index.stage_generation(build.metadata, build.documents)
        result = RuleGenerationBuildResultEvent.create(
            request=validated,
            metadata=build.metadata,
            built_at=max(self.clock(), validated.requested_at),
        )
        return await _commit_first_result(
            store=self.store,
            key=key,
            result=result,
            expected_request_digest=validated.request_digest,
            principal="Mimir",
            action_kind="rule_generation.build_completed",
        )


@dataclass(frozen=True, slots=True)
class RuleGenerationValidationWorker:
    """Independently validate one staged generation as Heimdall."""

    index: CatalogSemanticIndex
    store: StateStore
    validator_artifact_digest: str
    clock: Any = lambda: datetime.now(UTC)

    async def handle(
        self,
        build_result: RuleGenerationBuildResultEvent,
    ) -> RuleGenerationValidationResultEvent:
        validated = RuleGenerationBuildResultEvent.model_validate(build_result.model_dump())
        request = validated.request
        key = f"{_VALIDATION_KEY_PREFIX}{request.generation_request_id}"
        existing = await self.store.read_state(key)
        if existing is not None:
            return _parse_result(
                existing,
                event_type=RuleGenerationValidationResultEvent,
                expected_request_digest=request.request_digest,
            )

        validated_at = max(self.clock(), validated.built_at)
        snapshot = await self.index.generation_validation_snapshot(
            validated.generation.generation_id
        )
        if snapshot is None:
            result = RuleGenerationValidationResultEvent.create_invalid(
                build_result=validated,
                validator_artifact_digest=self.validator_artifact_digest,
                failure_reason="generation_unavailable",
                validated_at=validated_at,
            )
        elif RuleGenerationIdentity.from_metadata(snapshot.metadata) != validated.generation:
            result = RuleGenerationValidationResultEvent.create_invalid(
                build_result=validated,
                validator_artifact_digest=self.validator_artifact_digest,
                failure_reason="generation_identity_mismatch",
                validated_at=validated_at,
            )
        else:
            result = self._validate_snapshot(validated, snapshot.documents, snapshot.metadata)
        return await _commit_first_result(
            store=self.store,
            key=key,
            result=result,
            expected_request_digest=request.request_digest,
            principal="Heimdall",
            action_kind="rule_generation.validation_completed",
        )

    def _validate_snapshot(
        self,
        build_result: RuleGenerationBuildResultEvent,
        documents: tuple[CatalogSearchDocument, ...],
        metadata: Any,
    ) -> RuleGenerationValidationResultEvent:
        request = build_result.request
        validated_at = max(self.clock(), build_result.built_at)
        build = SemanticGenerationBuild(
            metadata=metadata,
            documents=documents,
            document_digests=tuple(
                catalog_search_document_digest(document) for document in documents
            ),
            reused_document_count=0,
        )
        try:
            receipt = validate_rule_semantic_generation(
                build=build,
                corpus=request.corpus.value,
                catalog_digest=request.catalog_digest,
                semantic_schema_digest=request.semantic_schema_digest,
                ontology_release_digest=request.ontology_release_digest,
                embedding_space_id=request.embedding_space_id,
                embedding_model_version=request.embedding_model_version,
                embedding_dimension=request.embedding_dimension,
                validator_artifact_digest=self.validator_artifact_digest,
            )
        except ValueError:
            return RuleGenerationValidationResultEvent.create_invalid(
                build_result=build_result,
                validator_artifact_digest=self.validator_artifact_digest,
                failure_reason="generation_validation_failed",
                validated_at=validated_at,
            )
        return RuleGenerationValidationResultEvent.create_valid(
            build_result=build_result,
            validation_receipt_digest=receipt.receipt_digest,
            validator_artifact_digest=self.validator_artifact_digest,
            validated_at=validated_at,
        )


async def _commit_first_result[
    ResultEvent: (RuleGenerationBuildResultEvent, RuleGenerationValidationResultEvent)
](
    *,
    store: StateStore,
    key: str,
    result: ResultEvent,
    expected_request_digest: str,
    principal: str,
    action_kind: str,
) -> ResultEvent:
    record = {
        "schema_version": _SCHEMA_VERSION,
        "kind": action_kind,
        "request_digest": expected_request_digest,
        "result": result.model_dump(mode="json"),
    }
    audit = {
        "kind": "rule_semantic_generation",
        "action_kind": action_kind,
        "principal": principal,
        "idempotency_key": result.idempotency_key,
        "request_digest": expected_request_digest,
        "result_digest": result.result_digest,
        "grants_authority": False,
    }
    if await store.write_state_with_audit_if_absent(key, record, audit):
        return result
    existing = await store.read_state(key)
    if existing is None:
        raise RuntimeError("Rule generation result write lost its durable state")
    return _parse_result(
        existing,
        event_type=type(result),
        expected_request_digest=expected_request_digest,
    )


def _parse_result[
    ResultEvent: (RuleGenerationBuildResultEvent, RuleGenerationValidationResultEvent)
](
    record: Mapping[str, Any],
    *,
    event_type: type[ResultEvent],
    expected_request_digest: str,
) -> ResultEvent:
    if record.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("Durable Rule generation result has an unsupported schema")
    if record.get("request_digest") != expected_request_digest:
        raise ValueError("Rule generation request identity was reused with another payload")
    raw_result = record.get("result")
    if not isinstance(raw_result, Mapping):
        raise ValueError("Durable Rule generation result is malformed")
    result = event_type.model_validate(raw_result)
    request = (
        result.request
        if isinstance(result, RuleGenerationBuildResultEvent)
        else result.build_result.request
    )
    if request.request_digest != expected_request_digest:
        raise ValueError("Durable Rule generation result request identity mismatch")
    return result


__all__ = [
    "RULE_GENERATION_VALIDATOR_ARTIFACT_DIGEST",
    "ExactRuleGenerationDocumentResolver",
    "RuleGenerationBuildWorker",
    "RuleGenerationDocumentResolver",
    "RuleGenerationValidationWorker",
]
