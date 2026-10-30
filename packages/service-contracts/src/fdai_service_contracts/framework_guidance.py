"""Source-bound, inert WAF, MCSB v1 and CAF presentation content.

The source revision is the assessment catalog's ``source_revision_digest``;
the source digest is the exact control's ``specification_digest``. Neither
reading a guide nor its illustrative configuration supplies assessment evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from functools import lru_cache
from importlib import resources
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .catalog_canonical import canonical_digest
from .wara_guidance import (
    Digest,
    GuidanceConfiguration,
    GuidanceDiagram,
    GuidanceSource,
    GuidanceText,
)

FrameworkId = Literal["azure-waf", "azure-mcsb", "azure-caf"]
EXPECTED_COUNTS: dict[FrameworkId, int] = {"azure-waf": 59, "azure-mcsb": 86, "azure-caf": 15}
MAXIMUM_CATALOG_BYTES = 8_388_608
MAXIMUM_SHARD_BYTES = 524_288


class FrameworkGuidanceUnavailable(ValueError):
    """The installed corpus or requested authoritative identity is unavailable."""


class FrameworkGuidanceMismatch(ValueError):
    """The requested source pins do not match the installed guidance."""


def _digest(material: dict[str, object], key: str) -> str:
    return "sha256:" + canonical_digest(
        {name: value for name, value in material.items() if name != key}
    )


def _check_bilingual(value: object) -> None:
    if isinstance(value, dict):
        if "en" in value:
            english, korean = value.get("en"), value.get("ko")
            if (
                not isinstance(english, str)
                or not isinstance(korean, str)
                or not re.search("[가-힣]", korean)
                or unicodedata.normalize("NFC", korean) != korean
            ):
                raise ValueError("Framework guidance requires readable English and Korean text")
            if any("<" in text or ">" in text for text in (english, korean)):
                raise ValueError("Framework guidance text must not contain markup")
        for item in value.values():
            _check_bilingual(item)
    elif isinstance(value, list):
        for item in value:
            _check_bilingual(item)


class FrameworkGuidance(BaseModel):
    """Shared presentation shape; framework and control identity are not APRL GUIDs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    framework_id: FrameworkId
    control_id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:.-]+$")]
    source_revision: Digest
    source_digest: Digest
    title: GuidanceText
    summary: GuidanceText
    benefits: GuidanceText
    rationale: GuidanceText
    applicability: tuple[GuidanceText, ...] = Field(min_length=2, max_length=12)
    configuration: GuidanceConfiguration
    implementation_steps: tuple[GuidanceText, ...] = Field(min_length=3, max_length=12)
    verification_steps: tuple[GuidanceText, ...] = Field(min_length=3, max_length=12)
    cautions: tuple[GuidanceText, ...] = Field(min_length=2, max_length=12)
    diagram: GuidanceDiagram
    sources: tuple[GuidanceSource, ...] = Field(min_length=1, max_length=8)
    content_digest: Digest

    @model_validator(mode="after")
    def validate_content(self) -> FrameworkGuidance:
        material = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        if self.content_digest != _digest(material, "content_digest"):
            raise ValueError("Framework guidance content digest does not match its material")
        _check_bilingual(material)
        if any(source.kind != "learn" for source in self.sources):
            raise ValueError("Framework guidance must cite reviewed Microsoft Learn sources")
        if self.framework_id == "azure-waf":
            valid = re.fullmatch(r"(?:CO|OE|PE|RE|SE):[0-9]{2}", self.control_id)
        elif self.framework_id == "azure-mcsb":
            valid = re.fullmatch(
                r"(?:AM|BR|DP|DS|ES|GS|IM|IR|LT|NS|PA|PV)-[1-9][0-9]?", self.control_id
            )
        else:
            valid = re.fullmatch(
                r"(?:strategy|plan|ready|adopt|govern|secure|manage|landing-zone\."
                r"(?:billing-tenant|identity-access|resource-organization|network-connectivity|"
                r"security|management|governance|platform-automation-devops))",
                self.control_id,
            )
        if not valid:
            raise ValueError("Framework guidance control identity is outside its framework")
        known = {node.id for node in self.diagram.nodes}
        roots = {node.id for node in self.diagram.nodes if node.role == "subject"}
        reached = set(roots)
        for _ in known:
            reached.update(edge.to for edge in self.diagram.edges if edge.from_ in reached)
        if not roots or reached != known:
            raise ValueError("Framework guidance diagram must be directed from its subject")
        roles = {node.role for node in self.diagram.nodes}
        if not {"subject", "configuration", "evidence", "outcome"}.issubset(roles):
            raise ValueError(
                "Framework guidance diagram must distinguish design, evidence and outcome"
            )
        return self


class FrameworkGuidancePin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    framework_id: FrameworkId
    source_revision: Digest
    assessment_catalog_digest: Digest
    framework_definition_digest: Digest
    expected_control_count: int


class FrameworkGuidanceCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    pins: tuple[FrameworkGuidancePin, ...] = Field(min_length=3, max_length=3)
    entries: tuple[FrameworkGuidance, ...] = Field(min_length=160, max_length=160)
    catalog_digest: Digest

    @model_validator(mode="after")
    def validate_accounting(self) -> FrameworkGuidanceCatalog:
        pins = {pin.framework_id: pin for pin in self.pins}
        if set(pins) != set(EXPECTED_COUNTS):
            raise ValueError("Framework guidance source pin accounting is incomplete")
        identities = {(entry.framework_id, entry.control_id) for entry in self.entries}
        if len(identities) != len(self.entries):
            raise ValueError("Framework guidance control identities are duplicated")
        for framework_id, count in EXPECTED_COUNTS.items():
            selected = [entry for entry in self.entries if entry.framework_id == framework_id]
            if len(selected) != count or pins[framework_id].expected_control_count != count:
                raise ValueError("Framework guidance exact control accounting is incomplete")
            if any(
                entry.source_revision != pins[framework_id].source_revision for entry in selected
            ):
                raise ValueError("Framework guidance entry revision does not match its source pin")
        material = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        if self.catalog_digest != _digest(material, "catalog_digest"):
            raise ValueError("Framework guidance catalog digest does not match its material")
        return self

    def resolve(self, framework_id: str, control_id: str) -> FrameworkGuidance | None:
        return next(
            (
                entry
                for entry in self.entries
                if entry.framework_id == framework_id and entry.control_id == control_id
            ),
            None,
        )


def load_framework_guidance(body: bytes) -> FrameworkGuidanceCatalog:
    """Validate bounded public JSON, including every guide and the catalog digest."""
    if len(body) > MAXIMUM_CATALOG_BYTES:
        raise ValueError("Framework guidance catalog exceeds its byte limit")
    return FrameworkGuidanceCatalog.model_validate_json(body)


class _Shard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file: Annotated[str, Field(pattern=r"^framework-guidance-[0-9]{2}\.json$")]
    digest: Digest
    entry_count: int = Field(ge=1, le=16)


class _OfficialSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    framework_id: FrameworkId
    source_url: str = Field(pattern=r"^https://learn\.microsoft\.com/")
    resolved_ref: str = Field(pattern=r"^[a-f0-9]{40}$")
    content_hash: str = Field(pattern=r"^(?:git:[a-f0-9]{40}|sha256:[a-f0-9]{64})$")
    license: Literal["CC-BY-4.0"]


class _Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    pins: tuple[FrameworkGuidancePin, ...] = Field(min_length=3, max_length=3)
    catalog_digest: Digest
    authoring_digest: Digest
    source_files: dict[str, Digest] = Field(min_length=6, max_length=128)
    official_sources: tuple[_OfficialSource, ...] = Field(min_length=21, max_length=21)
    shards: tuple[_Shard, ...] = Field(min_length=10, max_length=10)
    manifest_digest: Digest

    @model_validator(mode="after")
    def validate_digest(self) -> _Manifest:
        material = self.model_dump(mode="json")
        if self.manifest_digest != _digest(material, "manifest_digest"):
            raise ValueError("Framework guidance manifest digest does not match its material")
        return self


@lru_cache(maxsize=1)
def packaged_framework_guidance() -> FrameworkGuidanceCatalog:
    """Load only installed immutable public files; no URL, model or external path."""
    directory = resources.files("fdai_service_contracts").joinpath("data")
    try:
        manifest_body = directory.joinpath("framework-guidance.json").read_bytes()
        if len(manifest_body) > MAXIMUM_SHARD_BYTES:
            raise ValueError("Framework guidance manifest exceeds its byte limit")
        manifest = _Manifest.model_validate_json(manifest_body)
        entries: list[object] = []
        seen: set[str] = set()
        for shard in manifest.shards:
            if shard.file in seen:
                raise ValueError("Framework guidance shard is duplicated")
            seen.add(shard.file)
            body = directory.joinpath(shard.file).read_bytes()
            if len(body) > MAXIMUM_SHARD_BYTES:
                raise ValueError("Framework guidance shard exceeds its byte limit")
            if "sha256:" + hashlib.sha256(body).hexdigest() != shard.digest:
                raise ValueError("Framework guidance shard digest does not match its bytes")
            material = json.loads(body)
            if set(material) != {"entries"} or len(material["entries"]) != shard.entry_count:
                raise ValueError("Framework guidance shard accounting is incomplete")
            entries.extend(material["entries"])
        return load_framework_guidance(
            json.dumps(
                {
                    "schema_version": manifest.schema_version,
                    "pins": [pin.model_dump(mode="json") for pin in manifest.pins],
                    "entries": entries,
                    "catalog_digest": manifest.catalog_digest,
                },
                ensure_ascii=False,
            ).encode("utf-8")
        )
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise FrameworkGuidanceUnavailable(
            "Installed framework guidance is missing or invalid; regenerate the packaged corpus"
        ) from error


