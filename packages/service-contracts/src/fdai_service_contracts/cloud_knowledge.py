"""Provider-neutral public-document provenance and freshness contracts.

These records distinguish source observations from local transfer timestamps.
Validation and freshness classification perform no I/O and grant no authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")]
DAY = 86400


def canonical_bytes(value: BaseModel) -> bytes:
    """Encode a validated contract deterministically without losing Unicode prose."""
    return json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def content_digest(content: bytes) -> str:
    """Return a lowercase SHA-256 identity for exact bytes."""
    return hashlib.sha256(content).hexdigest()


def public_document_url(value: str) -> str:
    """Require a canonical credential-free HTTPS document URL, not an arbitrary fetch target."""
    parsed = urlsplit(value)
    if (
        len(value) > 2048
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or "\\" in value
        or "%" in value
        or any(part in {".", ".."} for part in parsed.path.split("/"))
        or re.search(r"[\x00-\x20\x7f]", value)
    ):
        raise ValueError("source URL MUST be canonical credential-free HTTPS")
    return value


class KnowledgeContract(BaseModel):
    """Closed immutable data record; all supplied timestamps are timezone-aware."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    @field_validator("*", mode="after")
    @classmethod
    def aware_times(cls, value: object) -> object:
        if isinstance(value, datetime) and value.utcoffset() is None:
            raise ValueError("knowledge timestamps MUST be timezone-aware")
        return value


class Freshness(StrEnum):
    FRESH = "fresh"
    REFRESH_DUE = "refresh_due"
    STALE = "stale"
    UNKNOWN = "unknown"


class RefreshPolicy(KnowledgeContract):
    """Approved source-check interval and a separate operational evidence ceiling."""

    policy_id: Identifier = "operational-v1"
    check_interval_seconds: Annotated[StrictInt, Field(ge=60, le=365 * DAY)] = 7 * DAY
    max_unverified_seconds: Annotated[StrictInt, Field(ge=60, le=365 * DAY)] = 30 * DAY
    full_fetch_interval_seconds: Annotated[StrictInt, Field(ge=60, le=365 * DAY)] = 30 * DAY

    @model_validator(mode="after")
    def intervals(self) -> Self:
        if self.max_unverified_seconds < self.check_interval_seconds:
            raise ValueError("freshness ceiling MUST NOT precede the check interval")
        return self


class Applicability(KnowledgeContract):
    """Exact provider identities and explicitly stated conditions, not inferred synonyms."""

    provider: Identifier = "azure"
    resource_type: Annotated[str, Field(min_length=1, max_length=256)]
    service_generation: Identifier
    skus: Annotated[tuple[Identifier, ...], Field(max_length=32)] = ()
    api_versions: Annotated[tuple[Identifier, ...], Field(max_length=32)] = ()
    regions: Annotated[tuple[Identifier, ...], Field(max_length=128)] = ()
    deployment_modes: Annotated[tuple[Identifier, ...], Field(max_length=32)] = ()

    def matches(self, target: Applicability) -> bool:
        """Match exact declared constraints; missing required conditions remain unknown."""
        if (self.provider, self.resource_type.casefold(), self.service_generation) != (
            target.provider,
            target.resource_type.casefold(),
            target.service_generation,
        ):
            return False
        return all(
            (not wanted and not declared)
            or bool(wanted and declared)
            and set(wanted).issubset(declared)
            for declared, wanted in (
                (self.skus, target.skus),
                (self.api_versions, target.api_versions),
                (self.regions, target.regions),
                (self.deployment_modes, target.deployment_modes),
            )
        )


class CloudKnowledgeSource(KnowledgeContract):
    """Deployment-reviewed source policy; connectivity alone never enables collection."""

    source_id: Identifier
    collection_id: Identifier
    url: str
    title: Annotated[str, Field(min_length=1, max_length=256)]
    applicability: Applicability
    locale: Literal["en", "ko"] = "en"
    mode: Literal["online", "offline"] = "offline"
    enabled: bool = False
    storage_allowed: bool = False
    internal_transfer_allowed: bool = False
    license_ref: Annotated[str, Field(min_length=1, max_length=256)]
    policy: RefreshPolicy = RefreshPolicy()
    max_bytes: Annotated[StrictInt, Field(ge=1, le=8 * 1024 * 1024)] = 1024 * 1024

    _url = field_validator("url")(public_document_url)


