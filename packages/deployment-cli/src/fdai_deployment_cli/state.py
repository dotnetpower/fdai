"""Hash-chained local run journal and legal resume decisions."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO

from fdai_deployment_cli.contracts import canonical_digest, load_json_object

GENESIS_HASH = "0" * 64
_MAX_JOURNAL_BYTES = 8 * 1024 * 1024
_MAX_EVENTS = 10_000
_ID = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")


class RunState(StrEnum):
    """Terminal and nonterminal provisioning run states."""

    PLANNING = "planning"
    WAITING = "waiting"
    APPLYING = "applying"
    VERIFYING = "verifying"
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
    sequence: int
    stage: str
    attempt: int
    state: RunState
    occurred_at: str
    previous_digest: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if _ID.fullmatch(self.run_id) is None or _ID.fullmatch(self.stage) is None:
            raise ValueError("run_id and stage MUST be stable identifiers")
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

    @property
    def digest(self) -> str:
        """Return the event hash-chain digest."""

        return canonical_digest(self._body_mapping())

    def to_mapping(self) -> dict[str, object]:
        """Return canonical event data."""

        return {**self._body_mapping(), "event_digest": self.digest}

    def _body_mapping(self) -> dict[str, object]:
        return {
            "schema_version": "fdai.provision-event.v1",
            "run_id": self.run_id,
            "sequence": self.sequence,
            "stage": self.stage,
            "attempt": self.attempt,
            "state": self.state.value,
            "occurred_at": self.occurred_at,
            "previous_digest": self.previous_digest,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> ProvisionEvent:
        """Decode one strict journal event."""

        expected = {
            "schema_version",
            "run_id",
            "sequence",
            "stage",
            "attempt",
            "state",
            "occurred_at",
            "previous_digest",
            "reason_code",
            "event_digest",
        }
        if set(value) != expected or value["schema_version"] != "fdai.provision-event.v1":
            raise ValueError("provision event schema does not match")
        reason = value["reason_code"]
        if reason is not None and not isinstance(reason, str):
            raise ValueError("event reason_code MUST be a string or null")
        event = cls(
            run_id=_required_text(value, "run_id"),
            sequence=_required_int(value, "sequence"),
            stage=_required_text(value, "stage"),
            attempt=_required_int(value, "attempt"),
            state=RunState(_required_text(value, "state")),
            occurred_at=_required_text(value, "occurred_at"),
            previous_digest=_required_text(value, "previous_digest"),
            reason_code=reason,
        )
        if value["event_digest"] != event.digest:
            raise ValueError("provision event digest does not match")
        return event


def append_event(path: Path, event: ProvisionEvent) -> None:
    """Append and fsync one event after checking sequence and hash continuity."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
        raise PermissionError("provision journal directory MUST have mode 0700")
    descriptor = os.open(
        path,
        os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(descriptor, "a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o600:
            raise PermissionError("provision journal MUST be a mode-0600 regular file")
        if details.st_size > _MAX_JOURNAL_BYTES:
            raise ValueError("provision journal exceeds its size limit")
        events = _read_stream(stream)
        previous = events[-1] if events else None
        expected_sequence = 1 if previous is None else previous.sequence + 1
        expected_digest = GENESIS_HASH if previous is None else previous.digest
        if event.sequence != expected_sequence or event.previous_digest != expected_digest:
            raise ValueError("provision event does not continue the journal")
        if previous is not None and event.run_id != previous.run_id:
            raise ValueError("provision event run_id does not match the journal")
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


def read_journal(path: Path) -> tuple[ProvisionEvent, ...]:
    """Read and verify a complete local journal."""

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o600:
            raise PermissionError("provision journal MUST be a mode-0600 regular file")
        if details.st_size > _MAX_JOURNAL_BYTES:
            raise ValueError("provision journal exceeds its size limit")
        return _read_stream(stream)


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


def _read_stream(stream: BinaryIO) -> tuple[ProvisionEvent, ...]:
    stream.seek(0)
    events: list[ProvisionEvent] = []
    previous_digest = GENESIS_HASH
    run_id: str | None = None
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
        run_id = event.run_id
        previous_digest = event.digest
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
