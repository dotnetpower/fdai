"""Inert illustrated WARA guidance shared by independent read-only consumers."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from functools import lru_cache
from importlib import resources
from typing import Annotated, Literal, cast
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .catalog_canonical import canonical_digest

_DIGEST = r"^sha256:[a-f0-9]{64}$"
_REVISION = r"^[a-f0-9]{40}$"
_GUID = r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$"
_IDENTIFIER = r"^[a-z][a-z0-9._-]{0,127}$"
_MAXIMUM_BYTES = 8_388_608
_MAXIMUM_SHARD_BYTES = 524_288

Digest = Annotated[str, Field(pattern=_DIGEST)]
Identifier = Annotated[str, Field(pattern=_IDENTIFIER)]


class GuidanceText(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    en: str = Field(min_length=1, max_length=4_000)
    ko: str | None = Field(default=None, min_length=1, max_length=4_000)


class ReferenceImage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    asset_id: Annotated[str, Field(pattern=r"^sha256-[a-f0-9]{64}$")]
    digest: Digest
    source_document_url: str = Field(min_length=1, max_length=2_048)
    image_url: str = Field(min_length=1, max_length=2_048)
    source_revision: Annotated[str, Field(pattern=_REVISION)]
    attribution: str = Field(min_length=1, max_length=512)
    license: Literal["CC-BY-4.0"]
    license_url: Literal["https://creativecommons.org/licenses/by/4.0/"]
    alt: GuidanceText
    caption: GuidanceText
    english_in_image_notice: GuidanceText

    @model_validator(mode="after")
    def validate_provenance(self) -> ReferenceImage:
        if self.asset_id != "sha256-" + self.digest.removeprefix("sha256:"):
            raise ValueError("WARA reference image identifier does not match its digest")
        for value in (self.source_document_url, self.image_url):
            parsed = urlsplit(value)
            decoded_path = unquote(parsed.path)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "learn.microsoft.com"
                or parsed.username
                or parsed.password
                or parsed.port is not None
                or parsed.query
                or parsed.fragment
                or not decoded_path.startswith("/en-us/")
                or "\\" in decoded_path
                or any(part in {".", ".."} for part in decoded_path.split("/"))
                or any(ord(char) < 32 or ord(char) > 126 for char in value)
            ):
                raise ValueError("WARA reference image source must be a public Learn URL")
        for text in (self.alt, self.caption, self.english_in_image_notice):
            if any("<" in value or ">" in value for value in (text.en, text.ko or "")):
                raise ValueError("WARA reference image text must not contain markup")
        return self


class GuidanceConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    before: tuple[GuidanceText, ...] = Field(min_length=2, max_length=12)
    after: tuple[GuidanceText, ...] = Field(min_length=2, max_length=12)


class GuidanceNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier
    label: GuidanceText
    detail: GuidanceText
    role: Literal["subject", "configuration", "dependency", "evidence", "outcome"]


class GuidanceEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    from_: Identifier = Field(alias="from")
    to: Identifier
    label: GuidanceText
    style: Literal["solid", "dashed"]


class GuidanceDiagram(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier
    kind: Identifier
    title: GuidanceText
    description: GuidanceText
    nodes: tuple[GuidanceNode, ...] = Field(min_length=3, max_length=9)
    edges: tuple[GuidanceEdge, ...] = Field(min_length=2, max_length=12)

    @model_validator(mode="after")
    def validate_connections(self) -> GuidanceDiagram:
        identities = [node.id for node in self.nodes]
        if len(set(identities)) != len(identities):
            raise ValueError("WARA guidance diagram node identities are duplicated")
        known = set(identities)
        used: set[str] = set()
        connections = set()
        for edge in self.edges:
            if edge.from_ not in known or edge.to not in known or edge.from_ == edge.to:
                raise ValueError("WARA guidance diagram edge has invalid endpoints")
            pair = (edge.from_, edge.to)
            if pair in connections:
                raise ValueError("WARA guidance diagram edge is duplicated")
            connections.add(pair)
            used.update(pair)
        if used != known:
            raise ValueError("WARA guidance diagram contains an isolated node")
        return self


class GuidanceSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: GuidanceText
    url: str = Field(min_length=1, max_length=2_048)
    kind: Literal["aprl", "learn", "vendor"]

    @model_validator(mode="after")
    def validate_public_reference(self) -> GuidanceSource:
        parsed = urlsplit(self.url)
        decoded_path = unquote(parsed.path)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port is not None
            or parsed.query
            or any(ord(char) < 33 for char in self.url)
            or "\\" in decoded_path
            or any(part in {".", ".."} for part in decoded_path.split("/"))
            or any(ord(char) < 32 for char in decoded_path)
        ):
            raise ValueError("WARA guidance source must be a public HTTPS document reference")
        if self.kind == "learn":
            allowed = parsed.hostname == "learn.microsoft.com"
        elif self.kind == "vendor":
            allowed = (
                parsed.hostname == "docs.citrix.com"
                and parsed.path == "/us/en/citrix-daas-azure/limits.html"
                and not parsed.fragment
            )
        else:
            allowed = (
                parsed.hostname in {"github.com", "raw.githubusercontent.com"}
                and parsed.path.startswith("/Azure/Azure-Proactive-Resiliency-Library-v2/")
            ) or (
                parsed.hostname == "azure.github.io"
                and parsed.path.startswith("/Azure-Proactive-Resiliency-Library")
            )
        if not allowed:
            raise ValueError("WARA guidance source is outside the reviewed documentation origins")
        return self


class WaraGuidance(BaseModel):
    """A presentation record; it contains no operational finding or authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    recommendation_id: Annotated[str, Field(pattern=_GUID)]
    source_revision: Annotated[str, Field(pattern=_REVISION)]
    source_digest: Digest
    lifecycle: Literal["active", "disabled"]
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
    reference_image: ReferenceImage | None = None
    sources: tuple[GuidanceSource, ...] = Field(min_length=1, max_length=8)
    content_digest: Digest

    @model_validator(mode="after")
    def validate_identity(self) -> WaraGuidance:
        material = self.model_dump(
            mode="json", by_alias=True, exclude={"content_digest"}, exclude_none=True
        )
        if self.content_digest != "sha256:" + canonical_digest(material):
            raise ValueError("WARA guidance content digest does not match its material")
        if not any(source.kind == "aprl" for source in self.sources):
            raise ValueError("WARA guidance must cite the exact APRL source")
        return self


class WaraGuidanceCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    framework_revision: Annotated[str, Field(pattern=_REVISION)]
    framework_digest: Digest
    entries: tuple[WaraGuidance, ...] = Field(min_length=456, max_length=456)
    catalog_digest: Digest

    @model_validator(mode="after")
    def validate_accounting(self) -> WaraGuidanceCatalog:
        identities = [entry.recommendation_id for entry in self.entries]
        if len(set(identities)) != len(identities):
            raise ValueError("WARA guidance recommendation identities are duplicated")
        if sum(entry.lifecycle == "active" for entry in self.entries) != 393:
            raise ValueError("WARA guidance active and disabled accounting is incomplete")
        if any(entry.source_revision != self.framework_revision for entry in self.entries):
            raise ValueError("WARA guidance source revisions are inconsistent")
        material = self.model_dump(
            mode="json", by_alias=True, exclude={"catalog_digest"}, exclude_none=True
        )
        if self.catalog_digest != "sha256:" + canonical_digest(material):
            raise ValueError("WARA guidance catalog digest does not match its material")
        return self

    def resolve(self, recommendation_id: str) -> WaraGuidance | None:
        return next(
            (entry for entry in self.entries if entry.recommendation_id == recommendation_id),
            None,
        )


def load_wara_guidance(body: bytes) -> WaraGuidanceCatalog:
    if len(body) > _MAXIMUM_BYTES:
        raise ValueError("WARA guidance catalog exceeds its byte limit")
    catalog = WaraGuidanceCatalog.model_validate_json(body)
    from .reference_image_assets import load_packaged_reference_image

    for entry in catalog.entries:
        if entry.reference_image is not None:
            load_packaged_reference_image(entry.reference_image)
    return catalog


class _GuidanceShardReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Annotated[str, Field(pattern=r"^wara-guidance-[0-9]{2}\.json$")]
    digest: Digest
    count: int = Field(strict=True, ge=1, le=64)


