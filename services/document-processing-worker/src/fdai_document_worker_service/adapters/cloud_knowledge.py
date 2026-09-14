"""Revalidate knowledge provenance and extract only its licensed normalized passages."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from datetime import UTC, datetime

from fdai_service_contracts import DocumentVersion, StructuralUnit
from fdai_service_contracts.cloud_knowledge import (
    SourceRegistryRevision,
    canonical_bytes,
    content_digest,
)
from fdai_service_contracts.cloud_knowledge_admission import validate_admitted_binding
from fdai_service_contracts.cloud_knowledge_package import KnowledgeTrustPolicy
from fdai_service_contracts.cloud_knowledge_release import KnowledgeReleaseManifest


class CloudReferenceGuard:
    """Read current independent policy at execution, not a package-supplied approval."""

    def __init__(self, environ: Mapping[str, str]) -> None:
        self._registry = environ.get("FDAI_CLOUD_KNOWLEDGE_REGISTRY_PATH", "")
        self._trust = environ.get("FDAI_CLOUD_KNOWLEDGE_TRUST_PATH", "")

    def check(self, version: DocumentVersion, now: datetime) -> None:
        binding = version.cloud_knowledge
        if binding is None:
            return
        if now >= binding.admission_expires_at:
            raise ValueError("knowledge admission has expired")
        if not self._registry or not self._trust:
            raise ValueError("knowledge worker requires independent current policies")
        registry = SourceRegistryRevision.model_validate_json(_policy_bytes(self._registry))
        trust = KnowledgeTrustPolicy.model_validate_json(_policy_bytes(self._trust))
        validate_admitted_binding(binding, registry=registry, trust=trust, now=now)


def _policy_bytes(path: str) -> bytes:
    """Bound the same no-follow file descriptor that is inspected, including after replacement."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("knowledge policy must be a bounded regular file")
        content = stream.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ValueError("knowledge policy exceeds its byte limit")
    return content


def cloud_reference_units(version: DocumentVersion, content: bytes) -> tuple[StructuralUnit, ...]:
    """Decode the sealed generation; JSON containers and original HTML never enter model context."""
    binding = version.cloud_knowledge
    if binding is None:
        raise ValueError("cloud reference extraction requires verified provenance")
    manifest = KnowledgeReleaseManifest.model_validate_json(content)
    if canonical_bytes(manifest) != content or manifest.digest != binding.manifest_digest:
        raise ValueError("knowledge source no longer matches its admitted manifest")
    if (
        manifest.collection_id != version.access.collection_id
        or manifest.registry_digest != binding.registry_digest
        or tuple(doc.evidence for doc in manifest.documents) != binding.sources
    ):
        raise ValueError("knowledge source metadata does not match the admitted document")
    units = []
    for document in manifest.documents:
        evidence = document.evidence
        context = (
            f"Source: {evidence.source_url}\nResource: {evidence.applicability.resource_type}\n"
            f"Generation: {evidence.applicability.service_generation}; "
            f"SKU: {', '.join(evidence.applicability.skus) or 'not specified'}\n"
        )
        sections = re.split(r"(?m)(?=^#{1,6} )", document.text)
        for section_number, section in enumerate(sections):
            if not section.strip():
                continue
            heading = section.splitlines()[0].lstrip("# ")[:200]
            # Keep complete structural sections: arbitrary slices can detach a table's
            # header, caveat, or footnote. Oversized sections fail closed in v1.
            text = context + f"Section: {heading}\n" + section
            if len(text.encode("utf-8")) > 8192:
                raise ValueError("cloud source section exceeds the safe excerpt byte limit")
            identity = (
                f"cloud:{content_digest(evidence.source_id.encode())[:16]}:{section_number}:0"
            )
            units.append(
                StructuralUnit(
                    unit_id=identity,
                    kind="text",
                    locator=identity,
                    section_name=heading,
                    text=text,
                )
            )
    return tuple(units)


def utc_now() -> datetime:
    return datetime.now(tz=UTC)
