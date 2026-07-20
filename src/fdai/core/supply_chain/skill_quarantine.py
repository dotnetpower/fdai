"""Content-addressed skill quarantine records and deterministic scanning."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol

_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_MAX_FILE_BYTES = 256 * 1024
_MAX_ARTIFACT_BYTES = 1024 * 1024
_MAX_FILES = 64


class SkillQuarantineState(StrEnum):
    FETCHED = "fetched"
    PASSED = "passed"
    BLOCKED = "blocked"
    PROPOSED = "proposed"
    REVOKED = "revoked"


class SkillScanSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    DANGEROUS = "dangerous"


class SkillScanVerdict(StrEnum):
    PASS = "pass"  # noqa: S105 - scan verdict, not a credential
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class QuarantinedSkillFile:
    path: str
    content_sha256: str
    content: bytes
    media_type: str
    is_symlink: bool = False

    def __post_init__(self) -> None:
        _safe_path(self.path)
        if self.is_symlink:
            raise ValueError("skill quarantine rejects symlinks")
        if not self.content or len(self.content) > _MAX_FILE_BYTES:
            raise ValueError("skill quarantine file MUST be non-empty and bounded")
        if _DIGEST.fullmatch(self.content_sha256) is None:
            raise ValueError("skill quarantine file digest MUST be lowercase SHA-256")
        if hashlib.sha256(self.content).hexdigest() != self.content_sha256:
            raise ValueError("skill quarantine file digest does not match content")
        if not self.media_type or len(self.media_type) > 128:
            raise ValueError("skill quarantine media_type MUST be bounded")


@dataclass(frozen=True, slots=True)
class SkillScanFinding:
    scanner: str
    code: str
    severity: SkillScanSeverity
    path: str
    detail: str

    def __post_init__(self) -> None:
        _safe_path(self.path)
        for name, value in (
            ("scanner", self.scanner),
            ("code", self.code),
            ("detail", self.detail),
        ):
            if not value.strip() or len(value) > 512:
                raise ValueError(f"skill scan finding {name} MUST be bounded")


@dataclass(frozen=True, slots=True)
class QuarantinedSkillArtifact:
    quarantine_id: str
    source_id: str
    source_revision: str
    artifact_digest: str
    files: tuple[QuarantinedSkillFile, ...]
    publisher_signature: bytes
    fetched_at: datetime
    scanner_version: str | None = None
    findings: tuple[SkillScanFinding, ...] = ()
    verdict: SkillScanVerdict | None = None
    state: SkillQuarantineState = SkillQuarantineState.FETCHED
    prior_installed_digest: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("quarantine_id", self.quarantine_id),
            ("source_id", self.source_id),
            ("source_revision", self.source_revision),
        ):
            if not value.strip() or len(value) > 256:
                raise ValueError(f"skill quarantine {name} MUST be bounded")
        if _DIGEST.fullmatch(self.artifact_digest) is None:
            raise ValueError("skill quarantine artifact_digest MUST be lowercase SHA-256")
        if not self.files or len(self.files) > _MAX_FILES:
            raise ValueError("skill quarantine requires 1..64 files")
        if len({item.path for item in self.files}) != len(self.files):
            raise ValueError("skill quarantine file paths MUST be unique")
        if sum(len(item.content) for item in self.files) > _MAX_ARTIFACT_BYTES:
            raise ValueError("skill quarantine artifact exceeds byte budget")
        digest = hashlib.sha256()
        for item in sorted(self.files, key=lambda value: value.path):
            digest.update(item.path.encode())
            digest.update(b"\0")
            digest.update(item.content)
            digest.update(b"\0")
        if digest.hexdigest() != self.artifact_digest:
            raise ValueError("skill quarantine artifact digest does not match files")
        if len(self.publisher_signature) != 64:
            raise ValueError("skill quarantine publisher_signature MUST be 64 bytes")
        if self.fetched_at.tzinfo is None:
            raise ValueError("skill quarantine fetched_at MUST include timezone")
        if (
            self.prior_installed_digest is not None
            and _DIGEST.fullmatch(self.prior_installed_digest) is None
        ):
            raise ValueError("prior installed digest MUST be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class SkillUpdateCandidate:
    candidate_id: str
    quarantine_id: str
    artifact_digest: str
    prior_installed_digest: str | None
    created_at: datetime
    disabled: bool = True

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.quarantine_id:
            raise ValueError("skill update candidate ids MUST be non-empty")
        if not self.disabled:
            raise ValueError("skill update candidates MUST remain disabled")
        if self.prior_installed_digest == self.artifact_digest:
            raise ValueError("skill update candidate MUST contain a new digest")
        if self.created_at.tzinfo is None:
            raise ValueError("skill update candidate created_at MUST include timezone")


@dataclass(frozen=True, slots=True)
class SkillRevocation:
    revocation_id: str
    source_id: str
    artifact_digest: str
    reason: str
    revoked_at: datetime

    def __post_init__(self) -> None:
        if not self.revocation_id or not self.source_id or not self.reason.strip():
            raise ValueError("skill revocation identity and reason MUST be non-empty")
        if _DIGEST.fullmatch(self.artifact_digest) is None:
            raise ValueError("skill revocation digest MUST be lowercase SHA-256")
        if self.revoked_at.tzinfo is None:
            raise ValueError("skill revocation timestamp MUST include timezone")


@dataclass(frozen=True, slots=True)
class SkillSourceRefreshState:
    source_id: str
    last_refresh_at: datetime | None = None
    next_refresh_at: datetime | None = None
    last_etag: str | None = None
    last_revision: str | None = None
    error_count: int = 0
    retry_at: datetime | None = None
    last_error_kind: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id or len(self.source_id) > 128:
            raise ValueError("skill refresh source_id MUST be bounded")
        for name, value in (
            ("last_refresh_at", self.last_refresh_at),
            ("next_refresh_at", self.next_refresh_at),
            ("retry_at", self.retry_at),
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError(f"skill refresh {name} MUST include timezone")
        if self.error_count < 0:
            raise ValueError("skill refresh error_count MUST be non-negative")
        for text_name, text_value in (
            ("last_etag", self.last_etag),
            ("last_revision", self.last_revision),
            ("last_error_kind", self.last_error_kind),
        ):
            if text_value is not None and (not text_value.strip() or len(text_value) > 512):
                raise ValueError(f"skill refresh {text_name} MUST be bounded")


class SkillQuarantineStore(Protocol):
    async def put(self, artifact: QuarantinedSkillArtifact) -> QuarantinedSkillArtifact: ...

    async def get(self, quarantine_id: str) -> QuarantinedSkillArtifact | None: ...

    async def list(
        self, *, source_id: str | None = None
    ) -> tuple[QuarantinedSkillArtifact, ...]: ...

    async def mark_revoked(
        self, *, source_id: str, artifact_digest: str | None = None
    ) -> tuple[QuarantinedSkillArtifact, ...]: ...


class SkillUpdateCandidateStore(Protocol):
    async def put(self, candidate: SkillUpdateCandidate) -> SkillUpdateCandidate: ...

    async def get(self, candidate_id: str) -> SkillUpdateCandidate | None: ...

    async def list(self, *, source_id: str | None = None) -> tuple[SkillUpdateCandidate, ...]: ...


class SkillRevocationStore(Protocol):
    async def put(self, revocation: SkillRevocation) -> SkillRevocation: ...

    async def list(self, *, source_id: str | None = None) -> tuple[SkillRevocation, ...]: ...

    async def is_revoked(self, *, source_id: str, artifact_digest: str) -> bool: ...


class SkillSourceRefreshStateStore(Protocol):
    async def put(self, state: SkillSourceRefreshState) -> SkillSourceRefreshState: ...

    async def get(self, source_id: str) -> SkillSourceRefreshState | None: ...

    async def claim(
        self, *, source_id: str, now: datetime, hold_until: datetime
    ) -> SkillSourceRefreshState | None: ...


class InMemorySkillQuarantineStore:
    def __init__(self) -> None:
        self._artifacts: dict[str, QuarantinedSkillArtifact] = {}

    async def put(self, artifact: QuarantinedSkillArtifact) -> QuarantinedSkillArtifact:
        existing = self._artifacts.get(artifact.quarantine_id)
        if existing is not None and existing.artifact_digest != artifact.artifact_digest:
            raise ValueError("quarantine id conflicts with different content")
        if (
            existing is not None
            and existing.state is SkillQuarantineState.REVOKED
            and artifact.state is not SkillQuarantineState.REVOKED
        ):
            raise ValueError("revoked quarantine artifact cannot change state")
        self._artifacts[artifact.quarantine_id] = artifact
        return artifact

    async def get(self, quarantine_id: str) -> QuarantinedSkillArtifact | None:
        return self._artifacts.get(quarantine_id)

    async def list(self, *, source_id: str | None = None) -> tuple[QuarantinedSkillArtifact, ...]:
        artifacts = tuple(
            item
            for item in self._artifacts.values()
            if source_id is None or item.source_id == source_id
        )
        return tuple(sorted(artifacts, key=lambda item: (item.fetched_at, item.quarantine_id)))

    async def mark_revoked(
        self, *, source_id: str, artifact_digest: str | None = None
    ) -> tuple[QuarantinedSkillArtifact, ...]:
        revoked: list[QuarantinedSkillArtifact] = []
        for quarantine_id, artifact in self._artifacts.items():
            if artifact.source_id != source_id:
                continue
            if artifact_digest is not None and artifact.artifact_digest != artifact_digest:
                continue
            updated = replace(artifact, state=SkillQuarantineState.REVOKED)
            self._artifacts[quarantine_id] = updated
            revoked.append(updated)
        return tuple(sorted(revoked, key=lambda item: (item.fetched_at, item.quarantine_id)))


class InMemorySkillUpdateCandidateStore:
    def __init__(self, quarantine: SkillQuarantineStore) -> None:
        self._quarantine = quarantine
        self._candidates: dict[str, SkillUpdateCandidate] = {}

    async def put(self, candidate: SkillUpdateCandidate) -> SkillUpdateCandidate:
        existing = self._candidates.get(candidate.candidate_id)
        if existing is not None and existing != candidate:
            raise ValueError("candidate id conflicts with different content")
        self._candidates[candidate.candidate_id] = candidate
        return candidate

    async def get(self, candidate_id: str) -> SkillUpdateCandidate | None:
        return self._candidates.get(candidate_id)

    async def list(self, *, source_id: str | None = None) -> tuple[SkillUpdateCandidate, ...]:
        candidates = tuple(self._candidates.values())
        if source_id is not None:
            quarantine_ids = {
                artifact.quarantine_id
                for artifact in await self._quarantine.list(source_id=source_id)
            }
            candidates = tuple(
                candidate for candidate in candidates if candidate.quarantine_id in quarantine_ids
            )
        return tuple(sorted(candidates, key=lambda item: (item.created_at, item.candidate_id)))


class DeterministicSkillScanner:
    """Scan normalized text for instruction, exfiltration, command, and dependency risk."""

    _MARKERS: tuple[tuple[str, str], ...] = (
        ("prompt_injection", "ignore previous"),
        ("prompt_injection", "system:"),
        ("prompt_injection", "developer:"),
        ("exfiltration", "os.environ"),
        ("exfiltration", "process.env"),
        ("exfiltration", "authorization: bearer"),
        ("command_risk", "subprocess"),
        ("command_risk", "shell=true"),
        ("command_risk", "sudo "),
        ("dependency_install", "pip install"),
        ("dependency_install", "npm install"),
        ("dependency_install", "apt-get"),
    )

    def scan(
        self,
        artifact: QuarantinedSkillArtifact,
        *,
        scanner_version: str,
    ) -> QuarantinedSkillArtifact:
        if artifact.state is not SkillQuarantineState.FETCHED:
            raise ValueError("only fetched skill artifacts can be scanned")
        if not scanner_version.strip() or len(scanner_version) > 128:
            raise ValueError("scanner_version MUST be bounded")
        findings: list[SkillScanFinding] = []
        for item in artifact.files:
            try:
                decoded = item.content.decode("utf-8")
            except UnicodeDecodeError:
                findings.append(
                    SkillScanFinding(
                        scanner="deterministic-skill-scanner",
                        code="invalid_utf8",
                        severity=SkillScanSeverity.DANGEROUS,
                        path=item.path,
                        detail="Text skill content is not valid UTF-8.",
                    )
                )
                continue
            normalized = unicodedata.normalize("NFKC", decoded).casefold()
            for code, marker in self._MARKERS:
                if marker in normalized:
                    findings.append(
                        SkillScanFinding(
                            scanner="deterministic-skill-scanner",
                            code=code,
                            severity=SkillScanSeverity.DANGEROUS,
                            path=item.path,
                            detail=f"Blocked deterministic marker: {marker}",
                        )
                    )
        blocked = any(item.severity is SkillScanSeverity.DANGEROUS for item in findings)
        return replace(
            artifact,
            scanner_version=scanner_version,
            findings=tuple(findings),
            verdict=SkillScanVerdict.BLOCK if blocked else SkillScanVerdict.PASS,
            state=SkillQuarantineState.BLOCKED if blocked else SkillQuarantineState.PASSED,
        )


def quarantine_artifact_digest(files: tuple[QuarantinedSkillFile, ...]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda value: value.path):
        digest.update(item.path.encode())
        digest.update(b"\0")
        digest.update(item.content)
        digest.update(b"\0")
    return digest.hexdigest()


def _safe_path(value: str) -> None:
    if (
        not value
        or len(value) > 512
        or value.startswith(("/", "\\"))
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("skill quarantine path MUST be a safe relative path")


__all__ = [
    "DeterministicSkillScanner",
    "InMemorySkillQuarantineStore",
    "InMemorySkillUpdateCandidateStore",
    "QuarantinedSkillArtifact",
    "QuarantinedSkillFile",
    "SkillQuarantineState",
    "SkillQuarantineStore",
    "SkillRevocation",
    "SkillRevocationStore",
    "SkillScanFinding",
    "SkillScanSeverity",
    "SkillScanVerdict",
    "SkillSourceRefreshState",
    "SkillSourceRefreshStateStore",
    "SkillUpdateCandidate",
    "SkillUpdateCandidateStore",
    "quarantine_artifact_digest",
]
