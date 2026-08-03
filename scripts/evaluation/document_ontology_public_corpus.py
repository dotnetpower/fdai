#!/usr/bin/env python3
"""Evaluate pinned public manuals without retaining or reporting source text."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import sys
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPMessage
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import NAMESPACE_URL, uuid5

from fdai.rule_catalog.pipeline.distill.ontology_claims import inventory_claims
from fdai.rule_catalog.pipeline.distill.ontology_ingestion import manual_document_from_envelope
from fdai.rule_catalog.pipeline.distill.ontology_models import ClaimKind, stable_digest
from fdai.shared.contracts import (
    AccessDescriptor,
    DocumentPurpose,
    DocumentState,
    DocumentVersion,
    ProtectionState,
    RetentionPolicy,
)
from fdai.shared.providers.distiller import Distiller
from fdai.shared.providers.local.document_ingestion import (
    SignatureProtectionInspector,
    StandardLibraryDocumentExtractor,
)

_ALLOWED_SOURCE_HOSTS = frozenset({"raw.githubusercontent.com"})
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_LINE_LOCATOR = re.compile(r"^line:([1-9][0-9]*)$")
_RANGE_LOCATOR = re.compile(r"/lines:([1-9][0-9]*)-([1-9][0-9]*)(?:/|$)")
_SOURCE_KEYS = frozenset(
    {
        "id",
        "url",
        "sha256",
        "license_id",
        "license_source",
        "format",
        "language",
        "source_line_count",
        "source_bytes",
        "critical_claims",
    }
)
_ANNOTATION_KEYS = frozenset({"locator", "text_sha256", "expected_claim_signals"})
_FORMAT_SUFFIX = {"markdown": ".md", "sgml": ".sgml"}
_EVALUATION_TIME = datetime(2026, 8, 3, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CriticalClaimAnnotation:
    locator: str
    text_sha256: str
    expected_claim_signals: tuple[str, ...]

    @property
    def line_number(self) -> int:
        match = _LINE_LOCATOR.fullmatch(self.locator)
        if match is None:
            raise ValueError("critical claim locator MUST use line:<positive integer>")
        return int(match.group(1))


@dataclass(frozen=True, slots=True)
class PublicCorpusSource:
    source_id: str
    url: str
    sha256: str
    license_id: str
    license_source: str
    source_format: str
    language: str
    source_line_count: int
    source_bytes: int
    critical_claims: tuple[CriticalClaimAnnotation, ...]


@dataclass(frozen=True, slots=True)
class PublicCorpusManifest:
    schema_version: int
    sources: tuple[PublicCorpusSource, ...]


@dataclass(frozen=True, slots=True)
class FetchResult:
    content: bytes
    final_url: str


class CorpusFetcher(Protocol):
    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int) -> FetchResult: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> None:
        return None


class UrlLibCorpusFetcher:
    """HTTPS-only fetcher with redirects disabled and a decoded-byte ceiling."""

    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int) -> FetchResult:
        _validate_source_url(url)
        request = Request(  # noqa: S310 - exact HTTPS host allowlist validated above
            url,
            headers={"User-Agent": "FDAI-public-corpus-evaluation/1"},
        )
        try:
            with build_opener(_NoRedirectHandler()).open(
                request,
                timeout=timeout_seconds,
            ) as response:
                content = response.read(max_bytes + 1)
                final_url = response.geturl()
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ValueError("public corpus source fetch failed") from exc
        if len(content) > max_bytes:
            raise ValueError("public corpus source exceeds the byte limit")
        if final_url != url:
            raise ValueError("public corpus final URL mismatch")
        return FetchResult(content=content, final_url=final_url)


def load_manifest(path: Path) -> PublicCorpusManifest:
    """Load and validate the content-free public corpus manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("public corpus manifest is unreadable") from exc
    root = _object(payload, "manifest")
    if set(root) != {"schema_version", "sources"}:
        raise ValueError("public corpus manifest keys are invalid")
    if _integer(root["schema_version"], "schema_version") != 1:
        raise ValueError("public corpus manifest schema_version MUST be 1")
    source_payloads = _array(root["sources"], "sources")
    if not source_payloads:
        raise ValueError("public corpus manifest sources MUST be non-empty")
    sources = tuple(_source(item) for item in source_payloads)
    _reject_duplicates(sources, "id", lambda item: item.source_id)
    _reject_duplicates(sources, "url", lambda item: item.url)
    return PublicCorpusManifest(schema_version=1, sources=sources)


