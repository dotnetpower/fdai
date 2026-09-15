"""Closed original-free article structure; offsets refer to Unicode code points, not bytes.

The manifest authenticates this representation, not the truth of its content.
No link, context reference, or installed recipe grants authority or performs I/O.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Final, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, StrictInt, field_validator, model_validator

from fdai_service_contracts.cloud_knowledge import (
    CloudSourceEvidence,
    Digest,
    Identifier,
    KnowledgeContract,
    canonical_bytes,
    content_digest,
)

STRUCTURE_RECIPE: Final = "article-blocks-2.0.0"
RECIPE_DIGEST = content_digest(STRUCTURE_RECIPE.encode())
MAX_EXCERPT_BYTES = 8192
MAX_BLOCKS = 8192


class CloudArticleBlock(KnowledgeContract):
    """One non-overlapping atomic text region with explicit supporting context."""

    block_id: Identifier
    kind: Literal["heading", "paragraph", "list", "code", "table_row", "notice"]
    start: Annotated[StrictInt, Field(ge=0)]
    end: Annotated[StrictInt, Field(gt=0)]
    heading_path: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=256)], ...], Field(max_length=6)
    ] = ()
    context_ids: Annotated[tuple[Identifier, ...], Field(max_length=64)] = ()
    table_id: Identifier | None = None
    table_header: Annotated[str, Field(max_length=4096)] | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if self.end <= self.start or len(set(self.context_ids)) != len(self.context_ids):
            raise ValueError("article block must have an ordered span and unique context")
        if self.block_id in self.context_ids:
            raise ValueError("article block cannot depend on itself")
        if (self.kind == "table_row") != (self.table_id is not None):
            raise ValueError("table rows require a table identity")
        if (self.kind == "table_row") != bool(self.table_header):
            raise ValueError("table rows require explicit column context")
        return self


class CloudArticleLink(KnowledgeContract):
    """Inert source-local attribution link; never an allowlist entry or fetch command."""

    block_id: Identifier
    label: Annotated[str, Field(max_length=1024)]
    target: Annotated[str, Field(min_length=1, max_length=2048)]

    @field_validator("target")
    @classmethod
    def inert_target(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 80, 443}
            or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("article link must be inert credential-free HTTP provenance")
        return value


class CloudStructuredDocument(KnowledgeContract):
    """V3 normalized text and complete block lineage; originals are forbidden."""

    evidence: CloudSourceEvidence
    title: Annotated[str, Field(min_length=1, max_length=256)]
    text: Annotated[str, Field(min_length=1, max_length=8 * 1024 * 1024)]
    normalizer_version: Literal["2.0.0"] = "2.0.0"
    recipe: Literal["article-blocks-2.0.0"] = STRUCTURE_RECIPE
    recipe_digest: Digest = RECIPE_DIGEST
    derived_at: datetime
    parent_normalized_sha256: Digest | None = None
    blocks: Annotated[tuple[CloudArticleBlock, ...], Field(min_length=1, max_length=MAX_BLOCKS)]
    links: Annotated[tuple[CloudArticleLink, ...], Field(max_length=16384)] = ()
    required_context_ids: Annotated[tuple[Identifier, ...], Field(max_length=64)] = ()
    unresolved_dependencies: Annotated[tuple[Identifier, ...], Field(max_length=64)] = ()

    @model_validator(mode="after")
    def structure(self) -> Self:
        if self.recipe_digest != RECIPE_DIGEST:
            raise ValueError("article recipe digest is not installed")
        if self.derived_at < self.evidence.collected_at:
            raise ValueError("article derivation cannot precede source collection")
        if len(self.text.encode()) > 8 * 1024 * 1024 or "\x00" in self.text:
            raise ValueError("article text exceeds its UTF-8 budget")
        if content_digest(self.text.encode()) != self.evidence.normalized_sha256:
            raise ValueError("article normalized hash does not match text")
        by_id = {block.block_id: block for block in self.blocks}
        if len(by_id) != len(self.blocks):
            raise ValueError("article block identities must be unique")
        cursor = 0
        for block in self.blocks:
            if block.start != cursor or block.end > len(self.text):
                raise ValueError("article blocks must cover exactly the normalized body")
            if not self.text[block.start : block.end].strip():
                raise ValueError("article block cannot be empty")
            cursor = block.end + 2
            if block is not self.blocks[-1] and self.text[block.end : cursor] != "\n\n":
                raise ValueError("article block separators must be canonical")
            if any(identity not in by_id for identity in block.context_ids):
                raise ValueError("article context reference is missing")
        if self.blocks[-1].end != len(self.text):
            raise ValueError("article body contains unrepresented trailing content")
        if len(set(self.required_context_ids)) != len(self.required_context_ids):
            raise ValueError("required article context must be unique")
        if any(identity not in by_id for identity in self.required_context_ids):
            raise ValueError("required article context is missing")
        if len(set(self.unresolved_dependencies)) != len(self.unresolved_dependencies):
            raise ValueError("unresolved dependencies must be unique")
        if any(link.block_id not in by_id for link in self.links):
            raise ValueError("article link must identify a represented block")
        # Context is deliberately one level: no cycles or attacker-amplified recursive expansion.
        if any(by_id[ref].context_ids for block in self.blocks for ref in block.context_ids):
            raise ValueError("article context cannot contain recursive dependencies")
        if any(by_id[ref].context_ids for ref in self.required_context_ids):
            raise ValueError("global article context cannot contain recursive dependencies")
        return self

    @property
    def processing_digest(self) -> str:
        """Content/recipe/structure identity excluding check and local derivation clocks."""
        values = self.model_dump(
            mode="json", exclude={"evidence", "derived_at", "parent_normalized_sha256"}
        )
        values["source"] = self.evidence.model_dump(mode="json", exclude={"check"})
        return content_digest(
            json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        )


class CloudStructuredExcerpt(KnowledgeContract):
    """One exact bounded evidence bundle; unit identity pins recipe and bytes."""

    unit_id: Identifier
    block_id: Identifier
    heading: Annotated[str, Field(min_length=1, max_length=256)]
    text: Annotated[str, Field(min_length=1)]

    @field_validator("text")
    @classmethod
    def bounded_text(cls, value: str) -> str:
        if len(value.encode()) > MAX_EXCERPT_BYTES:
            raise ValueError("article evidence bundle exceeds the safe excerpt byte limit")
        return value


def structured_excerpts(document: CloudStructuredDocument) -> tuple[CloudStructuredExcerpt, ...]:
    """Revalidate and derive every atomic bundle; one failure holds the whole generation."""
    document = CloudStructuredDocument.model_validate(document.model_dump(warnings="error"))
    if document.unresolved_dependencies:
        raise ValueError("article required dependencies remain unresolved")
    by_id = {block.block_id: block for block in document.blocks}
    processing = document.processing_digest
    links_by_block: dict[str, list[CloudArticleLink]] = {}
    for link in document.links:
        links_by_block.setdefault(link.block_id, []).append(link)
    source = document.evidence
    prefix = (
        f"Source: {source.source_url}\nResource: {source.applicability.resource_type}\n"
        f"Generation: {source.applicability.service_generation}; "
        f"SKU: {', '.join(source.applicability.skus) or 'not specified'}\n"
    )
    excerpts = []
    for block in document.blocks:
        heading = " / ".join(block.heading_path) or document.title
        context = dict.fromkeys((*document.required_context_ids, *block.context_ids))
        parts = [prefix, f"Section: {heading}\n"]
        if block.table_header:
            parts.append(f"Table columns: {block.table_header}\n")
        parts.append(document.text[block.start : block.end])
        for ref in context:
            if ref != block.block_id:
                dependency = by_id[ref]
                parts.append(
                    "\nRequired context: " + document.text[dependency.start : dependency.end]
                )
        for identity in dict.fromkeys((block.block_id, *context)):
            for link in links_by_block.get(identity, ()):
                parts.append(f"\nLink: {link.label} <{link.target}>")
        text = "".join(parts)
        identity = content_digest((processing + block.block_id + text).encode())[:32]
        excerpts.append(
            CloudStructuredExcerpt(
                unit_id=f"cloud:{content_digest(source.source_id.encode())[:16]}:v3:{identity}",
                block_id=block.block_id,
                heading=heading[:256],
                text=text,
            )
        )
    return tuple(excerpts)


def excerpt_digest(document: CloudStructuredDocument) -> str:
    """Bind the complete ordered derived inventory without including duplicate bodies in transport."""
    return content_digest(
        b"\n".join(canonical_bytes(item) for item in structured_excerpts(document))
    )
