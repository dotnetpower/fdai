"""Source-bound handover semantic compilation and deterministic review, never catalog activation.

Norns invokes extraction only once per source/binding/release identity. Mimir independently reads
the private immutable result and fresh source, then recompiles without a model call. Neither
component imports Core or receives an active catalog/graph writer, executor, or promotion registry.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import (
    Callable,
    Mapping,
)
from dataclasses import (
    asdict,
    dataclass,
    replace,
)
from datetime import (
    UTC,
    datetime,
)
from typing import Any

from fdai_service_contracts import DocumentEnvelope as ServiceEnvelope
from fdai_service_contracts.handover_knowledge import (
    HandoverKnowledgeNotice,
    notice_deadline,
)
from fdai_service_contracts.handover_semantics import HandoverSemanticReceipt
from pydantic import TypeAdapter

from fdai.rule_catalog.pipeline.distill.handover_retention import retention_descriptor
from fdai.rule_catalog.pipeline.distill.handover_rules import (
    HandoverRuleCompiler,
    explicit_rule_candidates,
)
from fdai.rule_catalog.pipeline.distill.ontology_council import OntologyAwareDistiller
from fdai.rule_catalog.pipeline.distill.ontology_ingestion import manual_document_from_envelope
from fdai.rule_catalog.pipeline.distill.ontology_review import build_ontology_review_package
from fdai.rule_catalog.pipeline.distill.ontology_verify import VerificationContext
from fdai.rule_catalog.pipeline.distill.sensitivity import scan_sensitivity
from fdai.shared.providers.distiller import (
    CandidateKind,
    DistillationResult,
    Distiller,
    DistillerAvailability,
    describe_distiller,
)
from fdai.shared.providers.handover_semantics import (
    HandoverSemanticPackageStore,
    HandoverSemanticSource,
)

_RESULT = TypeAdapter(DistillationResult)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def envelope_digest(envelope: ServiceEnvelope) -> str:
    """Bind the complete source envelope and manifest; no partial chunk set stands in for it."""
    return _digest(envelope.model_dump(mode="json"))


def _identity(notice: HandoverKnowledgeNotice, compiler_digest: str) -> dict[str, Any]:
    return {
        "source_id": notice.source_id,
        "source_revision": notice.goal_revision,
        "source_digest": notice.source_digest,
        "compiler_digest": compiler_digest,
    }


def _current_budget(notice: HandoverKnowledgeNotice, at: datetime, ceiling: int) -> float:
    notice.require_current(at)
    return min(ceiling, (notice_deadline(notice) - at).total_seconds())


@dataclass(frozen=True, slots=True)
class HandoverSemanticVerification:
    """Pure deterministic compiler over fresh admitted source plus retained extraction output."""

    rules: HandoverRuleCompiler
    context: Callable[[ServiceEnvelope], VerificationContext]
    compiler_digest: str

    def compile_document(
        self,
        envelope: ServiceEnvelope,
        result: DistillationResult,
        *,
        recorded_at: str,
    ) -> dict[str, Any]:
        """Compile typed Rules and ontology proposals without opening authority gates."""
        if len(result.candidates) > 20:
            raise ValueError("semantic extraction exceeds its candidate bound")
        document = manual_document_from_envelope(envelope)
        document = replace(document, metadata={**document.metadata, "recorded_at": recorded_at})
        if not scan_sensitivity(document).is_clear:
            raise ValueError("semantic source requires sensitivity review")
        typed = explicit_rule_candidates(document)
        typed_by_id = {item.candidate_id: item for item in typed}
        proposed = {item.candidate_id: item for item in result.candidates}
        if len(proposed) != len(result.candidates) or len(typed_by_id) != len(typed):
            raise ValueError("semantic extraction contains duplicate candidate ids")
        for identity, candidate in typed_by_id.items():
            if identity in proposed and proposed[identity] != candidate:
                raise ValueError("semantic extraction conflicts with an explicit typed Rule")
        combined = {**proposed, **typed_by_id}
        if len(combined) > 20:
            raise ValueError("semantic extraction exceeds its combined candidate bound")
        # Prose Rule proposals still require a separate source-fidelity review. They cannot
        # bypass that gate by matching a marker elsewhere in the source.
        rules = self.rules.compile(document, tuple(combined.values()))
        ontology_result = replace(
            result,
            candidates=tuple(
                item
                for item in result.candidates
                if item.kind in {CandidateKind.ONTOLOGY_OBJECT, CandidateKind.ONTOLOGY_LINK}
            ),
        )
        context = self.context(envelope)
        ontology = build_ontology_review_package(
            document=document,
            result=ontology_result,
            context=context,
            extraction_run_id="handover-"
            + _digest(
                {
                    "source": envelope_digest(envelope),
                    "compiler": self.compiler_digest,
                }
            ),
        )
        proposals = tuple(item for item in ontology.proposals if item.state.value != "denied")
        return {
            "document_id": str(envelope.document_id),
            "version_id": str(envelope.version_id),
            "envelope_digest": envelope_digest(envelope),
            "normalized_digest": document.content_sha,
            "source_digest": envelope.source_sha256,
            "extraction": _RESULT.dump_python(result, mode="json"),
            "rules": list(rules),
            "ontology": asdict(ontology),
            "ontology_digest": ontology.package_digest,
            "rule_count": len(rules),
            "ontology_count": len(proposals),
            "source_coverage_complete": False,
            "rule_prose_extraction": "requires_described_provider_and_source_fidelity_review",
            "required_gates": [
                "independent_review",
                "graph_revision",
                "regression",
                "shadow",
                "promotion",
            ],
            "execution_authority": False,
            "projection_authority": False,
            "promotion_authority": False,
        }


@dataclass(frozen=True, slots=True)
class HandoverSemanticCompilation:
    """Norns extraction producer; stable claims prevent repeated model calls."""

    sources: HandoverSemanticSource
    packages: HandoverSemanticPackageStore
    distiller: Distiller
    verifier: HandoverSemanticVerification
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def compile(self, notice: HandoverKnowledgeNotice) -> HandoverSemanticReceipt:
        """Compile once inside a 120-second budget; no existing claim is silently re-executed."""
        identity = _identity(notice, self.verifier.compiler_digest)
        key = "human_assignment:semantic-package:" + _digest(identity)
        async with asyncio.timeout(_current_budget(notice, self.clock(), 120)):
            envelopes = await self.sources.read(notice)
            if not 1 <= len(envelopes) <= 4:
                raise ValueError(
                    "semantic source document count is unavailable or exceeds its bound"
                )
            notice.require_current(self.clock())
            claimed = await self.packages.claim(key, identity)
            notice.require_current(self.clock())
            if not claimed:
                retained = await self.packages.read(key)
                notice.require_current(self.clock())
                if retained is None or retained["identity"] != identity:
                    raise ValueError("semantic attempt identity is unavailable")
                if retained.get("retired") is True:
                    return _receipt(identity, key, {}, "held", "source_changed")
                if retained.get("package") is None:
                    return _receipt(identity, key, {}, "held", "attempt_interrupted")
                return await HandoverSemanticReview(
                    self.sources,
                    self.packages,
                    self.verifier,
                    self.clock,
                ).review(
                    notice,
                    HandoverSemanticReceipt.model_validate(retained["package"]["receipt"]),
                )
            recorded_at = self.clock().isoformat()
            documents: list[dict[str, Any]] = []
            described = describe_distiller(self.distiller)
            for envelope in envelopes:
                notice.require_current(self.clock())
                manual = manual_document_from_envelope(envelope)
                if not scan_sensitivity(manual).is_clear:
                    raise ValueError("semantic source requires sensitivity review")
                extracted = DistillationResult()
                if described.availability is DistillerAvailability.AVAILABLE:
                    if isinstance(self.distiller, OntologyAwareDistiller):
                        extracted = await self.distiller.distill_ontology(
                            manual, self.verifier.context(envelope)
                        )
                    else:
                        extracted = await self.distiller.distill(manual)
                documents.append(
                    self.verifier.compile_document(envelope, extracted, recorded_at=recorded_at)
                )
            if tuple(envelope_digest(item) for item in await self.sources.read(notice)) != tuple(
                envelope_digest(item) for item in envelopes
            ):
                raise ValueError("semantic source changed during extraction")
            notice.require_current(self.clock())
            body = {
                "identity": identity,
                "recorded_at": recorded_at,
                "documents": documents,
                "retention": retention_descriptor(notice, envelopes),
            }
            rules = sum(item["rule_count"] for item in documents)
            ontology = sum(item["ontology_count"] for item in documents)
            receipt = _receipt(
                identity,
                key,
                body,
                "review_required" if rules + ontology else "held",
                "candidates_compiled" if rules + ontology else "no_supported_candidates",
                rules,
                ontology,
            )
            await self.packages.complete(
                key, identity, {**body, "receipt": receipt.model_dump(mode="json")}
            )
            notice.require_current(self.clock())
            return receipt


@dataclass(frozen=True, slots=True)
class HandoverSemanticReview:
    """Mimir deterministic source/package readback; has no model or catalog writer."""

    sources: HandoverSemanticSource
    packages: HandoverSemanticPackageStore
    verifier: HandoverSemanticVerification
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def maintain(self, notice: HandoverKnowledgeNotice, *, withdrawn: bool) -> int:
        """Retire exact-source packages under current legal-hold policy without widening access."""
        async with asyncio.timeout(_current_budget(notice, self.clock(), 30)):
            return await self.packages.reconcile(notice, withdrawn=withdrawn)

    async def review(
        self,
        notice: HandoverKnowledgeNotice,
        receipt: HandoverSemanticReceipt,
    ) -> HandoverSemanticReceipt:
        """Recompile exact retained outputs against independent current sources; mismatch holds."""
        async with asyncio.timeout(_current_budget(notice, self.clock(), 60)):
            identity = _identity(notice, self.verifier.compiler_digest)
            key = "human_assignment:semantic-package:" + _digest(identity)
            if (
                receipt.source_id != notice.source_id
                or receipt.source_revision != notice.goal_revision
                or receipt.source_digest != notice.source_digest
                or receipt.compiler_digest != self.verifier.compiler_digest
                or receipt.package_ref != key
            ):
                raise ValueError("semantic receipt source or compiler identity differs")
            envelopes = await self.sources.read(notice)
            notice.require_current(self.clock())
            retained = await self.packages.read(receipt.package_ref)
            if (
                retained is None
                or retained.get("retired") is True
                or retained.get("identity") != identity
                or not isinstance(retained.get("package"), Mapping)
            ):
                raise ValueError("semantic package is unavailable")
            package = retained["package"]
            if package.get("retention") != retention_descriptor(notice, envelopes):
                raise ValueError("semantic package source retention or access changed")
            if package.get("identity") != identity or package.get("receipt") != receipt.model_dump(
                mode="json"
            ):
                raise ValueError("semantic receipt does not match the immutable package")
            body = {key: value for key, value in package.items() if key != "receipt"}
            if _digest(body) != receipt.package_digest:
                raise ValueError("semantic package content digest differs")
            documents = package.get("documents", [])
            if len(documents) != len(envelopes) or not 1 <= len(envelopes) <= 4:
                raise ValueError("semantic package source coverage differs")
            for document, envelope in zip(documents, envelopes, strict=True):
                checked = self.verifier.compile_document(
                    envelope,
                    _RESULT.validate_python(document["extraction"]),
                    recorded_at=package["recorded_at"],
                )
                if _digest(checked) != _digest(document):
                    raise ValueError("semantic candidate deterministic verification changed")
            rules = sum(item["rule_count"] for item in documents)
            ontology = sum(item["ontology_count"] for item in documents)
            expected = _receipt(
                identity,
                key,
                body,
                "review_required" if rules + ontology else "held",
                "candidates_compiled" if rules + ontology else "no_supported_candidates",
                rules,
                ontology,
            )
            if receipt != expected:
                raise ValueError("semantic receipt differs from independently verified candidates")
            if tuple(envelope_digest(item) for item in await self.sources.read(notice)) != tuple(
                envelope_digest(item) for item in envelopes
            ):
                raise ValueError("semantic source changed during verification")
            notice.require_current(self.clock())
            return receipt


def _receipt(
    identity: Mapping[str, Any],
    key: str,
    body: Mapping[str, Any],
    disposition: str,
    reason: str,
    rules: int = 0,
    ontology: int = 0,
) -> HandoverSemanticReceipt:
    return HandoverSemanticReceipt.model_validate(
        {
            **identity,
            "package_ref": key,
            "package_digest": _digest(body),
            "disposition": disposition,
            "reason": reason,
            "rule_count": rules,
            "ontology_count": ontology,
        }
    )


__all__ = [
    "HandoverSemanticCompilation",
    "HandoverSemanticReview",
    "HandoverSemanticVerification",
    "envelope_digest",
]
