"""Deterministic artifact-manifest construction for extracted documents."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from fdai_service_contracts import (
    ArtifactManifestEntry,
    DocumentArtifactKind,
    DocumentArtifactManifest,
    DocumentEnvelope,
    DocumentVersion,
    StructuralUnit,
)

_PDF_OCR_LOCATOR = re.compile(r"(?:pdf/)?page:(\d+)/(?:ocr|block):\d+|page:(\d+):line:\d+")
_EMBEDDED_OCR_LOCATOR = re.compile(r"ooxml/embedded-image:(\d+)/ocr:\d+")


def build_artifact_manifest(
    *,
    envelope: DocumentEnvelope,
    version: DocumentVersion,
    observed_at: datetime,
    source_retained: bool = True,
) -> DocumentArtifactManifest:
    """Build the complete retained and discarded lineage for one extraction."""
    source_id = "source"
    entries: list[ArtifactManifestEntry] = [
        ArtifactManifestEntry(
            artifact_id=source_id,
            kind=DocumentArtifactKind.SOURCE,
            content_sha256=version.source_sha256,
            locator="source",
            media_type=version.media_type,
            size_bytes=version.size_bytes,
            retained=source_retained,
            expires_at=version.retention.source_expires_at if source_retained else None,
        )
    ]

    transient_parents = _transient_image_entries(envelope, source_id=source_id)
    entries.extend(transient_parents.values())
    unit_ids = {
        unit.locator: f"unit-{position}-{_short_digest(unit.locator.encode())}"
        for position, unit in enumerate(envelope.units, start=1)
    }
    for position, unit in enumerate(envelope.units, start=1):
        entries.append(
            _unit_entry(
                unit,
                position=position,
                parent_id=_unit_parent(
                    unit,
                    transient_parents,
                    unit_ids=unit_ids,
                    source_id=source_id,
                ),
                expires_at=version.retention.derived_expires_at,
            )
        )

    normalized = _canonical_bytes(envelope.model_dump(mode="json", exclude={"artifact_manifest"}))
    entries.append(
        ArtifactManifestEntry(
            artifact_id="normalized-envelope",
            parent_artifact_id=source_id,
            kind=DocumentArtifactKind.NORMALIZED_ENVELOPE,
            content_sha256=hashlib.sha256(normalized).hexdigest(),
            locator="envelope",
            media_type="application/json",
            size_bytes=len(normalized),
            retained=True,
            expires_at=version.retention.derived_expires_at,
        )
    )
    return DocumentArtifactManifest(
        document_id=version.document_id,
        version_id=version.version_id,
        source_sha256=version.source_sha256,
        access=version.access,
        retention=version.retention,
        disposition=version.disposition,
        scope_kind=version.scope_kind,
        scope_ref=version.scope_ref,
        entries=tuple(entries),
        extractor_name=envelope.extractor_name,
        extractor_version=envelope.extractor_version,
        created_at=observed_at,
        updated_at=observed_at,
    )


def attach_artifact_manifest(
    *,
    envelope: DocumentEnvelope,
    version: DocumentVersion,
    observed_at: datetime,
    source_retained: bool = True,
) -> DocumentEnvelope:
    """Return an envelope whose manifest is validated before artifact persistence."""
    manifest = build_artifact_manifest(
        envelope=envelope,
        version=version,
        observed_at=observed_at,
        source_retained=source_retained,
    )
    return DocumentEnvelope.model_validate(
        envelope.model_dump(mode="python") | {"artifact_manifest": manifest}
    )


def _unit_entry(
    unit: StructuralUnit,
    *,
    position: int,
    parent_id: str,
    expires_at: datetime | None,
) -> ArtifactManifestEntry:
    content = unit.text.encode("utf-8")
    return ArtifactManifestEntry(
        artifact_id=f"unit-{position}-{_short_digest(unit.locator.encode())}",
        parent_artifact_id=parent_id,
        kind=(
            DocumentArtifactKind.OCR_TEXT
            if "/ocr:" in unit.locator or re.search(r"page:\d+:line:\d+", unit.locator)
            else DocumentArtifactKind.NATIVE_TEXT
        ),
        content_sha256=hashlib.sha256(content).hexdigest(),
        locator=unit.locator,
        media_type="text/plain; charset=utf-8",
        size_bytes=len(content),
        retained=True,
        expires_at=expires_at,
    )


def _transient_image_entries(
    envelope: DocumentEnvelope,
    *,
    source_id: str,
) -> dict[str, ArtifactManifestEntry]:
    locators: dict[str, tuple[DocumentArtifactKind, str]] = {}
    for unit in envelope.units:
        embedded = _EMBEDDED_OCR_LOCATOR.fullmatch(unit.locator)
        if embedded is not None:
            locator = f"ooxml/embedded-image:{embedded.group(1)}"
            locators[locator] = (DocumentArtifactKind.EMBEDDED_IMAGE, "application/octet-stream")
            continue
        if envelope.observed_format == "pdf" and (
            "/ocr:" in unit.locator or re.fullmatch(r"page:\d+:line:\d+", unit.locator)
        ):
            match = _PDF_OCR_LOCATOR.fullmatch(unit.locator)
            if match is not None:
                page = match.group(1) or match.group(2)
                locator = f"pdf/page:{page}/raster"
                locators[locator] = (DocumentArtifactKind.PAGE_RASTER, "image/png")

    return {
        locator: ArtifactManifestEntry(
            artifact_id=f"discarded-{kind.value}-{_short_digest(locator.encode())}",
            parent_artifact_id=source_id,
            kind=kind,
            locator=locator,
            media_type=media_type,
            retained=False,
            expires_at=None,
        )
        for locator, (kind, media_type) in sorted(locators.items())
    }


def _unit_parent(
    unit: StructuralUnit,
    transient_parents: dict[str, ArtifactManifestEntry],
    *,
    unit_ids: dict[str, str],
    source_id: str,
) -> str:
    embedded = _EMBEDDED_OCR_LOCATOR.fullmatch(unit.locator)
    if embedded is not None:
        locator = f"ooxml/embedded-image:{embedded.group(1)}"
        return transient_parents[locator].artifact_id
    match = _PDF_OCR_LOCATOR.fullmatch(unit.locator)
    if match is not None and (
        "/ocr:" in unit.locator or re.fullmatch(r"page:\d+:line:\d+", unit.locator)
    ):
        page = match.group(1) or match.group(2)
        locator = f"pdf/page:{page}/raster"
        transient = transient_parents.get(locator)
        if transient is not None:
            return transient.artifact_id
    if unit.parent_locator is not None and unit.parent_locator in unit_ids:
        return unit_ids[unit.parent_locator]
    if unit.parent_locator is not None:
        raise ValueError("artifact unit parent locator does not exist")
    return source_id


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _short_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()[:16]
