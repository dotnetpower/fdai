"""Durable local agent state: replay floor, rejected sequences, and per-Plan report records.

The file is written atomically (temporary file, ``fsync``, ``os.replace``, directory ``fsync``)
with owner-only permissions. One poll at a time holds an exclusive ``flock`` on the state
directory, so concurrent polls can't roll the replay floor back. A corrupt or unknown file fails
closed; the agent never silently resets its replay floor.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import cast, get_args

from fdai_lifecycle_agent.hub_client import ReportOutcome
from fdai_lifecycle_agent.strict_json import load_json, read_limited

STATE_SCHEMA = "fdai.lifecycle-agent-state.v1"
STATE_FILE_NAME = "lifecycle-agent-state.json"
LOCK_FILE_NAME = ".lifecycle-agent.lock"
MAX_PLAN_RECORDS = 256
_MAX_STATE_BYTES = 4 * 1024 * 1024
_STATE_KEYS = frozenset({"schema", "last_accepted_sequence", "rejected_sequences", "plans"})
_RECORD_KEYS = frozenset(
    {"sequence", "payload_digest", "result", "attempts", "reported_at", "reported"}
)
_RESULT_KEYS = frozenset({"outcome", "reason_code", "exact_plan_digest", "summary", "retryable"})
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_PLAN_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,95}\Z", re.ASCII)
_MAX_SUMMARY_CHARACTERS = 2000


class AgentStateError(RuntimeError):
    """Local state is locked, unreadable, or invalid; the agent stops instead of resetting it."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanResult:
    """What the agent concluded about one Plan; equal results are never reported twice.

    A ``retryable`` result never blocks its sequence and is evaluated again on the next poll. It
    covers inputs that may appear later and bytes that no configured Hub key signed.
    """

    outcome: ReportOutcome
    reason_code: str
    exact_plan_digest: str | None = None
    summary: str = ""
    retryable: bool = False

    @property
    def admitted(self) -> bool:
        return self.outcome != "rejected"


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanRecord:
    """One Plan's result and its report delivery progress.

    ``attempts`` is the number of the latest report and only ever grows. ``reported_at`` is set
    while that report is pending, so a retry resends the identical report under the same attempt
    and the Hub treats it as a duplicate. ``None`` means the next delivery starts a new attempt.
    """

    sequence: int
    payload_digest: str
    result: PlanResult
    attempts: int = 0
    reported_at: datetime | None = None
    reported: bool = False


@dataclass(frozen=True, slots=True)
class AgentState:
    """``last_accepted_sequence`` starts at -1 so that sequence 0 is admissible."""

    last_accepted_sequence: int = -1
    rejected_sequences: frozenset[int] = frozenset()
    plans: Mapping[str, PlanRecord] = field(default_factory=dict)

    def with_result(self, plan_id: str, record: PlanRecord) -> AgentState:
        """Store a new result and apply its replay rule: an admission raises the floor, a final
        rejection blocks its sequence, and a retryable result changes neither."""

        state = self
        if record.result.admitted:
            state = replace(state, last_accepted_sequence=record.sequence)
        elif not record.result.retryable:
            state = replace(state, rejected_sequences=state.rejected_sequences | {record.sequence})
        return state.with_record(plan_id, record)

    def with_record(self, plan_id: str, record: PlanRecord) -> AgentState:
        """Store a record. Over the bound, retryable records go first, then the oldest, so
        unauthenticated bytes can't evict a final result."""

        plans = {**self.plans, plan_id: record}
        if len(plans) > MAX_PLAN_RECORDS:
            ranked = sorted(
                plans.items(), key=lambda item: (not item[1].result.retryable, item[1].sequence)
            )
            plans = dict(ranked[-MAX_PLAN_RECORDS:])
        return replace(self, plans=plans)


class LocalStateStore:
    """One JSON state file inside an owner-only state directory."""

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir
        self._path = state_dir / STATE_FILE_NAME

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Hold the exclusive state lock for one poll, or raise ``AgentStateError`` at once."""

        try:
            self._state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(self._state_dir / LOCK_FILE_NAME, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as error:
            raise AgentStateError(
                f"agent state lock is unavailable: {type(error).__name__}"
            ) from error
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise AgentStateError("another poll holds the agent state lock") from error
            yield
        finally:
            os.close(descriptor)

    def load(self) -> AgentState:
        try:
            raw = read_limited(self._path, limit=_MAX_STATE_BYTES, label="agent state")
        except FileNotFoundError:
            return AgentState()
        except OSError as error:
            raise AgentStateError(f"agent state is unreadable: {type(error).__name__}") from error
        try:
            state, migrated = _parse_state(load_json(raw, label="agent state"))
        except (TypeError, ValueError) as error:
            raise AgentStateError("agent state is invalid") from error
        if migrated:
            self.save(state)
        return state

    def save(self, state: AgentState) -> None:
        try:
            _validate_state(state)
            write_json_atomically(self._path, _state_document(state))
        except ValueError as error:
            raise AgentStateError("agent state is invalid") from error
        except OSError as error:
            raise AgentStateError(f"agent state is not writable: {type(error).__name__}") from error


def write_json_atomically(path: Path, document: object) -> None:
    """Write ``document`` as owner-only JSON that a crash can't leave half-written."""
    write_bytes_atomically(path, json.dumps(document, sort_keys=True, indent=2).encode() + b"\n")


def write_bytes_atomically(path: Path, data: bytes) -> None:
    """Publish exact bytes with file and directory fsync and owner-only permissions."""
    directory = path.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    directory_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _state_document(state: AgentState) -> dict[str, object]:
    return {
        "schema": STATE_SCHEMA,
        "last_accepted_sequence": state.last_accepted_sequence,
        "rejected_sequences": sorted(state.rejected_sequences),
        "plans": {
            plan_id: _record_document(record) for plan_id, record in sorted(state.plans.items())
        },
    }


