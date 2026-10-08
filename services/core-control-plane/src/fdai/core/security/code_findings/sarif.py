"""Bounded, fail-closed SARIF 2.1.0 ingestion for code-security findings.

Every SARIF document is untrusted, whichever producer created it (FDAI's deterministic lane,
Microsoft MDASH, GitHub code scanning, Opengrep, Trivy, or another tool). Ingestion therefore:

- enforces byte, nesting-depth, run, result, location, and code-flow limits before and after
  parsing;
- never dereferences artifact URIs, ``externalPropertyFileReferences``, ``helpUri``, or links;
- accepts only repository-relative paths (an absolute ``file:`` path is relativized only against
  an explicitly configured source root) and rejects traversal;
- strips control and bidirectional-override characters and truncates every text field;
- records every dropped result with a reason instead of discarding it silently.

The caller names the lane and the exact revision; neither is read from the document.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

from fdai.core.security.code_findings.models import FlowStep, Lane, Occurrence, SourceLocation
from fdai.core.security.code_findings.sarif_runs import RunMetadata, run_metadata

_REVISION = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_CWE = re.compile(r"(?i)\bcwe[-_/ ]?0*(\d{1,5})\b")
_ADVISORY = re.compile(
    r"\b(CVE-\d{4}-\d{4,7}|GHSA(?:-[23456789cfghjmpqrvwx]{4}){3}"
    r"|(?:PYSEC|GO|RUSTSEC|OSV|GSD)-\d{4}-\d{1,7})\b"
)
_DRIVE = re.compile(r"^[A-Za-z]:")
_UNSAFE_CHARS = re.compile(
    "[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]"
)
_PACKAGE_KEYS = ("purl", "packageName", "package", "PkgName", "pkgName")
_VERSION_KEYS = ("installedVersion", "InstalledVersion", "packageVersion", "version")


class SarifIngestError(ValueError):
    """Raised when a SARIF document violates a limit or the 2.1.0 shape."""


@dataclass(frozen=True, slots=True)
class SarifLimits:
    max_bytes: int = 20_000_000
    max_depth: int = 64
    max_runs: int = 20
    max_results: int = 20_000
    max_locations_per_result: int = 20
    max_code_flows_per_result: int = 5
    max_flow_steps: int = 64
    max_text: int = 1_024
    max_identifier: int = 256


@dataclass(frozen=True, slots=True)
class SarifIngestContext:
    """Caller-asserted ingestion context. Nothing here is read from the document."""

    lane: Lane
    revision: str
    source_roots: tuple[str, ...] = ()
    limits: SarifLimits = field(default_factory=SarifLimits)
    producer: str | None = None
    """Catalog producer name when FDAI ran the scanner itself. It replaces the tool's
    self-reported driver name, which varies by edition (``Opengrep OSS``) and is shared across
    modes (two Trivy scanners), so coverage receipts bind to the scanner that actually ran."""

    def __post_init__(self) -> None:
        if _REVISION.fullmatch(self.revision) is None:
            raise ValueError("revision must be a full lowercase git commit id")


@dataclass(frozen=True, slots=True)
class DroppedResult:
    run_index: int
    result_index: int
    reason: str


@dataclass(frozen=True, slots=True)
class SarifIngestResult:
    scan_digest: str
    producers: tuple[str, ...]
    occurrences: tuple[Occurrence, ...]
    dropped: tuple[DroppedResult, ...]
    runs: tuple[RunMetadata, ...] = ()


def clean_text(value: object, limit: int) -> str:
    """Return ``value`` as NFC text without control or bidi characters, truncated to ``limit``."""
    if not isinstance(value, str):
        return ""
    text = _UNSAFE_CHARS.sub("", unicodedata.normalize("NFC", value)).replace("\n", " ")
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _check_depth(raw: bytes, max_depth: int) -> None:
    depth = 0
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
        elif byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):
            depth += 1
            if depth > max_depth:
                raise SarifIngestError(f"SARIF nesting exceeds {max_depth} levels")
        elif byte in (0x5D, 0x7D):
            depth -= 1


def normalize_path(uri: object, source_roots: Sequence[str] = ()) -> str | None:
    """Return a safe repository-relative POSIX path for ``uri`` or ``None``."""
    if not isinstance(uri, str) or not uri or len(uri) > 2_048:
        return None
    parts = urlsplit(uri)
    if parts.scheme and len(parts.scheme) > 1:
        if parts.scheme.lower() != "file" or parts.netloc not in ("", "localhost"):
            return None
    raw_path = parts.path if parts.scheme and len(parts.scheme) > 1 else uri.split("?")[0]
    path = unquote(raw_path).replace("\\", "/")
    # Glob characters are rejected because fix-group allowed paths are matched as globs.
    if "\x00" in path or _UNSAFE_CHARS.search(path) or any(c in path for c in "*?[]"):
        return None
    if path.startswith("/") or _DRIVE.match(path):
        relative = _relativize(path, source_roots)
        if relative is None:
            return None
        path = relative
    normalized = posixpath.normpath(path)
    if normalized in (".", "..") or normalized.startswith("../") or normalized.startswith("/"):
        return None
    return normalized


def _strip_drive_slash(path: str) -> str:
    return path[1:] if path.startswith("/") and _DRIVE.match(path[1:]) else path


def _relativize(path: str, source_roots: Sequence[str]) -> str | None:
    candidate = _strip_drive_slash(posixpath.normpath(path))
    for root in source_roots:
        base = _strip_drive_slash(posixpath.normpath(root.replace("\\", "/"))).rstrip("/")
        if base and candidate.startswith(base + "/"):
            return candidate[len(base) + 1 :]
    return None


def _as_list(value: object, limit: int) -> list[object]:
    return list(value[:limit]) if isinstance(value, list) else []


def _as_map(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _line(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _physical(
    location: object, ctx: SarifIngestContext
) -> tuple[str | None, int | None, int | None]:
    physical = _as_map(_as_map(location).get("physicalLocation"))
    artifact = _as_map(physical.get("artifactLocation"))
    region = _as_map(physical.get("region"))
    path = normalize_path(artifact.get("uri"), ctx.source_roots)
    start = _line(region.get("startLine"))
    end = _line(region.get("endLine")) or start
    return path, start, end


def _tags(*sources: Mapping[str, object]) -> tuple[str, ...]:
    tags: list[str] = []
    for source in sources:
        for tag in _as_list(_as_map(source.get("properties")).get("tags"), 64):
            text = clean_text(tag, 128)
            if text and text not in tags:
                tags.append(text)
    return tuple(tags)


def _cwes(tags: Sequence[str], result: Mapping[str, object]) -> tuple[int, ...]:
    found: list[int] = []
    texts = list(tags)
    for taxon in _as_list(result.get("taxa"), 16):
        texts.append(clean_text(_as_map(taxon).get("id"), 32))
    for text in texts:
        for match in _CWE.finditer(text):
            value = int(match.group(1))
            if value not in found:
                found.append(value)
    if not found:
        for taxon in _as_list(result.get("taxa"), 16):
            taxon_map = _as_map(taxon)
            component = _as_map(taxon_map.get("toolComponent"))
            identifier = clean_text(taxon_map.get("id"), 16)
            if clean_text(component.get("name"), 16).upper() == "CWE" and identifier.isdigit():
                found.append(int(identifier))
    return tuple(sorted(found))


def _advisories(*texts: str) -> tuple[str, ...]:
    found: list[str] = []
    for text in texts:
        for match in _ADVISORY.finditer(text):
            if match.group(1) not in found:
                found.append(match.group(1))
    return tuple(found)


def _score(value: object) -> float | None:
    try:
        score = float(value) if isinstance(value, (str, int, float)) else None
    except ValueError:
        return None
    return score if score is not None and 0.0 < score <= 10.0 else None


def _first_text(props: Mapping[str, object], keys: Sequence[str], limit: int) -> str | None:
    for key in keys:
        text = clean_text(props.get(key), limit)
        if text:
            return text
    return None


def ingest_sarif(raw: bytes, ctx: SarifIngestContext) -> SarifIngestResult:
    """Parse one SARIF 2.1.0 document into occurrences, or raise :class:`SarifIngestError`."""
    limits = ctx.limits
    if len(raw) > limits.max_bytes:
        raise SarifIngestError(f"SARIF exceeds {limits.max_bytes} bytes")
    _check_depth(raw, limits.max_depth)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise SarifIngestError(f"SARIF is not valid UTF-8 JSON: {type(exc).__name__}") from exc
    if not isinstance(document, dict) or document.get("version") != "2.1.0":
        raise SarifIngestError("SARIF document must be an object with version 2.1.0")
    runs = document.get("runs")
    if not isinstance(runs, list) or len(runs) > limits.max_runs:
        raise SarifIngestError(f"SARIF runs must be a list of at most {limits.max_runs}")
    scan_digest = hashlib.sha256(raw).hexdigest()
    occurrences: list[Occurrence] = []
    dropped: list[DroppedResult] = []
    producers: list[str] = []
    run_facts: list[RunMetadata] = []
    total = 0
    for run_index, run in enumerate(runs):
        run_map = _as_map(run)
        driver = _as_map(_as_map(run_map.get("tool")).get("driver"))
        producer = ctx.producer or clean_text(driver.get("name"), 128) or "unknown"
        version = clean_text(driver.get("semanticVersion") or driver.get("version"), 64)
        if producer not in producers:
            producers.append(producer)
        rules = {
            clean_text(_as_map(rule).get("id"), limits.max_identifier): _as_map(rule)
            for rule in _as_list(driver.get("rules"), limits.max_results)
        }
        run_facts.append(
            run_metadata(
                run_map,
                producer,
                version,
                [rule_id for rule_id in rules if rule_id],
                lambda uri: normalize_path(uri, ctx.source_roots),
            )
        )
        results = run_map.get("results")
        if not isinstance(results, list):
            continue
        total += len(results)
        if total > limits.max_results:
            raise SarifIngestError(f"SARIF exceeds {limits.max_results} results")
        for result_index, result in enumerate(results):
            occurrence = _occurrence(
                _as_map(result), rules, producer, version, scan_digest, run_index, result_index, ctx
            )
            if isinstance(occurrence, str):
                dropped.append(DroppedResult(run_index, result_index, occurrence))
            else:
                occurrences.append(occurrence)
    return SarifIngestResult(
        scan_digest, tuple(producers), tuple(occurrences), tuple(dropped), tuple(run_facts)
    )


def _occurrence(
    result: Mapping[str, object],
    rules: Mapping[str, Mapping[str, object]],
    producer: str,
    version: str,
    scan_digest: str,
    run_index: int,
    result_index: int,
    ctx: SarifIngestContext,
) -> Occurrence | str:
    limits = ctx.limits
    if result.get("kind") not in (None, "fail"):
        return "not_a_failure"
    if _as_list(result.get("suppressions"), 1):
        return "suppressed_by_producer"
    rule_id = clean_text(
        result.get("ruleId") or _as_map(result.get("rule")).get("id"), limits.max_identifier
    )
    if not rule_id:
        return "missing_rule_id"
    rule = rules.get(rule_id, {})
    locations = _as_list(result.get("locations"), limits.max_locations_per_result)
    if not locations:
        return "missing_location"
    path, start, end = _physical(locations[0], ctx)
    if path is None:
        return "unresolvable_location"
    logical_locations = _as_list(_as_map(locations[0]).get("logicalLocations"), 1)
    logical = _as_map(logical_locations[0]) if logical_locations else {}
    symbol = (
        clean_text(logical.get("fullyQualifiedName") or logical.get("name"), limits.max_identifier)
        or None
    )
    tags = _tags(rule, result)
    props = _as_map(result.get("properties"))
    rule_props = _as_map(rule.get("properties"))
    level = clean_text(
        result.get("level") or _as_map(rule.get("defaultConfiguration")).get("level"), 16
    )
    advisories = _advisories(rule_id, *tags)
    return Occurrence(
        occurrence_id=hashlib.sha256(
            f"{scan_digest}:{run_index}:{result_index}".encode()
        ).hexdigest()[:24],
        producer=producer,
        producer_version=version,
        lane=ctx.lane,
        scan_digest=scan_digest,
        revision=ctx.revision,
        rule_id=rule_id,
        location=SourceLocation(path=path, start_line=start, end_line=end, symbol=symbol),
        cwe_ids=_cwes(tags, result),
        tags=tags,
        source_severity=level,
        message=clean_text(_as_map(result.get("message")).get("text"), limits.max_text),
        code_flow=_flow(result, ctx),
        advisory_ids=advisories,
        package=_first_text(props, _PACKAGE_KEYS, limits.max_identifier) if advisories else None,
        package_version=_first_text(props, _VERSION_KEYS, 64) if advisories else None,
        advisory_score=_score(props.get("security-severity") or rule_props.get("security-severity"))
        if advisories
        else None,
        fingerprints=tuple(
            (clean_text(key, 64), clean_text(value, 128))
            for key, value in list(_as_map(result.get("partialFingerprints")).items())[:8]
        ),
    )


def _flow(result: Mapping[str, object], ctx: SarifIngestContext) -> tuple[FlowStep, ...]:
    limits = ctx.limits
    for flow in _as_list(result.get("codeFlows"), limits.max_code_flows_per_result):
        for thread in _as_list(_as_map(flow).get("threadFlows"), 4):
            steps: list[FlowStep] = []
            for step in _as_list(_as_map(thread).get("locations"), limits.max_flow_steps):
                path, start, _ = _physical(_as_map(step).get("location"), ctx)
                if path is not None:
                    steps.append(FlowStep(path=path, line=start))
            if steps:
                return tuple(steps)
    return ()


__all__ = [
    "DroppedResult",
    "SarifIngestContext",
    "SarifIngestError",
    "SarifIngestResult",
    "SarifLimits",
    "clean_text",
    "ingest_sarif",
    "normalize_path",
]
