"""Private, exclusive diagnostic evidence; never quality or activation authority."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Literal

from pydantic import TypeAdapter
from pydantic_core import PydanticSerializationError

_Event = Literal[
    "started",
    "embedding_call_intent",
    "embedding_result",
    "stage",
    "completed",
    "aborted",
    "cancelled",
]
_MAX_RECORD_BYTES = 4 * 1024 * 1024
_MAX_FILE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _Record:
    schema_version: Literal["1.0.0"]
    sequence: int
    event: _Event
    recorded_at: datetime
    payload: dict[str, object]
    source_commit: str | None
    production_qualification: Literal[False] = False
    execution_authority: Literal[False] = False


_RECORD = TypeAdapter(_Record)


class OntologyEvaluationEvidenceError(RuntimeError):
    """An unavailable evidence sink must stop the attempt, not discard its results."""


class OntologyEvaluationEvidence:
    """Append flushed JSON-mode records to a new caller-owned local file with mode 0600.

    Use as a context manager around one execution. Existing files and symlink destinations
    are rejected, never resumed or replaced. Each complete line is independently readable;
    an interrupted tail or absence of a terminal record is not a successful execution.
    The caller owns the private local parent directory, isolation and later cleanup.
    """

    def __init__(
        self, path: Path, *, source_commit: str | None = None, retain_vectors: bool = False
    ) -> None:
        if source_commit is not None and re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
            raise ValueError("ontology evidence source commit must be a full lowercase Git SHA")
        if retain_vectors and source_commit is None:
            raise ValueError("ontology vector retention requires a source commit")
        self._path = path
        self._source_commit = source_commit
        self._descriptor: int | None = None
        self._sequence = 0
        self._bytes = 0
        self._failed = False
        self._entered = False
        self._terminal = False
        self._retain_vectors = retain_vectors

    @property
    def retain_vectors(self) -> bool:
        """Explicit opt-in to private vector retention, without retaining source text."""
        return self._retain_vectors

    def __enter__(self) -> OntologyEvaluationEvidence:
        if self._entered:
            raise OntologyEvaluationEvidenceError("ontology evidence writer cannot be reused")
        self._entered = True
        try:
            parent = os.open(self._path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                self._descriptor = os.open(
                    self._path.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent,
                )
                os.fsync(parent)
            finally:
                os.close(parent)
        except OSError:
            if self._descriptor is not None:
                os.close(self._descriptor)
                self._descriptor = None
            raise OntologyEvaluationEvidenceError(
                "ontology evidence requires a new writable private local file"
            ) from None
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._descriptor is not None:
            descriptor, self._descriptor = self._descriptor, None
            os.close(descriptor)

    def record(self, event: _Event, payload: dict[str, object]) -> None:
        """Serialize before writing and fsync before permitting the next provider call.

        A failed or partial write poisons this writer. Earlier complete lines are retained;
        no best-effort append, retry, truncation, raw provider error or success fallback follows.
        """
        if self._descriptor is None or self._failed or self._terminal:
            raise OntologyEvaluationEvidenceError("ontology evidence writer is unavailable")
        try:
            if (event == "started") != (self._sequence == 0):
                raise ValueError("ontology evidence must start exactly once")
            if event == "embedding_result" and not self._retain_vectors:
                raise ValueError("ontology vector retention was not selected")
            encoded = (
                _RECORD.dump_json(
                    _Record(
                        "1.0.0",
                        self._sequence,
                        event,
                        datetime.now(UTC),
                        payload,
                        self._source_commit,
                    ),
                    warnings="error",
                )
                + b"\n"
            )
            if (
                len(encoded) > _MAX_RECORD_BYTES
                or self._bytes + len(encoded) > _MAX_FILE_BYTES
                or self._sequence >= (262 if self._retain_vectors else 134)
            ):
                raise ValueError("ontology evidence exceeds its bounded capacity")
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(self._descriptor, remaining)
                if written <= 0:
                    raise OSError("ontology evidence write made no progress")
                remaining = remaining[written:]
            os.fsync(self._descriptor)
        except (OSError, ValueError, PydanticSerializationError):
            self._failed = True
            raise OntologyEvaluationEvidenceError(
                "ontology evidence record could not be retained"
            ) from None
        self._bytes += len(encoded)
        self._sequence += 1
        self._terminal = event in ("completed", "aborted", "cancelled")


__all__ = ["OntologyEvaluationEvidence", "OntologyEvaluationEvidenceError"]
