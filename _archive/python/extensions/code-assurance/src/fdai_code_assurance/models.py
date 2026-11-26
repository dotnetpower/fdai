"""Immutable inputs and outputs for bounded pull-request review."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ReviewProfile(StrEnum):
    CODE = "code"
    SECURITY = "security"
    ALL = "all"


class FindingSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class PullRequestFile:
    path: str
    status: str
    additions: int
    deletions: int
    patch: str | None


@dataclass(frozen=True, slots=True)
class PullRequestSnapshot:
    repository: str
    pull_number: int
    base_sha: str
    head_sha: str
    changed_files: int
    files: tuple[PullRequestFile, ...]


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    rule_id: str
    severity: FindingSeverity
    category: str
    path: str
    line: int
    message: str
    evidence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "category": self.category,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class ReviewReport:
    repository: str
    pull_number: int
    base_sha: str
    head_sha: str
    profile: ReviewProfile
    changed_files: int
    reviewed_files: int
    omitted_patch_files: tuple[str, ...]
    findings: tuple[ReviewFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "fdai.code-assurance.review.v1",
            "repository": self.repository,
            "pull_number": self.pull_number,
            "base_sha": self.base_sha,
            "head_sha": self.head_sha,
            "profile": self.profile.value,
            "changed_files": self.changed_files,
            "reviewed_files": self.reviewed_files,
            "omitted_patch_files": list(self.omitted_patch_files),
            "coverage_complete": (
                self.reviewed_files == self.changed_files and not self.omitted_patch_files
            ),
            "finding_count": len(self.findings),
            "findings": [finding.to_dict() for finding in self.findings],
        }


__all__ = [
    "FindingSeverity",
    "PullRequestFile",
    "PullRequestSnapshot",
    "ReviewFinding",
    "ReviewProfile",
    "ReviewReport",
]