class SourceRegistryRevision(KnowledgeContract):
    """Exact reviewed registry revision delivered independently of document packages."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    revision: Annotated[StrictInt, Field(ge=1)]
    approved_by: Identifier
    valid_until: datetime
    sources: Annotated[tuple[CloudKnowledgeSource, ...], Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        ids = [item.source_id for item in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("registry source identities MUST be unique")
        if any(item.applicability.provider != "azure" for item in self.sources):
            raise ValueError("only the approved Azure source adapter is available")
        return self

    @property
    def digest(self) -> str:
        return content_digest(canonical_bytes(self))


class SourceCheckReceipt(KnowledgeContract):
    """One immutable attempt; only successful digest-bound observations renew freshness."""

    source_id: Identifier
    source_url: str
    checked_at: datetime
    outcome: Literal["fetched", "unchanged", "changed", "failed", "withdrawal_pending"]
    content_sha256: Digest | None = None
    equivalence: Literal["body_hash", "strong_etag", "none"] = "none"
    etag: Annotated[str, Field(max_length=512)] | None = None
    last_modified: Annotated[str, Field(max_length=128)] | None = None
    collector_id: Identifier
    collector_version: Identifier = "1.0.0"
    reason: Identifier = "source_observed"

    _url = field_validator("source_url")(public_document_url)

    @model_validator(mode="after")
    def observation_binding(self) -> Self:
        success = self.outcome in {"fetched", "unchanged", "changed"}
        if success != (self.content_sha256 is not None and self.equivalence != "none"):
            raise ValueError("successful source checks MUST bind content and equivalence")
        if self.equivalence == "strong_etag" and (
            self.outcome != "unchanged"
            or self.etag is None
            or not re.fullmatch(r'"[\x21\x23-\x7e]{1,500}"', self.etag)
        ):
            raise ValueError("conditional equivalence requires a strong ETag")
        return self


class CloudSourceEvidence(KnowledgeContract):
    """Content-free source provenance safe to carry beside an authorized citation."""

    source_id: Identifier
    source_url: str
    source_sha256: Digest
    normalized_sha256: Digest
    collected_at: datetime
    source_updated_at: datetime | None = None
    check: SourceCheckReceipt
    applicability: Applicability
    policy: RefreshPolicy
    license_ref: Annotated[str, Field(min_length=1, max_length=256)]

    _url = field_validator("source_url")(public_document_url)

    @model_validator(mode="after")
    def bind_check(self) -> Self:
        if (
            self.check.source_id != self.source_id
            or self.check.source_url != self.source_url
            or self.check.content_sha256 != self.source_sha256
            or self.check.outcome not in {"fetched", "unchanged", "changed"}
            or self.check.checked_at < self.collected_at
        ):
            raise ValueError("source evidence MUST bind a successful same-body check")
        return self

    def freshness(self, now: datetime) -> Freshness:
        """Classify by source-check time; transfer and local index dates are not inputs."""
        if now.utcoffset() is None:
            raise ValueError("freshness clock MUST be timezone-aware")
        if self.check.checked_at > now or self.collected_at > now:
            return Freshness.UNKNOWN
        if self.source_updated_at is not None and self.source_updated_at > now:
            return Freshness.UNKNOWN
        age = now - self.check.checked_at
        if age >= timedelta(seconds=self.policy.max_unverified_seconds):
            return Freshness.STALE
        if age >= timedelta(seconds=self.policy.check_interval_seconds):
            return Freshness.REFRESH_DUE
        return Freshness.FRESH

    def allows_current_guidance(self, now: datetime, *, update_pending: bool = False) -> bool:
        """Permit checked-as-of guidance, never a claim of live resource observation."""
        return not update_pending and self.freshness(now) is Freshness.FRESH
