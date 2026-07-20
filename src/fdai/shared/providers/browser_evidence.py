"""Provider-neutral contracts for bounded, read-only browser evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

BrowserCaptureKind = Literal["screenshot", "visible_text", "aria_snapshot"]
BrowserReceiptStatus = Literal["captured", "unavailable", "abstained"]
BrowserReferenceKind = Literal["human", "api"]
BrowserReferenceStatus = Literal["available", "unavailable"]
_SENSITIVE_QUERY_KEYS = frozenset(
    {"access_token", "api_key", "apikey", "code", "password", "secret", "sig", "token"}
)


def canonical_browser_hostname(value: str) -> str:
    """Return the lower-case IDNA ASCII form of one hostname."""

    candidate = value.strip().rstrip(".")
    if not candidate or any(character.isspace() for character in candidate):
        raise ValueError("browser policy hostname MUST be non-empty and contain no whitespace")
    try:
        canonical = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("browser policy hostname MUST be valid IDNA") from exc
    if len(canonical) > 253:
        raise ValueError("browser policy hostname exceeds the DNS length limit")
    return canonical


def _browser_path_prefix(value: str) -> str:
    if not value.startswith("/") or "?" in value or "#" in value:
        raise ValueError("browser policy path prefix MUST be an absolute path")
    return value.rstrip("/") or "/"


@dataclass(frozen=True, slots=True)
class BrowserCaptureLimits:
    max_response_bytes: int
    max_text_chars: int
    max_snapshot_chars: int
    timeout_seconds: float
    max_screenshot_bytes: int = 5_000_000
    max_selectors: int = 32

    def __post_init__(self) -> None:
        values = (
            self.max_response_bytes,
            self.max_text_chars,
            self.max_snapshot_chars,
            self.max_screenshot_bytes,
            self.max_selectors,
        )
        if any(value < 1 for value in values) or self.timeout_seconds <= 0:
            raise ValueError("browser capture limits MUST be positive")


@dataclass(frozen=True, slots=True)
class TrustedBrowserDestination:
    scheme: str
    host: str
    path_prefixes: tuple[str, ...]
    port: int = 443

    def __post_init__(self) -> None:
        if self.scheme.lower() != "https":
            raise ValueError("trusted browser destinations MUST use HTTPS")
        if self.port != 443:
            raise ValueError("trusted browser destinations MUST use port 443")
        if not self.path_prefixes:
            raise ValueError("trusted browser destination path prefixes MUST be non-empty")
        object.__setattr__(self, "scheme", "https")
        object.__setattr__(self, "host", canonical_browser_hostname(self.host))
        object.__setattr__(
            self,
            "path_prefixes",
            tuple(_browser_path_prefix(value) for value in self.path_prefixes),
        )


@dataclass(frozen=True, slots=True)
class BrowserRedirectPolicy:
    max_redirects: int
    trusted_destinations: tuple[TrustedBrowserDestination, ...] = ()

    def __post_init__(self) -> None:
        if self.max_redirects < 0 or self.max_redirects > 10:
            raise ValueError("browser redirect max_redirects MUST be between 0 and 10")


@dataclass(frozen=True, slots=True)
class BrowserOriginPolicy:
    policy_id: str
    version: int
    allowed_schemes: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    allowed_path_prefixes: tuple[str, ...]
    auth_profile_ref: str
    redirect_policy: BrowserRedirectPolicy
    limits: BrowserCaptureLimits
    sensitive_region_selectors: tuple[str, ...] = ()
    text_redaction_patterns: tuple[str, ...] = ()
    secret_canary_markers: tuple[str, ...] = ()
    allowed_query_keys: tuple[str, ...] = ()
    retention_days: int = 30

    def __post_init__(self) -> None:
        if not self.policy_id or self.version < 1:
            raise ValueError("browser origin policy id and version MUST be valid")
        schemes = tuple(value.lower() for value in self.allowed_schemes)
        if schemes != ("https",):
            raise ValueError("browser origin policies MUST allow exactly HTTPS")
        if not self.allowed_hosts or not self.allowed_path_prefixes:
            raise ValueError("browser origin policy hosts and paths MUST be non-empty")
        if not self.auth_profile_ref or any(
            marker in self.auth_profile_ref.lower()
            for marker in ("password=", "token=", "secret=", "bearer ")
        ):
            raise ValueError("browser auth_profile_ref MUST be an opaque non-secret reference")
        if self.retention_days < 1:
            raise ValueError("browser evidence retention_days MUST be positive")
        if {key.lower() for key in self.allowed_query_keys} & _SENSITIVE_QUERY_KEYS:
            raise ValueError("browser origin policy query keys MUST NOT carry credentials")
        object.__setattr__(self, "allowed_schemes", schemes)
        object.__setattr__(
            self,
            "allowed_hosts",
            tuple(canonical_browser_hostname(value) for value in self.allowed_hosts),
        )
        object.__setattr__(
            self,
            "allowed_path_prefixes",
            tuple(_browser_path_prefix(value) for value in self.allowed_path_prefixes),
        )


@dataclass(frozen=True, slots=True)
class BrowserCaptureRequest:
    """Credential-free request accepted by the evidence-only facade."""

    request_id: str
    policy_id: str
    policy_version: int
    source_url: str
    stable_selectors: tuple[str, ...]
    capture_kinds: tuple[BrowserCaptureKind, ...]
    correlation_id: str

    def __post_init__(self) -> None:
        if not all((self.request_id, self.policy_id, self.source_url, self.correlation_id)):
            raise ValueError("browser capture request identifiers MUST be non-empty")
        if self.policy_version < 1 or not self.capture_kinds:
            raise ValueError("browser capture request version and kinds MUST be valid")
        if len(set(self.capture_kinds)) != len(self.capture_kinds):
            raise ValueError("browser capture kinds MUST be unique")


@dataclass(frozen=True, slots=True)
class BrowserRuntimeIsolation:
    """Evidence that the delivery runtime applied its isolation profile."""

    executor_identity_present: bool
    host_filesystem_mounted: bool
    environment_scrubbed: bool
    restricted_egress: bool
    ephemeral_profile: bool

    @property
    def verified(self) -> bool:
        return (
            not self.executor_identity_present
            and not self.host_filesystem_mounted
            and self.environment_scrubbed
            and self.restricted_egress
            and self.ephemeral_profile
        )


@dataclass(frozen=True, slots=True)
class BrowserRedactionEntry:
    surface: Literal["screenshot", "visible_text", "aria_snapshot"]
    rule: str
    replacements: int


@dataclass(frozen=True, slots=True)
class BrowserCaptureMaterial:
    """Sanitized adapter output awaiting hashing and durable storage."""

    canonical_source_url: str
    canonical_final_url: str
    screenshot: bytes | None
    visible_text: str | None
    aria_snapshot: str | None
    selectors: tuple[str, ...]
    redacted_selectors: tuple[str, ...]
    redactions: tuple[BrowserRedactionEntry, ...]
    browser_version: str
    isolation: BrowserRuntimeIsolation
    response_bytes: int


@dataclass(frozen=True, slots=True)
class BrowserEvidencePayload:
    screenshot: bytes | None
    visible_text: str | None
    aria_snapshot: str | None


@dataclass(frozen=True, slots=True)
class BrowserEvidenceArtifact:
    artifact_id: str
    policy_id: str
    policy_version: int
    canonical_source_url: str
    canonical_final_url: str
    captured_at: datetime
    selectors: tuple[str, ...]
    screenshot_hash: str | None
    text_hash: str | None
    snapshot_hash: str | None
    redaction_manifest: tuple[BrowserRedactionEntry, ...]
    browser_version: str
    chain_of_custody_audit_ref: str
    content_digest: str
    prompt_injection_findings: tuple[str, ...]
    isolation: BrowserRuntimeIsolation
    expires_at: datetime
    untrusted: bool = True

    def __post_init__(self) -> None:
        if not self.untrusted:
            raise ValueError("browser evidence MUST remain untrusted")
        if not self.isolation.verified:
            raise ValueError("browser evidence isolation MUST be verified")

    @property
    def can_authorize_action(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class StoredBrowserEvidence:
    artifact: BrowserEvidenceArtifact
    payload: BrowserEvidencePayload


@dataclass(frozen=True, slots=True)
class BrowserEvidenceReceipt:
    request_id: str
    status: BrowserReceiptStatus
    artifact_id: str | None
    content_digest: str | None
    chain_of_custody_audit_ref: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class BrowserEvidenceReference:
    kind: BrowserReferenceKind
    status: BrowserReferenceStatus
    content_digest: str | None


@runtime_checkable
class BrowserEvidenceProvider(Protocol):
    """The complete public browser adapter surface. It exposes no page handle."""

    async def capture(
        self,
        *,
        policy: BrowserOriginPolicy,
        request: BrowserCaptureRequest,
    ) -> BrowserCaptureMaterial: ...


@runtime_checkable
class BrowserEvidenceArtifactStore(Protocol):
    async def put(self, evidence: StoredBrowserEvidence) -> bool: ...

    async def get(self, artifact_id: str) -> StoredBrowserEvidence | None: ...

    async def list_artifacts(self, *, limit: int) -> tuple[BrowserEvidenceArtifact, ...]: ...

    async def purge_expired(self, *, now: datetime, limit: int) -> tuple[str, ...]: ...


@runtime_checkable
class BrowserEvidenceCustodySink(Protocol):
    async def record_capture(
        self,
        *,
        request_id: str,
        policy_ref: str,
        content_digest: str,
        captured_at: datetime,
        correlation_id: str,
    ) -> str: ...


__all__ = [
    "BrowserCaptureKind",
    "BrowserCaptureLimits",
    "BrowserCaptureMaterial",
    "BrowserCaptureRequest",
    "BrowserEvidenceArtifact",
    "BrowserEvidenceArtifactStore",
    "BrowserEvidenceCustodySink",
    "BrowserEvidencePayload",
    "BrowserEvidenceProvider",
    "BrowserEvidenceReceipt",
    "BrowserEvidenceReference",
    "BrowserOriginPolicy",
    "BrowserReceiptStatus",
    "BrowserRedactionEntry",
    "BrowserRedirectPolicy",
    "BrowserReferenceKind",
    "BrowserReferenceStatus",
    "BrowserRuntimeIsolation",
    "StoredBrowserEvidence",
    "TrustedBrowserDestination",
    "canonical_browser_hostname",
]