def assert_framework_guidance_catalog(
    catalog: FrameworkGuidanceCatalog, framework_id: str, assessment_body: bytes
) -> None:
    """Bind all guides to an authoritative assessment catalog before serving details.

    The caller supplies its already-admitted catalog bytes, never a request-selected
    file or URL. A changed definition, source revision, control set or specification
    fails closed even when the presentation content remains internally well formed.
    """
    if len(assessment_body) > MAXIMUM_CATALOG_BYTES:
        raise FrameworkGuidanceMismatch("Framework assessment catalog exceeds its byte limit")
    try:
        source = json.loads(assessment_body)
        pin = next(pin for pin in catalog.pins if pin.framework_id == framework_id)
        controls = source["controls"]
        actual = {control["control_id"]: control["specification_digest"] for control in controls}
        expected = {
            entry.control_id: entry.source_digest
            for entry in catalog.entries
            if entry.framework_id == framework_id
        }
        valid = (
            source["framework_id"] == framework_id
            and source["source_revision_digest"] == pin.source_revision
            and source["framework_definition_digest"] == pin.framework_definition_digest
            and source["catalog_digest"] == pin.assessment_catalog_digest
            and source["catalog_digest"] == _digest(source, "catalog_digest")
            and source["expected_control_count"] == pin.expected_control_count
            and len(controls) == len(actual)
            and actual == expected
        )
    except (ValueError, KeyError, TypeError, StopIteration) as error:
        raise FrameworkGuidanceMismatch(
            "Framework guidance authoritative catalog is invalid"
        ) from error
    if not valid:
        raise FrameworkGuidanceMismatch(
            "Framework guidance does not match the authoritative catalog"
        )


def resolve_framework_guidance(
    *,
    framework_id: str,
    control_id: str,
    source_revision: str,
    source_digest: str,
    catalog: FrameworkGuidanceCatalog | None = None,
) -> FrameworkGuidance:
    """Resolve one exact source-bound control or raise an explicit unavailable/mismatch error."""
    selected = packaged_framework_guidance() if catalog is None else catalog
    entry = selected.resolve(framework_id, control_id)
    if entry is None:
        raise FrameworkGuidanceUnavailable("Framework guidance is unavailable for this control")
    if entry.source_revision != source_revision or entry.source_digest != source_digest:
        raise FrameworkGuidanceMismatch(
            "Framework guidance does not match this control's source pins"
        )
    return entry


def framework_guidance_detail(
    detail: Mapping[str, object], *, framework_id: str
) -> dict[str, object]:
    """Attach presentation without changing any evaluation or authority field.

    The producer must supply ``guidance_source_revision`` from its admitted
    assessment catalog's ``source_revision_digest`` and ``guidance_source_digest``
    from the selected control's ``specification_digest``. Legacy Git revision,
    title, URL and version fields are never inferred to supply these pins.
    Missing pins or unavailable content yield an explicit null guide. Present
    mismatched pins raise a bounded ``FrameworkGuidanceMismatch`` (ValueError).
    """
    result = dict(detail)
    result["guidance"] = None

    def absent(reason: str) -> dict[str, object]:
        result["guidance_unavailable_reason"] = reason
        return result

    if framework_id not in EXPECTED_COUNTS:
        return absent("unsupported_framework")
    if detail.get("framework_id", framework_id) != framework_id:
        raise FrameworkGuidanceMismatch(
            "Framework guidance detail framework identity does not match"
        )
    if framework_id == "azure-mcsb" and detail.get("benchmark_version") != "v1":
        return absent("unsupported_benchmark_version")
    control_id = detail.get("control_id", detail.get("id"))
    if not isinstance(control_id, str) or not control_id:
        return absent("missing_control_identity")
    revision = detail.get("guidance_source_revision")
    digest = detail.get("guidance_source_digest")
    if revision is None or digest is None:
        return absent("missing_source_pins")
    if not isinstance(revision, str) or not isinstance(digest, str):
        raise FrameworkGuidanceMismatch("Framework guidance detail source pins are invalid")
    try:
        guidance = resolve_framework_guidance(
            framework_id=framework_id,
            control_id=control_id,
            source_revision=revision,
            source_digest=digest,
        )
    except FrameworkGuidanceUnavailable:
        return absent("guidance_unavailable")
    result.pop("guidance_unavailable_reason", None)
    result["guidance"] = guidance.model_dump(mode="json", by_alias=True, exclude_none=True)
    return result


__all__ = [
    "EXPECTED_COUNTS",
    "FrameworkGuidance",
    "FrameworkGuidanceCatalog",
    "FrameworkGuidanceMismatch",
    "FrameworkGuidanceUnavailable",
    "assert_framework_guidance_catalog",
    "framework_guidance_detail",
    "load_framework_guidance",
    "packaged_framework_guidance",
    "resolve_framework_guidance",
]