def evaluate_manifest(
    manifest: PublicCorpusManifest,
    *,
    cache_dir: Path,
    fetcher: CorpusFetcher | None = None,
    distiller: Distiller | None = None,
    timeout_seconds: float = 30.0,
    max_bytes: int = 8 * 1024 * 1024,
) -> dict[str, Any]:
    """Evaluate the manifest and return deterministic metadata-only JSON data."""
    if not math.isfinite(timeout_seconds) or not 0.0 < timeout_seconds <= 300.0:
        raise ValueError("public corpus timeout MUST be finite and in (0, 300]")
    if type(max_bytes) is not int or max_bytes < 1 or max_bytes > 32 * 1024 * 1024:
        raise ValueError("public corpus byte limit MUST be in [1, 33554432]")
    return asyncio.run(
        _evaluate_manifest(
            manifest,
            cache_dir=cache_dir,
            fetcher=fetcher or UrlLibCorpusFetcher(),
            distiller=distiller,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
    )


async def _evaluate_manifest(
    manifest: PublicCorpusManifest,
    *,
    cache_dir: Path,
    fetcher: CorpusFetcher,
    distiller: Distiller | None,
    timeout_seconds: float,
    max_bytes: int,
) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    manuals = [
        await _evaluate_source(
            source,
            content=_load_source(
                source,
                cache_dir=cache_dir,
                fetcher=fetcher,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            ),
            distiller=distiller,
        )
        for source in manifest.sources
    ]
    summary = {
        "annotation_count": sum(item["annotation_count"] for item in manuals),
        "annotation_detected_count": sum(item["annotation_detected_count"] for item in manuals),
        "candidate_count": sum(item["provider"]["candidate_count"] for item in manuals),
        "extraction_success_count": sum(item["provider"]["extraction_success"] for item in manuals),
        "manual_count": len(manuals),
        "parser_rejection_count": sum(item["parser_rejected"] for item in manuals),
        "provider_abstention_count": sum(item["provider"]["abstained"] for item in manuals),
        "replay_mismatch_count": sum(not item["replay_match"] for item in manuals),
    }
    return {
        "manifest_schema_version": manifest.schema_version,
        "manuals": manuals,
        "summary": summary,
    }


async def _evaluate_source(
    source: PublicCorpusSource,
    *,
    content: bytes,
    distiller: Distiller | None,
) -> dict[str, Any]:
    text = _validated_source_text(source, content)
    _validate_annotation_hashes(source, text)
    provider = _provider_report(status="unbound" if distiller is None else "abstained")
    try:
        inspector = SignatureProtectionInspector()
        inspection = await inspector.inspect(
            source_name=source.source_id + _FORMAT_SUFFIX[source.source_format],
            media_type_hint="text/markdown" if source.source_format == "markdown" else "text/plain",
            chunks=_chunks(content),
        )
        version = _document_version(
            source,
            inspection.media_type,
            inspection.observed_format,
            inspection.state,
        )
        envelope = await StandardLibraryDocumentExtractor().extract(
            version=version,
            chunks=_chunks(content),
        )
        document = manual_document_from_envelope(envelope)
        claims = inventory_claims(document)
        replay_claims = inventory_claims(document)
        inventory_digest = _inventory_digest(claims)
        replay_digest = _inventory_digest(replay_claims)
    except ValueError as exc:
        return {
            "annotation_count": len(source.critical_claims),
            "annotation_detected_count": 0,
            "critical_detected_claim_count": 0,
            "detected_claim_count": 0,
            "format": source.source_format,
            "id": source.source_id,
            "inventory_digest": None,
            "language": source.language,
            "parser_error_code": type(exc).__name__,
            "parser_rejected": True,
            "provider": provider,
            "replay_match": False,
            "sha256": source.sha256,
            "source_bytes": source.source_bytes,
            "source_line_count": source.source_line_count,
            "unit_count": 0,
        }
    detected = _validate_annotation_signals(source, claims)
    if distiller is not None:
        result = await distiller.distill(document)
        provider = _provider_report(
            status="bound" if result.candidates else "abstained",
            candidate_count=len(result.candidates),
        )
    return {
        "annotation_count": len(source.critical_claims),
        "annotation_detected_count": detected,
        "critical_detected_claim_count": sum(claim.critical for claim in claims),
        "detected_claim_count": len(claims),
        "format": source.source_format,
        "id": source.source_id,
        "inventory_digest": inventory_digest,
        "language": source.language,
        "parser_error_code": None,
        "parser_rejected": False,
        "provider": provider,
        "replay_match": inventory_digest == replay_digest,
        "sha256": source.sha256,
        "source_bytes": source.source_bytes,
        "source_line_count": source.source_line_count,
        "unit_count": len(envelope.units),
    }


def _source(payload: object) -> PublicCorpusSource:
    item = _object(payload, "manifest source")
    if set(item) != _SOURCE_KEYS:
        raise ValueError("manifest source keys are invalid")
    source_id = _string(item["id"], "manifest source id")
    if _TOKEN.fullmatch(source_id) is None:
        raise ValueError("manifest source id MUST be a bounded lowercase token")
    url = _string(item["url"], "manifest source url")
    _validate_source_url(url)
    digest = _string(item["sha256"], "manifest source sha256")
    if _SHA256.fullmatch(digest) is None:
        raise ValueError("manifest source sha256 MUST be lowercase SHA-256")
    license_id = _string(item["license_id"], "manifest source license_id")
    license_source = _string(item["license_source"], "manifest source license_source")
    _validate_https_url(license_source, "manifest source license_source")
    source_format = _string(item["format"], "manifest source format")
    if source_format not in _FORMAT_SUFFIX:
        raise ValueError("manifest source format is unsupported")
    language = _string(item["language"], "manifest source language")
    if _TOKEN.fullmatch(language) is None:
        raise ValueError("manifest source language MUST be a bounded lowercase token")
    line_count = _positive_integer(item["source_line_count"], "manifest source line count")
    source_bytes = _positive_integer(item["source_bytes"], "manifest source bytes")
    annotations = tuple(
        _annotation(value, line_count)
        for value in _array(item["critical_claims"], "critical_claims")
    )
    if len(annotations) < 2:
        raise ValueError("manifest source MUST contain at least two critical claims")
    locators = [annotation.locator for annotation in annotations]
    if len(locators) != len(set(locators)):
        raise ValueError("manifest source critical claim locators MUST be unique")
    return PublicCorpusSource(
        source_id,
        url,
        digest,
        license_id,
        license_source,
        source_format,
        language,
        line_count,
        source_bytes,
        annotations,
    )


def _annotation(payload: object, line_count: int) -> CriticalClaimAnnotation:
    item = _object(payload, "critical claim")
    if set(item) != _ANNOTATION_KEYS:
        raise ValueError("critical claim keys are invalid")
    annotation = CriticalClaimAnnotation(
        locator=_string(item["locator"], "critical claim locator"),
        text_sha256=_string(item["text_sha256"], "critical claim text_sha256"),
        expected_claim_signals=tuple(
            _string(signal, "critical claim signal")
            for signal in _array(item["expected_claim_signals"], "expected_claim_signals")
        ),
    )
    if annotation.line_number > line_count:
        raise ValueError("critical claim locator exceeds the source line count")
    if _SHA256.fullmatch(annotation.text_sha256) is None:
        raise ValueError("critical claim text_sha256 MUST be lowercase SHA-256")
    allowed_signals = {kind.value for kind in ClaimKind}
    if (
        not annotation.expected_claim_signals
        or not set(annotation.expected_claim_signals) <= allowed_signals
    ):
        raise ValueError("critical claim expected signals are invalid")
    return annotation


def _load_source(
    source: PublicCorpusSource,
    *,
    cache_dir: Path,
    fetcher: CorpusFetcher,
    timeout_seconds: float,
    max_bytes: int,
) -> bytes:
    if source.source_bytes > max_bytes:
        raise ValueError(f"{source.source_id} source exceeds the configured byte limit")
    path = cache_dir / (source.source_id + _FORMAT_SUFFIX[source.source_format])
    if path.is_file():
        if path.is_symlink():
            raise ValueError(f"{source.source_id} cached source MUST NOT be a symbolic link")
        cached_size = path.stat().st_size
        if cached_size != source.source_bytes or cached_size > max_bytes:
            raise ValueError(f"{source.source_id} cached source byte count mismatch")
        return path.read_bytes()
    fetched = fetcher.fetch(source.url, timeout_seconds=timeout_seconds, max_bytes=max_bytes)
    if fetched.final_url != source.url:
        raise ValueError(f"{source.source_id} final URL mismatch")
    _validate_source_identity(source, fetched.content)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(fetched.content)
    temporary.replace(path)
    return fetched.content


def _validated_source_text(source: PublicCorpusSource, content: bytes) -> str:
    _validate_source_identity(source, content)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{source.source_id} source is not valid UTF-8") from exc
    if len(text.splitlines()) != source.source_line_count:
        raise ValueError(f"{source.source_id} source line count mismatch")
    return text


def _validate_source_identity(source: PublicCorpusSource, content: bytes) -> None:
    if len(content) != source.source_bytes:
        raise ValueError(f"{source.source_id} source byte count mismatch")
    if hashlib.sha256(content).hexdigest() != source.sha256:
        raise ValueError(f"{source.source_id} source SHA-256 mismatch")


def _validate_annotation_hashes(source: PublicCorpusSource, text: str) -> None:
    lines = text.splitlines()
    for annotation in source.critical_claims:
        digest = hashlib.sha256(lines[annotation.line_number - 1].strip().encode()).hexdigest()
        if digest != annotation.text_sha256:
            raise ValueError(f"{source.source_id} critical claim hash mismatch")


def _validate_annotation_signals(source: PublicCorpusSource, claims: Sequence[Any]) -> int:
    detected = 0
    for annotation in source.critical_claims:
        signals = {
            signal.value
            for claim in claims
            if _locator_covers(claim.evidence.structural_locator, annotation.line_number)
            for signal in claim.signals
        }
        if set(annotation.expected_claim_signals) <= signals:
            detected += 1
    return detected


def _locator_covers(locator: str, line_number: int) -> bool:
    if locator == f"line:{line_number}":
        return True
    match = _RANGE_LOCATOR.search(locator)
    return bool(match and int(match.group(1)) <= line_number <= int(match.group(2)))


def _document_version(
    source: PublicCorpusSource,
    media_type: str,
    observed_format: str,
    protection_state: ProtectionState,
) -> DocumentVersion:
    return DocumentVersion(
        document_id=uuid5(NAMESPACE_URL, source.url),
        version_id=uuid5(NAMESPACE_URL, source.url + "#" + source.sha256),
        upload_id=uuid5(NAMESPACE_URL, source.source_id),
        source_name=source.source_id + _FORMAT_SUFFIX[source.source_format],
        source_sha256=source.sha256,
        size_bytes=source.source_bytes,
        media_type=media_type,
        observed_format=observed_format,
        state=DocumentState.EXTRACTING,
        protection_state=protection_state,
        access=AccessDescriptor(reference="access:public-corpus", collection_id="public-corpus"),
        retention=RetentionPolicy(policy_version="evaluation-v1"),
        purposes=(DocumentPurpose.MANUAL_DISTILLATION,),
        uploader_id="public-corpus-evaluation",
        created_at=_EVALUATION_TIME,
        updated_at=_EVALUATION_TIME,
    )


async def _chunks(content: bytes) -> AsyncIterator[bytes]:
    for offset in range(0, len(content), 64 * 1024):
        yield content[offset : offset + 64 * 1024]


def _inventory_digest(claims: Sequence[Any]) -> str:
    return stable_digest(
        tuple(
            (
                claim.kind.value,
                tuple(signal.value for signal in claim.signals),
                claim.critical,
                claim.evidence.text_sha256,
                claim.evidence.structural_locator,
            )
            for claim in claims
        )
    )


def _provider_report(*, status: str, candidate_count: int = 0) -> dict[str, Any]:
    return {
        "abstained": candidate_count == 0,
        "candidate_count": candidate_count,
        "extraction_success": candidate_count > 0,
        "status": status,
    }


def _validate_source_url(url: str) -> None:
    parsed = _validate_https_url(url, "public corpus source URL")
    if parsed.hostname not in _ALLOWED_SOURCE_HOSTS:
        raise ValueError("public corpus source host is not allowlisted")
    if parsed.query or parsed.fragment:
        raise ValueError("public corpus source URL MUST NOT contain a query or fragment")


def _validate_https_url(url: str, label: str) -> Any:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{label} MUST be an HTTPS URL without credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} has an invalid port") from exc
    if port not in (None, 443):
        raise ValueError(f"{label} MUST use the default HTTPS port")
    return parsed


def _reject_duplicates(
    sources: Sequence[PublicCorpusSource],
    label: str,
    selector: Any,
) -> None:
    values = [selector(source) for source in sources]
    if len(values) != len(set(values)):
        raise ValueError(f"public corpus manifest contains a duplicate source {label}")


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} MUST be an object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} MUST be an array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} MUST be a non-empty string")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} MUST be an integer")
    return value


def _positive_integer(value: object, label: str) -> int:
    result = _integer(value, label)
    if result < 1:
        raise ValueError(f"{label} MUST be positive")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-bytes", type=int, default=8 * 1024 * 1024)
    args = parser.parse_args(argv)
    try:
        report = evaluate_manifest(
            load_manifest(args.manifest),
            cache_dir=args.cache_dir,
            timeout_seconds=args.timeout_seconds,
            max_bytes=args.max_bytes,
        )
    except ValueError as exc:
        print(f"document-ontology-public-corpus: FAIL: {exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(serialized)
    else:
        args.output.write_text(serialized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
