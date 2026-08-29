"""Hash-chained local run journal and legal resume decisions."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.compiler import (
    GENESIS_ENTRY_IDS_BY_VERSION,
    GENESIS_MANIFEST_VERSION,
)

GENESIS_HASH = "0" * 64
_LEGACY_EVENT_MANIFEST_VERSION = "genesis.v1"
_MAX_JOURNAL_BYTES = 8 * 1024 * 1024
_MAX_EVENTS = 10_000
_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_RETRY_SECONDS = 0.05
_ID = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")


class RunState(StrEnum):
    """Terminal and nonterminal provisioning run states."""

    PLANNING = "planning"
    WAITING = "waiting"
    APPLYING = "applying"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    READY = "ready"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"


class ResumeAction(StrEnum):
    """Only safe continuations after an interrupted stage."""

    REPLAN = "replan"
    RESUME_VERIFICATION = "resume-verification"
    COMPLETE = "complete"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class ProvisionEvent:
    """One append-only, replayable local run event."""

    run_id: str
    context_digest: str
    sequence: int
    stage: str
    attempt: int
    state: RunState
    occurred_at: str
    previous_digest: str
    reason_code: str | None = None
    manifest_version: str = GENESIS_MANIFEST_VERSION
    schema_version: str = "fdai.provision-event.v2"

    def __post_init__(self) -> None:
        if _ID.fullmatch(self.run_id) is None or _ID.fullmatch(self.stage) is None:
            raise ValueError("run_id and stage MUST be stable identifiers")
        if re.fullmatch(r"[0-9a-f]{64}", self.context_digest) is None:
            raise ValueError("event context_digest MUST be a SHA-256")
        if self.sequence < 1 or self.attempt < 1:
            raise ValueError("event sequence and attempt MUST be positive")
        try:
            moment = datetime.fromisoformat(self.occurred_at)
        except ValueError as exc:
            raise ValueError("event occurred_at MUST be ISO 8601") from exc
        if moment.tzinfo is None:
            raise ValueError("event occurred_at MUST be timezone-aware")
        if re.fullmatch(r"[0-9a-f]{64}", self.previous_digest) is None:
            raise ValueError("event previous_digest MUST be a SHA-256")
        if self.reason_code is not None and _ID.fullmatch(self.reason_code) is None:
            raise ValueError("event reason_code MUST be a stable identifier")
        if self.manifest_version not in GENESIS_ENTRY_IDS_BY_VERSION:
            raise ValueError("event manifest_version is unsupported")
        if self.schema_version not in {"fdai.provision-event.v1", "fdai.provision-event.v2"}:
            raise ValueError("event schema_version is unsupported")

    @property
    def digest(self) -> str:
        """Return the event hash-chain digest."""

        return canonical_digest(self._body_mapping())

    def to_mapping(self) -> dict[str, object]:
        """Return canonical event data."""

        return {**self._body_mapping(), "event_digest": self.digest}

    def _body_mapping(self) -> dict[str, object]:
        body: dict[str, object] = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "context_digest": self.context_digest,
            "sequence": self.sequence,
            "stage": self.stage,
            "attempt": self.attempt,
            "state": self.state.value,
            "occurred_at": self.occurred_at,
            "previous_digest": self.previous_digest,
            "reason_code": self.reason_code,
        }
        if self.schema_version == "fdai.provision-event.v2":
            body["manifest_version"] = self.manifest_version
        return body

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> ProvisionEvent:
        """Decode one strict journal event."""

        common = {
            "schema_version",
            "run_id",
            "context_digest",
            "sequence",
            "stage",
            "attempt",
            "state",
            "occurred_at",
            "previous_digest",
            "reason_code",
            "event_digest",
        }
        schema_version = value.get("schema_version")
        if schema_version == "fdai.provision-event.v1":
            expected = common
            manifest_version = _LEGACY_EVENT_MANIFEST_VERSION
        elif schema_version == "fdai.provision-event.v2":
            expected = common | {"manifest_version"}
            manifest_version = _required_text(value, "manifest_version")
        else:
            raise ValueError("provision event schema does not match")
        if set(value) != expected:
            raise ValueError("provision event schema does not match")
        reason = value["reason_code"]
        if reason is not None and not isinstance(reason, str):
            raise ValueError("event reason_code MUST be a string or null")
        event = cls(
            run_id=_required_text(value, "run_id"),
            context_digest=_required_text(value, "context_digest"),
            sequence=_required_int(value, "sequence"),
            stage=_required_text(value, "stage"),
            attempt=_required_int(value, "attempt"),
            state=RunState(_required_text(value, "state")),
            occurred_at=_required_text(value, "occurred_at"),
            previous_digest=_required_text(value, "previous_digest"),
            reason_code=reason,
            manifest_version=manifest_version,
            schema_version=schema_version,
        )
        if value["event_digest"] != event.digest:
            raise ValueError("provision event digest does not match")
        return event


def append_event(path: Path, event: ProvisionEvent) -> None:
    """Append and fsync one event after checking sequence and hash continuity."""

    directory = _open_journal_directory(path, create=True)
    try:
        descriptor = os.open(
            path.name,
            os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
    finally:
        os.close(directory)
    with os.fdopen(descriptor, "a+b") as stream:
        _validate_journal_descriptor(stream.fileno())
        _acquire_exclusive_lock(stream.fileno())
        details = _validate_journal_descriptor(stream.fileno())
        events = _read_stream(stream)
        previous = events[-1] if events else None
        expected_sequence = 1 if previous is None else previous.sequence + 1
        expected_digest = GENESIS_HASH if previous is None else previous.digest
        if event.sequence != expected_sequence or event.previous_digest != expected_digest:
            raise ValueError("provision event does not continue the journal")
        if previous is not None and event.run_id != previous.run_id:
            raise ValueError("provision event run_id does not match the journal")
        if previous is not None and event.context_digest != previous.context_digest:
            raise ValueError("provision event context does not match the journal")
        if previous is not None and event.manifest_version != previous.manifest_version:
            raise ValueError("provision event manifest version does not match the journal")
        _validate_ready_history(events, event)
        _validate_transition(previous, event)
        payload = json.dumps(
            event.to_mapping(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
        if details.st_size + len(payload) + 1 > _MAX_JOURNAL_BYTES:
            raise ValueError("provision journal append exceeds its size limit")
        stream.seek(0, os.SEEK_END)
        stream.write(payload + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _acquire_exclusive_lock(
    descriptor: int, *, timeout_seconds: float = _LOCK_TIMEOUT_SECONDS
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("provision journal lock timed out") from exc
            time.sleep(min(_LOCK_RETRY_SECONDS, remaining))


def _validate_journal_descriptor(descriptor: int) -> os.stat_result:
    details = os.fstat(descriptor)
    if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o600:
        raise PermissionError("provision journal MUST be a mode-0600 regular file")
    if details.st_size > _MAX_JOURNAL_BYTES:
        raise ValueError("provision journal exceeds its size limit")
    return details


def read_journal(path: Path) -> tuple[ProvisionEvent, ...]:
    """Read and verify a complete local journal."""

    directory = _open_journal_directory(path, create=False)
    try:
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
    finally:
        os.close(directory)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o600:
            raise PermissionError("provision journal MUST be a mode-0600 regular file")
        if details.st_size > _MAX_JOURNAL_BYTES:
            raise ValueError("provision journal exceeds its size limit")
        return _read_stream(stream)


def _open_journal_directory(path: Path, *, create: bool) -> int:
    if path.name in {"", ".", ".."}:
        raise ValueError("provision journal filename is invalid")
    parent = path.parent
    descriptor = os.open(
        parent.anchor or ".",
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    parts = parent.parts[1:] if parent.anchor else parent.parts
    try:
        for part in parts:
            if part in {"", "."}:
                continue
            if part == "..":
                raise ValueError("provision journal path MUST NOT traverse parent directories")
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        details = os.fstat(descriptor)
        if details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) != 0o700:
            raise PermissionError("provision journal directory MUST be current-UID mode 0700")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def resume_action(*, claim: str, receipt: str, failed: bool) -> ResumeAction:
    """Return the only legal continuation for an apply claim state."""

    if claim not in {"absent", "present"} or receipt not in {"absent", "present"}:
        raise ValueError("claim and receipt states are unsupported")
    if receipt == "present" and claim != "present":
        raise ValueError("an apply receipt without a claim is invalid")
    if failed and receipt == "present":
        raise ValueError("a completed apply receipt cannot also be failed")
    if failed:
        return ResumeAction.REVIEW
    if receipt == "present":
        return ResumeAction.COMPLETE
    if claim == "present":
        return ResumeAction.RESUME_VERIFICATION
    return ResumeAction.REPLAN


def _validate_transition(
    previous: ProvisionEvent | None,
    current: ProvisionEvent,
) -> None:
    if previous is not None and previous.state in {
        RunState.READY,
        RunState.BLOCKED,
        RunState.FAILED,
        RunState.CANCELLED,
        RunState.INCOMPLETE,
    }:
        raise ValueError("terminal provision state cannot advance")
    if current.state is RunState.READY and (
        previous is None
        or previous.state is not RunState.COMPLETED
        or previous.stage != "system-readiness"
        or current.stage != "system-readiness"
    ):
        raise ValueError("ready requires completed system-readiness evidence")


def _validate_ready_history(
    events: tuple[ProvisionEvent, ...] | list[ProvisionEvent],
    current: ProvisionEvent,
) -> None:
    if current.state is not RunState.READY:
        return
    completed = tuple(event.stage for event in events if event.state is RunState.COMPLETED)
    expected = GENESIS_ENTRY_IDS_BY_VERSION[current.manifest_version]
    if completed != expected:
        raise ValueError("ready requires every manifest entry completed in order")


def _read_stream(stream: BinaryIO) -> tuple[ProvisionEvent, ...]:
    stream.seek(0)
    events: list[ProvisionEvent] = []
    previous_digest = GENESIS_HASH
    previous: ProvisionEvent | None = None
    run_id: str | None = None
    context_digest: str | None = None
    manifest_version: str | None = None
    for sequence, line in enumerate(stream, start=1):
        if sequence > _MAX_EVENTS:
            raise ValueError("provision journal exceeds its event count limit")
        event = ProvisionEvent.from_mapping(
            load_json_object(line, label="provision journal event", max_bytes=64 * 1024)
        )
        if event.sequence != sequence or event.previous_digest != previous_digest:
            raise ValueError("provision journal hash chain is invalid")
        if run_id is not None and event.run_id != run_id:
            raise ValueError("provision journal contains multiple run ids")
        if context_digest is not None and event.context_digest != context_digest:
            raise ValueError("provision journal contains multiple contexts")
        if manifest_version is not None and event.manifest_version != manifest_version:
            raise ValueError("provision journal contains multiple manifest versions")
        _validate_ready_history(events, event)
        _validate_transition(previous, event)
        run_id = event.run_id
        context_digest = event.context_digest
        manifest_version = event.manifest_version
        previous_digest = event.digest
        previous = event
        events.append(event)
    return tuple(events)


def _required_text(value: dict[str, object], field: str) -> str:
    item = value[field]
    if not isinstance(item, str):
        raise ValueError(f"event {field} MUST be a string")
    return item


def _required_int(value: dict[str, object], field: str) -> int:
    item = value[field]
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"event {field} MUST be an integer")
    return item