def _record_document(record: PlanRecord) -> dict[str, object]:
    reported_at = None if record.reported_at is None else record.reported_at.isoformat()
    return asdict(record) | {"reported_at": reported_at}


def _parse_state(document: object) -> tuple[AgentState, bool]:
    if not isinstance(document, dict) or set(document) != _STATE_KEYS:
        raise ValueError("agent state fields are invalid")
    match document:
        case {"schema": schema, "rejected_sequences": list(rejected), "plans": dict(plans)} if (
            schema == STATE_SCHEMA
        ):
            if len(plans) > MAX_PLAN_RECORDS:
                raise ValueError("agent state retains too many Plan records")
            state = AgentState(
                last_accepted_sequence=_integer(document["last_accepted_sequence"], minimum=-1),
                rejected_sequences=frozenset(_integer(item, minimum=0) for item in rejected),
                plans={str(plan_id): _parse_record(record) for plan_id, record in plans.items()},
            )
            state, migrated = _migrate_legacy_expiry_tombstones(state)
            _validate_state(state)
            return state, migrated
    raise ValueError("agent state schema is unsupported")


def _migrate_legacy_expiry_tombstones(state: AgentState) -> tuple[AgentState, bool]:
    """Repair only v1 final expiry records that previously advanced the replay floor."""

    missing = {
        record.sequence
        for record in state.plans.values()
        if not record.result.admitted
        and not record.result.retryable
        and record.sequence not in state.rejected_sequences
    }
    if not missing:
        return state, False
    legacy_expiries = {
        record.sequence
        for record in state.plans.values()
        if record.sequence in missing
        and record.result.outcome == "rejected"
        and record.result.reason_code == "plan_expired"
        and record.sequence <= state.last_accepted_sequence
    }
    if missing != legacy_expiries:
        return state, False
    return (
        replace(state, rejected_sequences=state.rejected_sequences | legacy_expiries),
        True,
    )


def _parse_record(record: object) -> PlanRecord:
    if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
        raise ValueError("plan record fields are invalid")
    match record:
        case {
            "payload_digest": str(payload_digest),
            "reported": bool(reported),
            "reported_at": str() | None as reported_at,
            "result": result,
        }:
            parsed = PlanRecord(
                sequence=_integer(record["sequence"], minimum=0),
                payload_digest=payload_digest,
                result=parse_plan_result(result),
                attempts=_integer(record["attempts"], minimum=0),
                reported_at=None if reported_at is None else _aware(reported_at),
                reported=reported,
            )
            _validate_record(parsed)
            return parsed
    raise ValueError("plan record values are invalid")


def parse_plan_result(result: object) -> PlanResult:
    if not isinstance(result, dict) or set(result) != _RESULT_KEYS:
        raise ValueError("plan result fields are invalid")
    match result:
        case {
            "outcome": str(outcome),
            "reason_code": str(reason_code),
            "exact_plan_digest": str() | None as digest,
            "summary": str(summary),
            "retryable": bool(retryable),
        } if outcome in get_args(ReportOutcome.__value__):
            parsed = PlanResult(
                outcome=cast(ReportOutcome, outcome),
                reason_code=reason_code,
                exact_plan_digest=digest,
                summary=summary,
                retryable=retryable,
            )
            _validate_result(parsed)
            return parsed
    raise ValueError("plan result values are invalid")


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("agent state timestamp MUST include timezone information")
    return parsed


def _integer(value: object, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError("agent state integer is invalid")
    return value


def _validate_state(state: AgentState) -> None:
    if len(state.plans) > MAX_PLAN_RECORDS:
        raise ValueError("agent state retains too many Plan records")
    admitted = [record.sequence for record in state.plans.values() if record.result.admitted]
    if admitted and max(admitted) > state.last_accepted_sequence:
        raise ValueError("agent state replay floor is below an admitted Plan")
    if any(sequence in state.rejected_sequences for sequence in admitted):
        raise ValueError("an admitted Plan sequence cannot remain rejected")
    for record in state.plans.values():
        _validate_record(record)
        if (
            not record.result.admitted
            and not record.result.retryable
            and record.sequence not in state.rejected_sequences
        ):
            raise ValueError("a final rejection MUST retain its sequence tombstone")


def _validate_record(record: PlanRecord) -> None:
    if _HEX_DIGEST.fullmatch(record.payload_digest) is None:
        raise ValueError("agent state payload digest is invalid")
    if record.attempts == 0 and (record.reported_at is not None or record.reported):
        raise ValueError("an undelivered report cannot have delivery progress")
    if record.reported and record.reported_at is None:
        raise ValueError("an accepted report MUST retain its timestamp")
    _validate_result(record.result)


def _validate_result(result: PlanResult) -> None:
    if _REASON_CODE.fullmatch(result.reason_code) is None:
        raise ValueError("agent state reason code is invalid")
    if len(result.summary) > _MAX_SUMMARY_CHARACTERS:
        raise ValueError("agent state report summary is too large")
    if result.retryable and result.admitted:
        raise ValueError("an admitted result cannot be retryable")
    if result.admitted and (
        result.exact_plan_digest is None or _PLAN_DIGEST.fullmatch(result.exact_plan_digest) is None
    ):
        raise ValueError("an admitted result MUST retain the exact Plan digest")
    if (
        result.exact_plan_digest is not None
        and _PLAN_DIGEST.fullmatch(result.exact_plan_digest) is None
    ):
        raise ValueError("agent state exact Plan digest is invalid")
