"""Saga - append-only audit and typed issue-handoff materialization."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fdai.agents._framework.adapters import (
    AuditEntry,
    GitHubIssue,
    IdempotentIssueTrackerAdapter,
    IssueTrackerAdapter,
)

_FINGERPRINT_BUCKET = "issue_fingerprint_index"
_AUDIT_OUTBOX_PREFIX = "pantheon/saga/audit-outbox/"
_FINGERPRINT_PREFIX = "pantheon/saga/issue-fingerprint/"
_ISSUE_CLOSE_ELIGIBILITY_PREFIX = "pantheon/saga/issue-close-eligibility/"
_AUDIT_OUTBOX_PENDING_SCAN_LIMIT = 5_000
_AUDIT_OUTBOX_MAINTENANCE_PAGE = 16
# Published outbox tombstones retain only digests long enough to suppress
# duplicate redelivery across restarts while keeping prefix scans bounded.
_AUDIT_OUTBOX_TOMBSTONE_RETENTION = 1_024
_AUDIT_OUTBOX_CLAIM_LEASE = timedelta(minutes=5)
_FORECAST_AUDIT_FENCE_SIZE = 10_000
_MAX_FINGERPRINT_INDEX = 50_000
_FINGERPRINT_RETENTION = 10_000
_ISSUE_CLOSE_CLEAN_WINDOW = timedelta(hours=24)
_ISSUE_CLOSE_ELIGIBILITY_BUCKET = "issue_close_eligibility"
_MAX_HANDOFF_CONTEXT_ITEMS = 8
_MAX_HANDOFF_CONTEXT_VALUE_CHARS = 256
_HANDOFF_CONTEXT_KEYS = frozenset(
    {
        "context_ref",
        "evidence_ref",
        "handoff_ref",
        "payload_digest",
        "source_ref",
        "trace_ref",
    }
)
_NON_LEARNABLE_TERMINAL_STATES = frozenset(
    {"deny_dropped", "rejected", "expired", "approval_expired"}
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SagaAuditChain(Protocol):
    durable: bool
    entries: list[AuditEntry]

    def append(
        self: Any,
        *,
        principal: str,
        topic: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> AuditEntry | Awaitable[AuditEntry]: ...

    def entries_for_correlation(self: Any, correlation_id: str) -> list[AuditEntry]: ...


@dataclass
class _RefCountedLock:
    lock: asyncio.Lock
    ref_count: int = 0


class SagaIssueRuntimeMixin:
    """Behavior-preserving extracted runtime methods."""

    async def escalate_to_github_issue(
        self: Any,
        *,
        fingerprint: str,
        emitting_agent: str,
        intent_category: str,
        failure_reason_code: str,
        correlation_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        operation_id = f"handoff:{fingerprint}:{correlation_id}"
        issue_number, created, occurrence_count = await self._mutate_github_issue(
            operation_id=operation_id,
            fingerprint=fingerprint,
            emitting_agent=emitting_agent,
            intent_category=intent_category,
            failure_reason_code=failure_reason_code,
            correlation_id=correlation_id,
            context=_bounded_handoff_context(context),
        )
        await self._append_issue_audit(
            fingerprint=fingerprint,
            issue_number=issue_number,
            created=created,
            correlation_id=correlation_id,
            operation_id=operation_id,
        )
        if self.bus is not None:
            await self._publish_issue(
                fingerprint=fingerprint,
                issue_number=issue_number,
                created=created,
                correlation_id=correlation_id,
                operation_id=operation_id,
            )
        return {
            "issue_number": issue_number,
            "created": created,
            "occurrence_count": occurrence_count,
        }

    async def _mutate_github_issue(
        self: Any,
        *,
        operation_id: str,
        fingerprint: str,
        emitting_agent: str,
        intent_category: str,
        failure_reason_code: str,
        correlation_id: str,
        emitted_at: str = "",
        context: dict[str, Any] | None = None,
        require_idempotent: bool = False,
    ) -> tuple[int, bool, int]:
        durable_prior = await self._load_durable_fingerprint(fingerprint)
        prior = durable_prior or self._fingerprint_index.get(fingerprint)
        replay = bool(prior and prior.get("last_correlation_id") == correlation_id)
        observed_at = emitted_at or "unknown"
        first_seen = str(prior.get("first_seen") or observed_at) if prior else observed_at
        prior_count = int(prior.get("occurrence_count", 0)) if prior is not None else 0
        occurrence_count = prior_count if replay else (prior_count + 1 if prior else 1)
        last_seen = str(prior.get("last_seen") or observed_at) if replay and prior else observed_at
        labels = _fingerprint_labels(fingerprint)
        title = f"[{intent_category}] {emitting_agent} handoff"
        body_lines = [
            f"Fingerprint: `{fingerprint}`",
            f"First seen: {first_seen}",
            f"Last seen: {last_seen}",
            f"Occurrence count: {occurrence_count}",
            f"Emitting agent: {emitting_agent}",
            f"Failure reason: {failure_reason_code}",
            f"Correlation id: {correlation_id}",
        ]
        if context:
            for k, v in sorted(_bounded_handoff_context(context).items()):
                body_lines.append(f"- {k}: {v}")
        body = "\n".join(body_lines)
        if durable_prior is not None:
            await self.rehydrate_issue_tracker()
            if not isinstance(self.github, IdempotentIssueTrackerAdapter):
                raise RuntimeError("Saga durable handoff requires an idempotent issue adapter")
            issue_result = _create_or_comment_once(
                self.github,
                operation_id=operation_id,
                fingerprint=fingerprint,
                title=title,
                body=body,
                labels=labels,
            )
            if inspect.isawaitable(issue_result):
                issue, _created = await asyncio.wait_for(
                    issue_result,
                    timeout=self._issue_timeout_seconds,
                )
            else:
                issue, _created = issue_result
            updated = await self._increment_durable_fingerprint(
                fingerprint,
                last_correlation_id=correlation_id,
                first_seen=first_seen,
                last_seen=last_seen,
            )
            if updated is None:
                raise RuntimeError("durable issue fingerprint disappeared during increment")
            self._fingerprint_index.set(fingerprint, updated)
            return issue.number, False, int(updated["occurrence_count"])
        if self._durable_state_store is not None and not await self._claim_fingerprint_creation(
            fingerprint,
            operation_id=operation_id,
            correlation_id=correlation_id,
        ):
            creating_operation = await self._fingerprint_creation_operation(fingerprint)
            if creating_operation == operation_id and isinstance(
                self.github, IdempotentIssueTrackerAdapter
            ):
                pass
            else:
                await self.rehydrate_issue_tracker()
                durable_after_claim = await self._load_durable_fingerprint(fingerprint)
                if durable_after_claim is not None:
                    updated = await self._increment_durable_fingerprint(
                        fingerprint,
                        last_correlation_id=correlation_id,
                        first_seen=first_seen,
                        last_seen=last_seen,
                    )
                    if updated is None:
                        raise RuntimeError("durable issue fingerprint disappeared during increment")
                    self._fingerprint_index.set(fingerprint, updated)
                    return (
                        int(updated["issue_number"]),
                        False,
                        int(updated["occurrence_count"]),
                    )
                self.record_behavior("handoff:fingerprint_claim_busy")
                raise RuntimeError("issue fingerprint mutation is already in progress")
        if isinstance(self.github, IdempotentIssueTrackerAdapter):
            issue_result = _create_or_comment_once(
                self.github,
                operation_id=operation_id,
                fingerprint=fingerprint,
                title=title,
                body=body,
                labels=labels,
            )
        elif require_idempotent:
            raise RuntimeError("Saga handoff requires an idempotent issue-tracker adapter")
        else:
            issue_result = _create_or_comment(
                self.github,
                fingerprint=fingerprint,
                title=title,
                body=body,
                labels=labels,
            )
        if inspect.isawaitable(issue_result):
            try:
                issue, created = await asyncio.wait_for(
                    issue_result,
                    timeout=self._issue_timeout_seconds,
                )
            except TimeoutError:
                self.record_behavior("handoff:issue_timeout")
                raise
        else:
            issue, created = issue_result
        occurrence_count = 1 + len(issue.comments)
        fingerprint_state = {
            "issue_number": issue.number,
            "occurrence_count": occurrence_count,
            "last_correlation_id": correlation_id,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "open": issue.open,
        }
        self._put_fingerprint_index(fingerprint, fingerprint_state)
        await self._put_durable_fingerprint(fingerprint, fingerprint_state)
        return issue.number, created, occurrence_count

    def _put_fingerprint_index(self: Any, fingerprint: str, value: dict[str, Any]) -> None:
        self._fingerprint_index.set(fingerprint, value)
        self.state_store.data[_FINGERPRINT_BUCKET] = dict(self._fingerprint_index.items())

    async def _load_durable_fingerprint(self: Any, fingerprint: str) -> dict[str, Any] | None:
        if self._durable_state_store is None:
            return None
        stored = await self._durable_state_store.read_state(_fingerprint_key(fingerprint))
        if stored is None:
            return None
        if stored.get("status") == "creating":
            return None
        issue_number = stored.get("issue_number")
        occurrence_count = stored.get("occurrence_count")
        if (
            stored.get("schema_version") != "1.0.0"
            or not isinstance(issue_number, int)
            or isinstance(issue_number, bool)
            or issue_number < 1
            or not isinstance(occurrence_count, int)
            or isinstance(occurrence_count, bool)
            or occurrence_count < 1
        ):
            raise RuntimeError("durable issue fingerprint record is malformed")
        return dict(stored)

    async def _claim_fingerprint_creation(
        self: Any,
        fingerprint: str,
        *,
        operation_id: str,
        correlation_id: str,
    ) -> bool:
        if self._durable_state_store is None:
            return True
        key = _fingerprint_key(fingerprint)
        return bool(
            await self._durable_state_store.write_state_if_absent(
                key,
                {
                    "schema_version": "1.0.0",
                    "revision": 1,
                    "fingerprint": fingerprint,
                    "status": "creating",
                    "operation_id": operation_id,
                    "last_correlation_id": correlation_id,
                },
            )
        )

    async def _fingerprint_creation_operation(self: Any, fingerprint: str) -> str | None:
        if self._durable_state_store is None:
            return None
        stored = await self._durable_state_store.read_state(_fingerprint_key(fingerprint))
        if stored is None or stored.get("status") != "creating":
            return None
        operation_id = stored.get("operation_id")
        return str(operation_id) if isinstance(operation_id, str) and operation_id else None

    async def _increment_durable_fingerprint(
        self: Any,
        fingerprint: str,
        *,
        last_correlation_id: str,
        first_seen: str,
        last_seen: str,
    ) -> dict[str, Any] | None:
        if self._durable_state_store is None:
            return None
        key = _fingerprint_key(fingerprint)
        for _attempt in range(16):
            stored = await self._durable_state_store.read_state(key)
            if stored is None:
                return None
            current = await self._load_durable_fingerprint(fingerprint)
            if current is None:
                return None
            revision = int(stored.get("revision", 1))
            updated = {
                **current,
                "occurrence_count": int(current["occurrence_count"]) + 1,
                "last_correlation_id": last_correlation_id,
                "first_seen": first_seen,
                "last_seen": last_seen,
            }
            advanced = await self._durable_state_store.compare_and_set_state(
                key,
                {**updated, "revision": revision + 1},
                expected_revision=revision,
            )
            if advanced:
                return updated
        raise RuntimeError("issue fingerprint occurrence CAS retry limit exceeded")

    async def _put_durable_fingerprint(self: Any, fingerprint: str, value: dict[str, Any]) -> None:
        if self._durable_state_store is None:
            return
        record = {
            "schema_version": "1.0.0",
            "revision": 1,
            "fingerprint": fingerprint,
            "status": "complete",
            **value,
        }
        key = _fingerprint_key(fingerprint)
        created = await self._durable_state_store.write_state_if_absent(key, record)
        if created:
            return
        for _attempt in range(16):
            stored = await self._durable_state_store.read_state(key)
            if stored is None:
                continue
            revision = int(stored.get("revision", 1))
            advanced = await self._durable_state_store.compare_and_set_state(
                key,
                {**record, "revision": revision + 1},
                expected_revision=revision,
            )
            if advanced:
                return
        raise RuntimeError("issue fingerprint CAS retry limit exceeded")

    async def _append_issue_audit(
        self: Any,
        *,
        fingerprint: str,
        issue_number: int,
        created: bool,
        correlation_id: str,
        operation_id: str,
    ) -> None:
        await self._append_audit(
            principal="Saga",
            topic="object.issue",
            correlation_id=correlation_id,
            payload={
                "idempotency_key": operation_id,
                "fingerprint": fingerprint,
                "issue_number": issue_number,
                "created": created,
            },
        )

    async def _publish_issue(
        self: Any,
        *,
        fingerprint: str,
        issue_number: int,
        created: bool,
        correlation_id: str,
        operation_id: str,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        if self.bus is None:
            return
        payload = {
            "producer_principal": "Saga",
            "correlation_id": correlation_id,
            "idempotency_key": operation_id,
            "fingerprint": fingerprint,
            "issue_number": issue_number,
            "created": created,
        }
        if extra is not None:
            payload.update(extra)
        await self.bus.publish("Saga", "object.issue", payload)


def _bounded_handoff_context(raw: Mapping[str, Any] | object | None) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    sanitized: dict[str, str] = {}
    for key, value in sorted(raw.items()):
        name = str(key)
        if name not in _HANDOFF_CONTEXT_KEYS:
            continue
        if len(sanitized) >= _MAX_HANDOFF_CONTEXT_ITEMS:
            break
        rendered = str(value).strip()
        if not rendered or len(rendered) > _MAX_HANDOFF_CONTEXT_VALUE_CHARS:
            continue
        sanitized[name] = rendered
    return sanitized


def _fingerprint_labels(fingerprint: str) -> tuple[str, ...]:
    if len(fingerprint) == 64 and all(character in "0123456789abcdef" for character in fingerprint):
        return (f"fdai:fp:{fingerprint}",)
    return ()


def _create_or_comment_once(
    github: IdempotentIssueTrackerAdapter,
    *,
    operation_id: str,
    fingerprint: str,
    title: str,
    body: str,
    labels: tuple[str, ...],
) -> tuple[GitHubIssue, bool] | Awaitable[tuple[GitHubIssue, bool]]:
    try:
        return github.create_or_comment_once(
            operation_id=operation_id,
            fingerprint=fingerprint,
            title=title,
            body=body,
            labels=labels,
        )
    except TypeError as exc:
        if "labels" not in str(exc):
            raise
        return github.create_or_comment_once(
            operation_id=operation_id,
            fingerprint=fingerprint,
            title=title,
            body=body,
        )


def _create_or_comment(
    github: IssueTrackerAdapter,
    *,
    fingerprint: str,
    title: str,
    body: str,
    labels: tuple[str, ...],
) -> tuple[GitHubIssue, bool] | Awaitable[tuple[GitHubIssue, bool]]:
    try:
        return github.create_or_comment(
            fingerprint=fingerprint,
            title=title,
            body=body,
            labels=labels,
        )
    except TypeError as exc:
        if "labels" not in str(exc):
            raise
        return github.create_or_comment(
            fingerprint=fingerprint,
            title=title,
            body=body,
        )


def _fingerprint_key(fingerprint: str) -> str:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return f"{_FINGERPRINT_PREFIX}{digest}"


__all__ = ["SagaIssueRuntimeMixin"]
