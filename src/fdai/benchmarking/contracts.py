"""Stable values exchanged between benchmark plugins and the FDAI runner."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

_MAX_ID_LENGTH = 256
_MAX_TEXT_LENGTH = 20_000
_MAX_METADATA_ENTRIES = 64
_MAX_METADATA_VALUE_LENGTH = 2_048
_MAX_EVIDENCE_REFS = 256


class BenchmarkStatus(StrEnum):
    """Terminal status reported to an external benchmark harness."""

    COMPLETED = "completed"
    HELD = "held"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BenchmarkTask:
    """One bounded unit of work supplied by a benchmark plugin."""

    run_id: str
    task_id: str
    stage: str
    objective: str
    target_ref: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_identifier("run_id", self.run_id)
        _validate_identifier("task_id", self.task_id)
        _validate_identifier("stage", self.stage)
        _validate_identifier("target_ref", self.target_ref)
        _validate_text("objective", self.objective)
        _validate_metadata(self.metadata)
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class BenchmarkSubmission:
    """FDAI result returned through the plugin that supplied the task."""

    run_id: str
    task_id: str
    stage: str
    status: BenchmarkStatus
    summary: str
    evidence_refs: tuple[str, ...] = ()
    audit_ref: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_identifier("run_id", self.run_id)
        _validate_identifier("task_id", self.task_id)
        _validate_identifier("stage", self.stage)
        _validate_text("summary", self.summary)
        if len(self.evidence_refs) > _MAX_EVIDENCE_REFS:
            raise ValueError(f"evidence_refs MUST contain at most {_MAX_EVIDENCE_REFS} entries")
        for evidence_ref in self.evidence_refs:
            _validate_identifier("evidence_ref", evidence_ref)
        if self.audit_ref is not None:
            _validate_identifier("audit_ref", self.audit_ref)
        _validate_metadata(self.metadata)
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


def _validate_identifier(name: str, value: str) -> None:
    if not value.strip() or len(value) > _MAX_ID_LENGTH or _has_control_character(value):
        raise ValueError(f"{name} MUST be a non-empty bounded identifier")


def _validate_text(name: str, value: str) -> None:
    if not value.strip() or len(value) > _MAX_TEXT_LENGTH or _has_control_character(value):
        raise ValueError(f"{name} MUST be non-empty bounded text")


def _validate_metadata(metadata: Mapping[str, str]) -> None:
    if len(metadata) > _MAX_METADATA_ENTRIES:
        raise ValueError(f"metadata MUST contain at most {_MAX_METADATA_ENTRIES} entries")
    for key, value in metadata.items():
        _validate_identifier("metadata key", key)
        if len(value) > _MAX_METADATA_VALUE_LENGTH or _has_control_character(value):
            raise ValueError("metadata values MUST be bounded text without control characters")


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 for character in value)


def _freeze_metadata(metadata: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(metadata))


__all__ = [
    "BenchmarkStatus",
    "BenchmarkSubmission",
    "BenchmarkTask",
]
