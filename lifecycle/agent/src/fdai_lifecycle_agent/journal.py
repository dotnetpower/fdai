"""Durable apply journal: the rollback target and the phase of the Plan being applied.

``<state-dir>/lifecycle-agent-workload.json`` holds the last verified-healthy rendering and at
most one journal. The journal is written before the apply-started report, moves to ``applying``
before the first cluster write, and its ``done`` write commits the outcome and the new state
snapshot. A restarted agent therefore never applies a Plan twice: a ``prepared`` journal hasn't
touched the cluster, an ``applying`` one is rolled back, and a ``done`` one only finishes its
reports.

``<state-dir>/lifecycle-agent-halt.json`` exists after a failed rollback. While it exists the agent
applies nothing. An operator removes it after repairing the namespace.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from fdai_lifecycle_agent.adoption import AdoptionExpectation
from fdai_lifecycle_agent.state import (
    AgentStateError,
    PlanResult,
    parse_plan_result,
    write_json_atomically,
)
from fdai_lifecycle_agent.strict_json import load_json, read_limited
from fdai_lifecycle_agent.workload import Manifest

WORKLOAD_SCHEMA = "fdai.lifecycle-agent-workload.v1"
HALT_SCHEMA = "fdai.lifecycle-agent-halt.v1"
WORKLOAD_FILE_NAME = "lifecycle-agent-workload.json"
HALT_FILE_NAME = "lifecycle-agent-halt.json"
_MAX_BYTES = 4 * 1024 * 1024
_JOURNAL_KEYS_V1 = frozenset(
    {
        "plan_id",
        "phase",
        "expires_at",
        "target_release_id",
        "entity_images",
        "desired",
        "previous",
        "result",
        "snapshot",
    }
)
_JOURNAL_KEYS = _JOURNAL_KEYS_V1 | {"adoptions"}

type Phase = Literal["prepared", "applying", "done"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplyJournal:
    """One Plan's apply. ``previous`` holds the healthy version of each desired object that
    existed; a desired object without one is deleted on rollback."""

    plan_id: str
    phase: Phase
    expires_at: datetime
    target_release_id: str
    entity_images: Mapping[str, frozenset[str]]
    desired: tuple[Manifest, ...]
    previous: tuple[Manifest, ...]
    result: PlanResult | None = None
    snapshot: Mapping[str, object] | None = None
    adoptions: tuple[AdoptionExpectation, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkloadState:
    healthy: tuple[Manifest, ...] = ()
    journal: ApplyJournal | None = None


class WorkloadStore:
    """The workload file and the halt marker inside the agent state directory."""

    def __init__(self, state_dir: Path) -> None:
        self._path = state_dir / WORKLOAD_FILE_NAME
        self._halt_path = state_dir / HALT_FILE_NAME

    def load(self) -> WorkloadState:
        document = self._read(self._path, "workload state")
        if document is None:
            return WorkloadState()
        try:
            return _parse_workload(document)
        except (KeyError, TypeError, ValueError) as error:
            raise AgentStateError("workload state is invalid") from error

    def save(self, state: WorkloadState) -> None:
        journal = state.journal
        document = {
            "schema": WORKLOAD_SCHEMA,
            "healthy": list(state.healthy),
            "journal": None if journal is None else _journal_document(journal),
        }
        self._write(self._path, document, "workload state")

    def require_private(self) -> None:
        """V2 rendering may persist private reference names, never into a public directory."""
        from fdai_deployment_cli.private_output import read_private_bytes

        from fdai_lifecycle_agent.workload import WorkloadError

        try:
            # The helper validates every ancestor and the held private parent even when the
            # first journal file does not exist yet.
            read_private_bytes(self._path.absolute(), max_bytes=_MAX_BYTES)
        except FileNotFoundError:
            if not self._path.parent.is_dir():
                raise WorkloadError(
                    "configuration_private_state_unavailable", retryable=True
                ) from None
        except (OSError, ValueError):
            raise WorkloadError("configuration_private_state_unavailable", retryable=True) from None

    def halted_plan_id(self) -> str | None:
        """Return the Plan whose rollback failed, or ``None``. A bad marker still halts."""

        document = self._read(self._halt_path, "halt marker")
        match document:
            case None:
                return None
            case {"schema": schema, "plan_id": str(plan_id)} if schema == HALT_SCHEMA:
                return plan_id
        raise AgentStateError("halt marker is invalid; repair the namespace and remove it")

    def halt(self, plan_id: str) -> None:
        self._write(self._halt_path, {"schema": HALT_SCHEMA, "plan_id": plan_id}, "halt marker")

    @staticmethod
    def _read(path: Path, label: str) -> object:
        try:
            raw = read_limited(path, limit=_MAX_BYTES, label=label)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise AgentStateError(f"{label} is unreadable: {type(error).__name__}") from error
        try:
            return load_json(raw, label=label)
        except ValueError as error:
            raise AgentStateError(f"{label} is invalid") from error

    @staticmethod
    def _write(path: Path, document: object, label: str) -> None:
        try:
            write_json_atomically(path, document)
        except OSError as error:
            raise AgentStateError(f"{label} is not writable: {type(error).__name__}") from error


def _journal_document(journal: ApplyJournal) -> dict[str, object]:
    return {
        "plan_id": journal.plan_id,
        "phase": journal.phase,
        "expires_at": journal.expires_at.isoformat(),
        "target_release_id": journal.target_release_id,
        "entity_images": {
            entity_id: sorted(images) for entity_id, images in journal.entity_images.items()
        },
        "desired": list(journal.desired),
        "previous": list(journal.previous),
        "result": None if journal.result is None else asdict(journal.result),
        "snapshot": journal.snapshot,
        "adoptions": [asdict(item) for item in journal.adoptions],
    }


def _parse_workload(document: object) -> WorkloadState:
    if not isinstance(document, dict) or set(document) != {"schema", "healthy", "journal"}:
        raise ValueError("workload state fields are invalid")
    match document:
        case {"schema": schema, "healthy": list(healthy), "journal": journal} if (
            schema == WORKLOAD_SCHEMA
        ):
            return WorkloadState(
                healthy=_manifests(healthy),
                journal=None if journal is None else _parse_journal(journal),
            )
    raise ValueError("workload state fields are invalid")


def _parse_journal(document: object) -> ApplyJournal:
    if not isinstance(document, dict):
        raise ValueError("apply journal fields are invalid")
    keys = frozenset(document)
    if keys not in {_JOURNAL_KEYS_V1, _JOURNAL_KEYS}:
        raise ValueError("apply journal fields are invalid")
    normalized = document | {"adoptions": document.get("adoptions", [])}
    match normalized:
        case {
            "plan_id": str(plan_id),
            "phase": "prepared" | "applying" | "done" as phase,
            "expires_at": str(expires_at),
            "target_release_id": str(target_release_id),
            "entity_images": dict(entity_images),
            "desired": list(desired),
            "previous": list(previous),
            "result": result,
            "snapshot": dict() | None as snapshot,
            "adoptions": list(adoptions),
        }:
            expires = datetime.fromisoformat(expires_at)
            if expires.utcoffset() is None:
                raise ValueError("apply journal expires_at MUST include timezone information")
            return ApplyJournal(
                plan_id=plan_id,
                phase=phase,
                expires_at=expires,
                target_release_id=target_release_id,
                entity_images={
                    str(entity_id): frozenset(_strings(images))
                    for entity_id, images in entity_images.items()
                },
                desired=_manifests(desired),
                previous=_manifests(previous),
                result=None if result is None else parse_plan_result(result),
                snapshot=snapshot,
                adoptions=_adoptions(adoptions),
            )
    raise ValueError("apply journal values are invalid")


def _manifests(items: list[object]) -> tuple[Manifest, ...]:
    # Shape only; the scope guard checks every manifest again before any cluster call.
    manifests = tuple(item for item in items if isinstance(item, dict))
    if len(manifests) != len(items):
        raise ValueError("manifests MUST be objects")
    return manifests


def _strings(items: object) -> list[str]:
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ValueError("expected a list of strings")
    return items


def _adoptions(items: list[object]) -> tuple[AdoptionExpectation, ...]:
    if not all(
        isinstance(item, dict) and set(item) == {"kind", "name", "uid", "resource_version"}
        for item in items
    ):
        raise ValueError("journal adoptions are invalid")
    documents = cast(list[dict[str, object]], items)
    return tuple(
        AdoptionExpectation(
            kind=str(item["kind"]),
            name=str(item["name"]),
            uid=str(item["uid"]),
            resource_version=str(item["resource_version"]),
        )
        for item in documents
    )
