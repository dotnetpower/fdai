"""Generic GitHub artifact-state adapter for independent effect observation.

``pr_native``, ``pr_manual`` and the GitHub-backed ``tool_call`` ActionTypes
all produce the same class of effect: a durable artifact - a pull request or
an issue - exists at a known reference with a known state.  One reader
therefore serves three execution paths.

The adapter is read-only by construction: it issues ``GET`` only, and its
token is expected to be a read-scoped credential distinct from the GitOps
writer credential.  Independence is enforced above it by
``IndependentEffectObserver``, which refuses an observer identity equal to
the executor or source identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from fdai.core.executor.effect_observation import (
    IndependentEffectObservationBinding,
)
from fdai.core.executor.effect_observation_source import ObservedEffectState


class GitHubArtifactKind(StrEnum):
    """Which durable GitHub artifact an execution path produces."""

    PULL_REQUEST = "pull_request"
    ISSUE = "issue"


class GitHubArtifactReadError(RuntimeError):
    """The authoritative GitHub read failed or cannot be trusted."""


@dataclass(frozen=True, slots=True)
class GitHubArtifactReading:
    """One bounded read of a pull request or issue."""

    exists: bool
    state: str | None
    head_sha: str | None
    merged: bool | None
    auto_merge_enabled: bool
    labels: tuple[str, ...]
    observed_at: datetime
    recorded_at: datetime
    censoring_refs: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("observed_at", self.observed_at),
            ("recorded_at", self.recorded_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"GitHub artifact {name} MUST be timezone-aware")
        if not self.exists and self.state is not None:
            raise ValueError("a missing GitHub artifact MUST NOT report a state")


class GitHubArtifactReader(Protocol):
    """Read one GitHub artifact through a read-only identity."""

    async def read_artifact(
        self,
        *,
        owner: str,
        repo: str,
        kind: GitHubArtifactKind,
        number: int,
    ) -> GitHubArtifactReading:
        """Return one bounded reading or raise :class:`GitHubArtifactReadError`."""
        ...


@dataclass(frozen=True, slots=True)
class GitHubArtifactEffectSourceConfig:
    """Pin one observation source to exactly one expected artifact.

    ``require_manual_merge`` distinguishes ``pr_manual`` from ``pr_native``:
    a manual-merge path that produced an auto-merging pull request did not
    produce the effect its ActionType declared, so the reading reports the
    expected state as absent rather than present.
    """

    owner: str
    repo: str
    kind: GitHubArtifactKind
    number: int
    source_instance_id: str
    expected_head_sha: str | None = None
    require_manual_merge: bool = False
    required_label: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("owner", self.owner),
            ("repo", self.repo),
            ("source_instance_id", self.source_instance_id),
        ):
            if not value.strip():
                raise ValueError(f"GitHub effect source {name} MUST NOT be empty")
        if type(self.kind) is not GitHubArtifactKind:
            raise ValueError("GitHub effect source kind is invalid")
        if isinstance(self.number, bool) or self.number < 1:
            raise ValueError("GitHub effect source number MUST be positive")


class GitHubArtifactEffectSource:
    """Read one pinned GitHub artifact and describe it in quality terms."""

    def __init__(
        self,
        *,
        reader: GitHubArtifactReader,
        config: GitHubArtifactEffectSourceConfig,
    ) -> None:
        self._reader = reader
        self._config = config

    @property
    def source_instance_id(self) -> str:
        """Stable identity of the authoritative GitHub read path."""

        return self._config.source_instance_id

    async def read(
        self,
        *,
        binding: IndependentEffectObservationBinding,
    ) -> ObservedEffectState:
        """Return the pinned artifact's state as a provider-neutral reading."""

        del binding
        reading = await self._reader.read_artifact(
            owner=self._config.owner,
            repo=self._config.repo,
            kind=self._config.kind,
            number=self._config.number,
        )
        return _state_from(reading, config=self._config)