class _GuidanceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    framework_revision: Annotated[str, Field(pattern=_REVISION)]
    framework_digest: Digest
    catalog_digest: Digest
    shards: tuple[_GuidanceShardReference, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_counts(self) -> _GuidanceManifest:
        paths = [shard.path for shard in self.shards]
        if len(set(paths)) != len(paths) or sum(shard.count for shard in self.shards) != 456:
            raise ValueError("WARA guidance shard accounting is incomplete or duplicated")
        return self


class _GuidanceShard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: tuple[WaraGuidance, ...] = Field(min_length=1, max_length=64)


@lru_cache(maxsize=1)
def packaged_wara_guidance() -> WaraGuidanceCatalog:
    """Load immutable installed public content, never a deployment-provided URL."""

    directory = resources.files("fdai_service_contracts").joinpath("data")
    source = directory.joinpath("wara-guidance.json")
    try:
        with source.open("rb") as stream:
            body = stream.read(_MAXIMUM_SHARD_BYTES + 1)
    except OSError as exc:
        raise ValueError("packaged WARA guidance catalog is unavailable") from exc
    if len(body) > _MAXIMUM_SHARD_BYTES:
        raise ValueError("WARA guidance manifest exceeds its byte limit")
    manifest = _GuidanceManifest.model_validate_json(body)
    entries: list[dict[str, object]] = []
    total_bytes = len(body)
    for reference in manifest.shards:
        try:
            with directory.joinpath(reference.path).open("rb") as stream:
                body = stream.read(_MAXIMUM_SHARD_BYTES + 1)
        except OSError as exc:
            raise ValueError("packaged WARA guidance shard is unavailable") from exc
        total_bytes += len(body)
        if len(body) > _MAXIMUM_SHARD_BYTES or total_bytes > _MAXIMUM_BYTES:
            raise ValueError("WARA guidance shard exceeds its byte limit")
        if "sha256:" + hashlib.sha256(body).hexdigest() != reference.digest:
            raise ValueError("WARA guidance shard digest does not match the manifest")
        shard = _GuidanceShard.model_validate_json(body)
        if len(shard.entries) != reference.count:
            raise ValueError("WARA guidance shard count does not match the manifest")
        entries.extend(
            entry.model_dump(mode="json", by_alias=True, exclude_none=True)
            for entry in shard.entries
        )
    material = {
        "schema_version": manifest.schema_version,
        "framework_revision": manifest.framework_revision,
        "framework_digest": manifest.framework_digest,
        "catalog_digest": manifest.catalog_digest,
        "entries": entries,
    }
    return load_wara_guidance(json.dumps(material, ensure_ascii=False).encode("utf-8"))


def assert_wara_guidance_framework(catalog: WaraGuidanceCatalog, framework_body: bytes) -> None:
    """Bind generated guidance to its exact catalog without importing the Core service."""

    if catalog.framework_digest != "sha256:" + hashlib.sha256(framework_body).hexdigest():
        raise ValueError("WARA guidance framework digest does not match the catalog")


@lru_cache(maxsize=1)
def _korean_titles_by_id() -> dict[str, tuple[str, str, str, str]]:
    return {
        entry.recommendation_id: (
            entry.title.ko,
            entry.source_revision,
            entry.source_digest,
            entry.lifecycle,
        )
        for entry in packaged_wara_guidance().entries
        if entry.title.ko is not None
    }


def localized_wara_titles(controls: Iterable[Mapping[str, object]]) -> dict[str, str]:
    """Return Korean titles keyed by recommendation id for controls whose exact source matches.

    A control whose revision, digest or lifecycle differs from the packaged guide is omitted, so
    a stale title is never attached. An unavailable packaged catalog yields no titles instead of
    failing the list, because titles are display text and never part of an assessment.
    """

    try:
        known = _korean_titles_by_id()
    except ValueError:
        return {}
    titles: dict[str, str] = {}
    for control in controls:
        recommendation_id = control.get("id")
        record = known.get(recommendation_id) if isinstance(recommendation_id, str) else None
        if (
            record is not None
            and (
                control.get("source_revision"),
                control.get("source_digest"),
                control.get("lifecycle"),
            )
            == record[1:]
        ):
            titles[cast(str, recommendation_id)] = record[0]
    return titles


def wara_guidance_detail(control: dict[str, object]) -> dict[str, object]:
    """Attach one exact-source public guide without changing stored evaluation fields."""

    recommendation_id = control.get("id")
    if not isinstance(recommendation_id, str) or re.fullmatch(_GUID, recommendation_id) is None:
        return {**control, "guidance": None}
    catalog = packaged_wara_guidance()
    guidance = catalog.resolve(recommendation_id)
    if guidance is None:
        return {**control, "guidance": None}
    if (
        control.get("source_revision") != guidance.source_revision
        or control.get("source_digest") != guidance.source_digest
        or control.get("lifecycle") != guidance.lifecycle
    ):
        raise ValueError("WARA guidance does not match the selected recommendation source")
    return {
        **control,
        "description": guidance.summary.en,
        "potential_benefits": guidance.benefits.en,
        "guidance": guidance.model_dump(mode="json", by_alias=True, exclude_none=True),
    }


__all__ = [
    "GuidanceDiagram",
    "GuidanceText",
    "ReferenceImage",
    "WaraGuidance",
    "WaraGuidanceCatalog",
    "assert_wara_guidance_framework",
    "localized_wara_titles",
    "load_wara_guidance",
    "packaged_wara_guidance",
    "wara_guidance_detail",
]
