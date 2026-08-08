"""In-memory adapters used by Wave 2+ agent behavior.

Wave 1 shipped stub agents with no state. Wave 2 begins wiring real
behavior: Saga writes to an append-only audit chain, Muninn holds a
key-value context store, Mimir tracks the rule promotion state. The
adapters here are simple in-memory implementations that satisfy the
provider protocols so tests can exercise the full flow without a
persistent backend. Fork adapters swap these behind the same
interfaces.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Audit chain (Saga)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuditEntry:
    seq: int
    prev_hash: str
    entry_hash: str
    principal: str
    topic: str
    correlation_id: str
    payload_digest: str


class AuditChainError(RuntimeError):
    """Raised when the audit chain integrity check fails."""


@dataclass
class InMemoryAuditChain:
    """Hash-linked append-only chain of AuditEntry records.

    Every append writes a new entry whose ``prev_hash`` is the previous
    ``entry_hash``. The chain is judge-only-replayable per pantheon
    contract: :meth:`verify` raises on any tamper (out-of-order or
    mutated payload).
    """

    entries: list[AuditEntry] = field(default_factory=list)
    durable: bool = False

    def append(
        self,
        *,
        principal: str,
        topic: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> AuditEntry:
        seq = len(self.entries)
        prev_hash = self.entries[-1].entry_hash if self.entries else "0" * 64
        payload_digest = _digest(payload)
        entry_hash = _digest(
            {
                "seq": seq,
                "prev_hash": prev_hash,
                "principal": principal,
                "topic": topic,
                "correlation_id": correlation_id,
                "payload_digest": payload_digest,
            }
        )
        entry = AuditEntry(
            seq=seq,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
            principal=principal,
            topic=topic,
            correlation_id=correlation_id,
            payload_digest=payload_digest,
        )
        self.entries.append(entry)
        return entry

    def verify(self) -> None:
        """Walk the chain and raise on any broken link."""
        prev = "0" * 64
        for i, entry in enumerate(self.entries):
            if entry.seq != i:
                raise AuditChainError(f"seq mismatch at index {i}: {entry.seq!r}")
            if entry.prev_hash != prev:
                raise AuditChainError(
                    f"prev_hash mismatch at seq {i}: got {entry.prev_hash!r}, expected {prev!r}"
                )
            recomputed = _digest(
                {
                    "seq": entry.seq,
                    "prev_hash": entry.prev_hash,
                    "principal": entry.principal,
                    "topic": entry.topic,
                    "correlation_id": entry.correlation_id,
                    "payload_digest": entry.payload_digest,
                }
            )
            if recomputed != entry.entry_hash:
                raise AuditChainError(f"entry hash mismatch at seq {i}")
            prev = entry.entry_hash

    def entries_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        return [e for e in self.entries if e.correlation_id == correlation_id]


# ---------------------------------------------------------------------------
# Muninn state store
# ---------------------------------------------------------------------------


@dataclass
class InMemoryStateStore:
    """Muninn's key-value context store.

    Two-level: an outer bucket name (e.g. ``fingerprint_index``,
    ``resource_state``, ``conversation``) plus an inner key. Simple
    dict-of-dicts is enough for tests.
    """

    data: dict[str, dict[str, Any]] = field(default_factory=lambda: defaultdict(dict))

    def get(self, bucket: str, key: str) -> Any | None:
        return self.data.get(bucket, {}).get(key)

    def put(self, bucket: str, key: str, value: Any) -> None:
        self.data[bucket][key] = value

    def delete(self, bucket: str, key: str) -> None:
        self.data.get(bucket, {}).pop(key, None)

    def scan(self, bucket: str) -> dict[str, Any]:
        return dict(self.data.get(bucket, {}))


# ---------------------------------------------------------------------------
# GitHub Issue adapter (used by Saga)
# ---------------------------------------------------------------------------


@dataclass
class GitHubIssue:
    number: int
    fingerprint: str
    title: str
    body: str
    comments: list[str] = field(default_factory=list)
    open: bool = True
    closed_by_pr: str | None = None


class IssueTrackerAdapter(Protocol):
    @property
    def issues(self) -> Mapping[str, GitHubIssue]: ...

    def create_or_comment(
        self,
        *,
        fingerprint: str,
        title: str,
        body: str,
    ) -> tuple[GitHubIssue, bool] | Awaitable[tuple[GitHubIssue, bool]]: ...

    def close(
        self,
        fingerprint: str,
        *,
        closed_by_pr: str,
    ) -> None | Awaitable[None]: ...


@dataclass
class InMemoryGithubIssueAdapter:
    """Stand-in for the real GitHub App integration.

    Real fork adapter wraps the GitHub REST API behind this contract.
    The in-memory version tracks issues by fingerprint so tests can
    verify dedup, comment append, and auto-close semantics.
    """

    issues: dict[str, GitHubIssue] = field(default_factory=dict)
    next_number: int = 1

    def create_or_comment(
        self,
        *,
        fingerprint: str,
        title: str,
        body: str,
    ) -> tuple[GitHubIssue, bool]:
        """Return (issue, was_created). Comment append on duplicate."""
        existing = self.issues.get(fingerprint)
        if existing is not None and existing.open:
            existing.comments.append(body)
            return existing, False
        number = self.next_number
        self.next_number += 1
        issue = GitHubIssue(
            number=number,
            fingerprint=fingerprint,
            title=title,
            body=body,
        )
        self.issues[fingerprint] = issue
        return issue, True

    def close(self, fingerprint: str, *, closed_by_pr: str) -> None:
        issue = self.issues.get(fingerprint)
        if issue is None or not issue.open:
            return
        issue.open = False
        issue.closed_by_pr = closed_by_pr
        issue.comments.append(f"Closed by promotion PR {closed_by_pr}.")


# ---------------------------------------------------------------------------
# ChatOps admin channel (used by Var)
# ---------------------------------------------------------------------------


@dataclass
class AdminCard:
    severity: str
    initiator_principal: str
    attempted_action: str
    counter: int


class AdminNotificationAdapter(Protocol):
    def upsert(
        self,
        dedup_key: tuple[str, str],
        card: AdminCard,
    ) -> AdminCard | Awaitable[AdminCard]: ...


@dataclass
class InMemoryAdminChannel:
    """In-memory sink for admin notifications; fork adapter posts to Teams."""

    cards: list[AdminCard] = field(default_factory=list)
    _positions: dict[tuple[str, str], int] = field(default_factory=dict)

    def send(self, card: AdminCard) -> None:
        self.cards.append(card)

    def upsert(self, dedup_key: tuple[str, str], card: AdminCard) -> AdminCard:
        position = self._positions.get(dedup_key)
        if position is None:
            self._positions[dedup_key] = len(self.cards)
            self.cards.append(card)
        else:
            self.cards[position] = card
        return card


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _digest(obj: Any) -> str:
    """Stable JSON-based SHA256 digest, used for audit chain integrity."""
    payload = json.dumps(obj, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "AdminCard",
    "AdminNotificationAdapter",
    "AuditChainError",
    "AuditEntry",
    "GitHubIssue",
    "InMemoryAdminChannel",
    "InMemoryAuditChain",
    "InMemoryGithubIssueAdapter",
    "InMemoryStateStore",
    "IssueTrackerAdapter",
]
