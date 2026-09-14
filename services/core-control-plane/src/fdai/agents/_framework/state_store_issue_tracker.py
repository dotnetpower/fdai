"""StateStore-backed issue tracker for restart-safe Saga handoffs."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework.adapters import GitHubIssue
from fdai.shared.providers.state_store import StateStore

_STATE_PREFIX = "pantheon/saga/issues"
_MAX_CAS_ATTEMPTS = 16
_MAX_ISSUES = 10_000
_MAX_OPERATIONS_PER_ISSUE = 10_000


class StateStoreIssueTrackerAdapter:
    """Persist synthetic issue state and exact operation results across restart."""

    def __init__(self, store: StateStore, *, max_issues: int = _MAX_ISSUES) -> None:
        if max_issues < 1:
            raise ValueError("max_issues MUST be at least one")
        self._store = store
        self._max_issues = max_issues
        self._issues: OrderedDict[str, GitHubIssue] = OrderedDict()

    @property
    def issues(self) -> Mapping[str, GitHubIssue]:
        return self._issues

    async def rehydrate(self) -> int:
        """Restore the bounded current issue projection from durable state."""
        rows = await self._store.read_states(
            f"{_STATE_PREFIX}/",
            limit=self._max_issues,
        )
        restored: OrderedDict[str, GitHubIssue] = OrderedDict()
        for row in reversed(rows):
            fingerprint = row.get("fingerprint")
            if not isinstance(fingerprint, str):
                raise RuntimeError("stored issue state is malformed")
            canonical = _validate_issue_state(row, fingerprint=fingerprint)
            restored[fingerprint] = _current_issue(canonical)
        self._issues = restored
        return len(restored)

    async def create_or_comment(
        self,
        *,
        fingerprint: str,
        title: str,
        body: str,
    ) -> tuple[GitHubIssue, bool]:
        """Apply one content-addressed legacy operation."""
        request_digest = _request_digest(fingerprint, title, body)
        return await self.create_or_comment_once(
            operation_id=f"legacy:{request_digest}",
            fingerprint=fingerprint,
            title=title,
            body=body,
        )

    async def create_or_comment_once(
        self,
        *,
        operation_id: str,
        fingerprint: str,
        title: str,
        body: str,
    ) -> tuple[GitHubIssue, bool]:
        """CAS-apply one operation and replay its original result."""
        _validate_request(
            operation_id=operation_id,
            fingerprint=fingerprint,
            title=title,
            body=body,
        )
        operation_digest = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
        request_digest = _request_digest(fingerprint, title, body)
        state_key = _issue_state_key(fingerprint)
        for _attempt in range(_MAX_CAS_ATTEMPTS):
            stored = await self._store.read_state(state_key)
            if stored is None:
                generation = 1
                issue_number = _issue_number(fingerprint, generation)
                result = _operation_result(
                    request_digest=request_digest,
                    fingerprint=fingerprint,
                    issue_number=issue_number,
                    issue_title=title,
                    issue_body=body,
                    created=True,
                    occurrence_count=1,
                )
                value = _issue_state(
                    revision=1,
                    fingerprint=fingerprint,
                    generation=generation,
                    issue_number=issue_number,
                    title=title,
                    body=body,
                    comments=(),
                    open_=True,
                    closed_by_pr=None,
                    operations={operation_digest: result},
                )
                created = await self._store.write_state_with_audit_if_absent(
                    state_key,
                    value,
                    _audit_entry(
                        action_kind="issue.created",
                        fingerprint=fingerprint,
                        operation_digest=operation_digest,
                        revision=1,
                    ),
                )
                if created:
                    self._remember_issue(fingerprint, _current_issue(value))
                    return _operation_issue(result), True
                continue

            current = _validate_issue_state(stored, fingerprint=fingerprint)
            operations = _operations(current)
            prior = operations.get(operation_digest)
            if prior is not None:
                if prior["request_digest"] != request_digest:
                    raise ValueError("issue operation_id reused with different content")
                self._remember_issue(fingerprint, _current_issue(current))
                return _operation_issue(prior), bool(prior["created"])
            if len(operations) >= _MAX_OPERATIONS_PER_ISSUE:
                raise RuntimeError("issue operation history capacity exhausted")

            if bool(current["open"]):
                generation = int(current["generation"])
                issue_number = int(current["issue_number"])
                issue_title = str(current["title"])
                issue_body = str(current["body"])
                comments = (*_comments(current), body)
                created_result = False
            else:
                generation = int(current["generation"]) + 1
                issue_number = _issue_number(fingerprint, generation)
                issue_title = title
                issue_body = body
                comments = ()
                created_result = True
            result = _operation_result(
                request_digest=request_digest,
                fingerprint=fingerprint,
                issue_number=issue_number,
                issue_title=issue_title,
                issue_body=issue_body,
                created=created_result,
                occurrence_count=1 + len(comments),
            )
            next_operations = {**operations, operation_digest: result}
            next_revision = int(current["revision"]) + 1
            value = _issue_state(
                revision=next_revision,
                fingerprint=fingerprint,
                generation=generation,
                issue_number=issue_number,
                title=issue_title,
                body=issue_body,
                comments=comments,
                open_=True,
                closed_by_pr=None,
                operations=next_operations,
            )
            advanced = await self._store.compare_and_set_state_with_audit(
                state_key,
                value,
                expected_revision=int(current["revision"]),
                audit_entry=_audit_entry(
                    action_kind=("issue.created" if created_result else "issue.commented"),
                    fingerprint=fingerprint,
                    operation_digest=operation_digest,
                    revision=next_revision,
                ),
            )
            if advanced:
                self._remember_issue(fingerprint, _current_issue(value))
                return _operation_issue(result), created_result
        raise RuntimeError("issue operation CAS retry limit exceeded")

    async def close(self, fingerprint: str, *, closed_by_pr: str) -> None:
        if not fingerprint or not closed_by_pr:
            raise ValueError("issue close requires fingerprint and closed_by_pr")
        state_key = _issue_state_key(fingerprint)
        for _attempt in range(_MAX_CAS_ATTEMPTS):
            stored = await self._store.read_state(state_key)
            if stored is None:
                return
            current = _validate_issue_state(stored, fingerprint=fingerprint)
            if not bool(current["open"]):
                self._remember_issue(fingerprint, _current_issue(current))
                return
            next_revision = int(current["revision"]) + 1
            value = _issue_state(
                revision=next_revision,
                fingerprint=fingerprint,
                generation=int(current["generation"]),
                issue_number=int(current["issue_number"]),
                title=str(current["title"]),
                body=str(current["body"]),
                comments=_comments(current),
                open_=False,
                closed_by_pr=closed_by_pr,
                operations=_operations(current),
            )
            _validate_issue_state(value, fingerprint=fingerprint)
            advanced = await self._store.compare_and_set_state_with_audit(
                state_key,
                value,
                expected_revision=int(current["revision"]),
                audit_entry=_audit_entry(
                    action_kind="issue.closed",
                    fingerprint=fingerprint,
                    operation_digest="",
                    revision=next_revision,
                ),
            )
            if advanced:
                self._remember_issue(fingerprint, _current_issue(value))
                return
        raise RuntimeError("issue close CAS retry limit exceeded")

    def _remember_issue(self, fingerprint: str, issue: GitHubIssue) -> None:
        self._issues[fingerprint] = issue
        self._issues.move_to_end(fingerprint)
        if len(self._issues) > self._max_issues:
            self._issues.popitem(last=False)


def _validate_request(
    *,
    operation_id: str,
    fingerprint: str,
    title: str,
    body: str,
) -> None:
    if (
        not isinstance(operation_id, str)
        or not operation_id
        or operation_id != operation_id.strip()
        or len(operation_id) > 1_024
        or not isinstance(fingerprint, str)
        or not fingerprint
        or fingerprint != fingerprint.strip()
        or len(fingerprint) > 512
        or not isinstance(title, str)
        or not title
        or len(title) > 512
        or not isinstance(body, str)
        or not body
        or len(body) > 20_000
    ):
        raise ValueError("issue operation request is malformed")


def _issue_state_key(fingerprint: str) -> str:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return f"{_STATE_PREFIX}/{digest}"


def _issue_number(fingerprint: str, generation: int) -> int:
    material = f"{fingerprint}\x00{generation}".encode()
    return int(hashlib.sha256(material).hexdigest()[:15], 16) + 1


def _request_digest(fingerprint: str, title: str, body: str) -> str:
    encoded = json.dumps(
        {"body": body, "fingerprint": fingerprint, "title": title},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _operation_result(
    *,
    request_digest: str,
    fingerprint: str,
    issue_number: int,
    issue_title: str,
    issue_body: str,
    created: bool,
    occurrence_count: int,
) -> dict[str, Any]:
    return {
        "request_digest": request_digest,
        "fingerprint": fingerprint,
        "issue_number": issue_number,
        "issue_title": issue_title,
        "issue_body": issue_body,
        "created": created,
        "occurrence_count": occurrence_count,
    }


def _issue_state(
    *,
    revision: int,
    fingerprint: str,
    generation: int,
    issue_number: int,
    title: str,
    body: str,
    comments: tuple[str, ...],
    open_: bool,
    closed_by_pr: str | None,
    operations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "fingerprint": fingerprint,
        "generation": generation,
        "issue_number": issue_number,
        "title": title,
        "body": body,
        "comments": list(comments),
        "open": open_,
        "closed_by_pr": closed_by_pr,
        "operations": {
            operation_digest: dict(result)
            for operation_digest, result in sorted(operations.items())
        },
    }


def _validate_issue_state(
    value: Mapping[str, Any],
    *,
    fingerprint: str,
) -> dict[str, Any]:
    revision = value.get("revision")
    generation = value.get("generation")
    issue_number = value.get("issue_number")
    title = value.get("title")
    body = value.get("body")
    comments_raw = value.get("comments")
    open_ = value.get("open")
    closed_by_pr = value.get("closed_by_pr")
    operations_raw = value.get("operations")
    if (
        value.get("schema_version") != "1.0.0"
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or value.get("fingerprint") != fingerprint
        or not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation < 1
        or issue_number != _issue_number(fingerprint, generation)
        or not isinstance(title, str)
        or not title
        or len(title) > 512
        or not isinstance(body, str)
        or not body
        or len(body) > 20_000
        or not isinstance(comments_raw, list)
        or any(not isinstance(comment, str) for comment in comments_raw)
        or len(comments_raw) >= _MAX_OPERATIONS_PER_ISSUE
        or not isinstance(open_, bool)
        or (
            open_
            and closed_by_pr is not None
            or not open_
            and (not isinstance(closed_by_pr, str) or not closed_by_pr)
        )
        or not isinstance(operations_raw, Mapping)
        or not operations_raw
        or len(operations_raw) > _MAX_OPERATIONS_PER_ISSUE
    ):
        raise RuntimeError("stored issue state is malformed")

    operations: dict[str, dict[str, Any]] = {}
    for operation_digest, result in operations_raw.items():
        if (
            not isinstance(operation_digest, str)
            or len(operation_digest) != 64
            or any(character not in "0123456789abcdef" for character in operation_digest)
            or not isinstance(result, Mapping)
        ):
            raise RuntimeError("stored issue operation result is malformed")
        result_dict = dict(result)
        if (
            set(result_dict)
            != {
                "request_digest",
                "fingerprint",
                "issue_number",
                "issue_title",
                "issue_body",
                "created",
                "occurrence_count",
            }
            or not _is_sha256(result_dict["request_digest"])
            or result_dict["fingerprint"] != fingerprint
            or not isinstance(result_dict["issue_number"], int)
            or isinstance(result_dict["issue_number"], bool)
            or result_dict["issue_number"] < 1
            or not isinstance(result_dict["issue_title"], str)
            or not isinstance(result_dict["issue_body"], str)
            or not isinstance(result_dict["created"], bool)
            or not isinstance(result_dict["occurrence_count"], int)
            or isinstance(result_dict["occurrence_count"], bool)
            or result_dict["occurrence_count"] < 1
        ):
            raise RuntimeError("stored issue operation result is malformed")
        operations[operation_digest] = result_dict

    canonical = _issue_state(
        revision=revision,
        fingerprint=fingerprint,
        generation=generation,
        issue_number=int(issue_number),
        title=title,
        body=body,
        comments=tuple(str(comment) for comment in comments_raw),
        open_=open_,
        closed_by_pr=closed_by_pr if isinstance(closed_by_pr, str) else None,
        operations=operations,
    )
    if dict(value) != canonical:
        raise RuntimeError("stored issue state is malformed")
    return canonical


def _operations(value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = value["operations"]
    if not isinstance(raw, Mapping):
        raise RuntimeError("stored issue operations are malformed")
    return {
        str(operation_digest): dict(result)
        for operation_digest, result in raw.items()
        if isinstance(result, Mapping)
    }


def _comments(value: Mapping[str, Any]) -> tuple[str, ...]:
    raw = value["comments"]
    if not isinstance(raw, list):
        raise RuntimeError("stored issue comments are malformed")
    return tuple(str(comment) for comment in raw)


def _current_issue(value: Mapping[str, Any]) -> GitHubIssue:
    return GitHubIssue(
        number=int(value["issue_number"]),
        fingerprint=str(value["fingerprint"]),
        title=str(value["title"]),
        body=str(value["body"]),
        comments=list(_comments(value)),
        open=bool(value["open"]),
        closed_by_pr=(
            str(value["closed_by_pr"]) if value.get("closed_by_pr") is not None else None
        ),
    )


def _operation_issue(result: Mapping[str, Any]) -> GitHubIssue:
    occurrence_count = int(result["occurrence_count"])
    return GitHubIssue(
        number=int(result["issue_number"]),
        fingerprint=str(result["fingerprint"]),
        title=str(result["issue_title"]),
        body=str(result["issue_body"]),
        comments=[""] * (occurrence_count - 1),
    )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _audit_entry(
    *,
    action_kind: str,
    fingerprint: str,
    operation_digest: str,
    revision: int,
) -> dict[str, Any]:
    return {
        "actor": "Saga",
        "action_kind": action_kind,
        "fingerprint": fingerprint,
        "operation_id_digest": (f"sha256:{operation_digest}" if operation_digest else None),
        "revision": revision,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }


__all__ = ["StateStoreIssueTrackerAdapter"]