def _state_from(
    reading: GitHubArtifactReading,
    *,
    config: GitHubArtifactEffectSourceConfig,
) -> ObservedEffectState:
    """Translate one artifact reading without widening what it proved."""

    observed_at = reading.observed_at.astimezone(UTC)
    recorded_at = reading.recorded_at.astimezone(UTC)
    present, detail = _expected_state(reading, config)
    return ObservedEffectState(
        source_instance_id=config.source_instance_id,
        observed_at=observed_at,
        source_recorded_at=recorded_at,
        evidence_window_start=min(observed_at, recorded_at) - timedelta(seconds=1),
        evidence_window_end=max(observed_at, recorded_at),
        expected_state_present=present,
        complete=not reading.censoring_refs,
        final=True,
        contained=True,
        synthetic=False,
        conflicts=reading.conflicts,
        censoring_refs=reading.censoring_refs,
        detail=detail,
    )


def _expected_state(
    reading: GitHubArtifactReading,
    config: GitHubArtifactEffectSourceConfig,
) -> tuple[bool | None, str]:
    """Decide whether the declared artifact effect is present.

    Returns ``None`` only when the source genuinely could not decide.  A
    positively-absent artifact is a ``False`` - a failed effect - because the
    executor claimed to have created it.
    """

    if not reading.exists:
        return False, f"{config.kind.value} {config.number} does not exist"
    if reading.state is None:
        return None, f"{config.kind.value} {config.number} reported no state"
    if config.expected_head_sha is not None and reading.head_sha != config.expected_head_sha:
        return (
            False,
            f"{config.kind.value} {config.number} head does not match the dispatched revision",
        )
    if config.require_manual_merge and reading.auto_merge_enabled:
        return (
            False,
            f"pull request {config.number} enabled auto-merge on a manual-merge path",
        )
    if config.required_label is not None and config.required_label not in reading.labels:
        return (
            False,
            f"{config.kind.value} {config.number} is missing the {config.required_label} label",
        )
    return True, f"{config.kind.value} {config.number} is {reading.state}"


def reading_from_payload(
    payload: Mapping[str, Any],
    *,
    kind: GitHubArtifactKind,
    observed_at: datetime,
) -> GitHubArtifactReading:
    """Translate one GitHub REST body into a bounded reading.

    Kept separate from transport so an adapter that fetches over HTTP and a
    test that supplies a recorded body exercise identical parsing.
    """

    state = payload.get("state")
    if type(state) is not str or not state.strip():
        raise GitHubArtifactReadError("GitHub artifact response omitted its state")
    updated_raw = payload.get("updated_at")
    if type(updated_raw) is not str:
        raise GitHubArtifactReadError("GitHub artifact response omitted its update time")
    try:
        recorded_at = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GitHubArtifactReadError("GitHub artifact update time is not ISO 8601") from exc
    if recorded_at.tzinfo is None:
        raise GitHubArtifactReadError("GitHub artifact update time MUST include a timezone")
    head = payload.get("head")
    head_sha = head.get("sha") if isinstance(head, Mapping) else None
    merged = payload.get("merged")
    labels = payload.get("labels")
    label_names: tuple[str, ...] = ()
    if isinstance(labels, list):
        label_names = tuple(
            str(label.get("name"))
            for label in labels
            if isinstance(label, Mapping) and label.get("name") is not None
        )
    return GitHubArtifactReading(
        exists=True,
        state=state,
        head_sha=head_sha if type(head_sha) is str else None,
        merged=merged if type(merged) is bool else None,
        auto_merge_enabled=payload.get("auto_merge") is not None,
        labels=label_names,
        observed_at=observed_at.astimezone(UTC),
        recorded_at=recorded_at.astimezone(UTC),
    )


__all__ = [
    "GitHubArtifactEffectSource",
    "GitHubArtifactEffectSourceConfig",
    "GitHubArtifactKind",
    "GitHubArtifactReadError",
    "GitHubArtifactReader",
    "GitHubArtifactReading",
    "reading_from_payload",
]
