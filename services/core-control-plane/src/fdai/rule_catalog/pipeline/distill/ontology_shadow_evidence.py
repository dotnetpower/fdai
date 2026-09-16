"""Governed immutable-file collection for ontology live-shadow evidence."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from fdai.rule_catalog.pipeline.distill.ontology_evaluation import (
    PromotionPolicy,
    ShadowReviewEvidenceBatch,
    ShadowReviewEvidenceVerifier,
    ShadowReviewOutcome,
)
from fdai.rule_catalog.pipeline.distill.ontology_shadow_evidence_io import (
    MAX_BATCH_BYTES,
    MAX_MANIFEST_BYTES,
    aware_now,
    bounded_batch_path,
    decode_batch,
    digest_text,
    digest_value,
    encode_batch,
    exact_fields,
    manifest_mapping,
    object_value,
    publish_exclusive,
    read_bounded_regular_file,
    revision_text,
    sha256,
    text_value,
)


@dataclass(frozen=True, slots=True)
class ShadowReviewBatchAttestation:
    """Expected immutable identity for one mounted shadow evidence batch."""

    path: Path
    content_digest: str
    fdai_revision: str
    ontology_release: str
    binding_digest: str
    policy_digest: str


@dataclass(frozen=True, slots=True)
class ShadowReviewEvidenceManifest:
    """Deployment-reviewed bounds for one content-free shadow evidence batch."""

    batch: ShadowReviewBatchAttestation
    source_receipt_digest: str
    review_receipt_digests: frozenset[str]

    @classmethod
    def load(cls, path: Path) -> ShadowReviewEvidenceManifest:
        """Load a strict manifest without accepting inline review outcomes."""
        raw = object_value(
            json.loads(read_bounded_regular_file(path, MAX_MANIFEST_BYTES)),
            "manifest",
        )
        exact_fields(
            raw,
            {"schema_version", "batch", "source_receipt_digest", "review_receipt_digests"},
            "manifest",
        )
        if raw["schema_version"] != "1.0.0":
            raise ValueError("unsupported ontology shadow evidence manifest")
        batch_raw = object_value(raw["batch"], "manifest batch")
        exact_fields(
            batch_raw,
            {
                "path",
                "content_digest",
                "fdai_revision",
                "ontology_release",
                "binding_digest",
                "policy_digest",
            },
            "manifest batch",
        )
        base = path.parent.resolve(strict=True)
        review_receipts = frozenset(
            digest_value(item) for item in _list(raw, "review_receipt_digests")
        )
        if not review_receipts:
            raise ValueError("ontology shadow manifest review receipts MUST be non-empty")
        return cls(
            batch=ShadowReviewBatchAttestation(
                path=bounded_batch_path(base, text_value(batch_raw, "path")),
                content_digest=digest_text(batch_raw, "content_digest"),
                fdai_revision=revision_text(batch_raw, "fdai_revision"),
                ontology_release=digest_text(batch_raw, "ontology_release"),
                binding_digest=digest_text(batch_raw, "binding_digest"),
                policy_digest=digest_text(batch_raw, "policy_digest"),
            ),
            source_receipt_digest=digest_text(raw, "source_receipt_digest"),
            review_receipt_digests=review_receipts,
        )


class ImmutableFileShadowReviewEvidenceSource:
    """Load only an exact-digest shadow batch declared by a reviewed manifest."""

    def __init__(self, manifest: ShadowReviewEvidenceManifest) -> None:
        self._attestation = manifest.batch

    async def load_batch(
        self,
        *,
        fdai_revision: str,
        ontology_release: str,
        binding_digest: str,
        policy_digest: str,
    ) -> ShadowReviewEvidenceBatch:
        text = await asyncio.to_thread(
            read_bounded_regular_file,
            self._attestation.path,
            MAX_BATCH_BYTES,
        )
        batch = decode_batch(text)
        if batch.content_digest != self._attestation.content_digest:
            raise ValueError("ontology shadow evidence batch digest mismatch")
        expected = (
            self._attestation.fdai_revision,
            self._attestation.ontology_release,
            self._attestation.binding_digest,
            self._attestation.policy_digest,
        )
        actual = (
            fdai_revision,
            ontology_release,
            binding_digest,
            policy_digest,
        )
        if actual != expected:
            raise ValueError("ontology shadow evidence requested identity mismatch")
        if (
            batch.fdai_revision,
            batch.ontology_release,
            batch.binding_digest,
            batch.policy_digest,
        ) != expected:
            raise ValueError("ontology shadow evidence batch identity mismatch")
        return batch


class ManifestShadowReviewEvidenceVerifier(ShadowReviewEvidenceVerifier):
    """Authenticate batch, source, and review receipt identity against a manifest."""

    def __init__(self, manifest: ShadowReviewEvidenceManifest) -> None:
        self._manifest = manifest

    def verify(self, batch: ShadowReviewEvidenceBatch) -> bool:
        attestation = self._manifest.batch
        return (
            batch.content_digest == attestation.content_digest
            and batch.fdai_revision == attestation.fdai_revision
            and batch.ontology_release == attestation.ontology_release
            and batch.binding_digest == attestation.binding_digest
            and batch.policy_digest == attestation.policy_digest
            and batch.source_receipt_digest == self._manifest.source_receipt_digest
            and frozenset(item.review_receipt_digest for item in batch.outcomes)
            == self._manifest.review_receipt_digests
        )


class ShadowReviewOutcomeSource(Protocol):
    """Deployment-owned read source for already audited review outcomes."""

    async def load_outcomes(
        self,
        *,
        fdai_revision: str,
        ontology_release: str,
        binding_digest: str,
        policy_digest: str,
    ) -> Sequence[ShadowReviewOutcome]: ...


@dataclass(frozen=True, slots=True)
class ShadowReviewBatchArtifact:
    """Immutable batch and manifest produced from governed review outcomes."""

    batch: ShadowReviewEvidenceBatch
    batch_path: Path
    manifest_path: Path
    manifest: ShadowReviewEvidenceManifest


class GovernedShadowReviewBatchProducer:
    """Seal audited outcomes without granting ontology promotion authority."""

    def __init__(
        self,
        *,
        source: ShadowReviewOutcomeSource,
        output_dir: Path,
        clock: object = None,
    ) -> None:
        self._source = source
        self._output_dir = output_dir
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def produce(
        self,
        *,
        fdai_revision: str,
        ontology_release: str,
        binding_digest: str,
        policy: PromotionPolicy,
        source_receipt_digest: str,
    ) -> ShadowReviewBatchArtifact:
        """Read, validate, and publish one content-addressed evidence snapshot."""
        outcomes = tuple(
            await self._source.load_outcomes(
                fdai_revision=fdai_revision,
                ontology_release=ontology_release,
                binding_digest=binding_digest,
                policy_digest=policy.policy_digest,
            )
        )
        if not outcomes:
            raise ValueError("ontology shadow evidence batch MUST contain outcomes")
        batch = ShadowReviewEvidenceBatch(
            fdai_revision=fdai_revision,
            ontology_release=ontology_release,
            binding_digest=binding_digest,
            policy_digest=policy.policy_digest,
            sealed_at=aware_now(self._clock),
            source_receipt_digest=source_receipt_digest,
            outcomes=outcomes,
        )
        batch_bytes = encode_batch(batch)
        if len(batch_bytes) > MAX_BATCH_BYTES:
            raise ValueError("ontology shadow evidence batch exceeds its byte limit")
        self._output_dir.mkdir(parents=True, exist_ok=True)
        batch_path = self._output_dir / f"{batch.content_digest}.batch.json"
        manifest_mapping_value = manifest_mapping(batch, batch_path.name)
        manifest_bytes = json.dumps(
            manifest_mapping_value,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        manifest_digest = sha256(manifest_bytes)
        manifest_path = self._output_dir / f"{manifest_digest}.manifest.json"
        publish_exclusive(batch_path, batch_bytes, kind="batch")
        publish_exclusive(manifest_path, manifest_bytes, kind="manifest")
        manifest = ShadowReviewEvidenceManifest.load(manifest_path)
        if not ManifestShadowReviewEvidenceVerifier(manifest).verify(batch):
            raise ValueError("published ontology shadow evidence failed manifest verification")
        return ShadowReviewBatchArtifact(batch, batch_path, manifest_path, manifest)


def _list(raw: Mapping[str, Any], name: str) -> list[object]:
    value = raw.get(name)
    if not isinstance(value, list):
        raise ValueError(f"ontology shadow evidence {name} MUST be an array")
    return value


__all__ = [
    "GovernedShadowReviewBatchProducer",
    "ImmutableFileShadowReviewEvidenceSource",
    "ManifestShadowReviewEvidenceVerifier",
    "ShadowReviewBatchArtifact",
    "ShadowReviewBatchAttestation",
    "ShadowReviewEvidenceManifest",
    "ShadowReviewOutcomeSource",
]
