"""GitHub App issue delivery with StateStore operation identity and remote readback."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from fdai_github_app_auth import TokenProvider

from fdai.agents import GitHubIssue, StateStoreIssueTrackerAdapter
from fdai.shared.providers.state_store import StateStore

_API_VERSION = "2022-11-28"
_LOCK_PREFIX = "pantheon/saga/remote-issue-locks"
_LOCK_LEASE = timedelta(seconds=30)
_MAX_CAS_ATTEMPTS = 16
_MAX_ISSUES = 256
_RESERVED_MARKER = "<!-- fdai-"


@dataclass(frozen=True, slots=True)
class GitHubIssueTrackerConfig:
    owner: str
    repo: str
    api_base: str = "https://api.github.com"
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.api_base)
        if (
            not self.owner
            or self.owner != self.owner.strip()
            or "/" in self.owner
            or not self.repo
            or self.repo != self.repo.strip()
            or "/" in self.repo
        ):
            raise ValueError("GitHub issue owner and repo MUST be canonical names")
        if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
            raise ValueError("GitHub issue api_base MUST be an HTTPS origin")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ValueError("GitHub issue timeout_seconds MUST be in (0, 60]")


class GitHubRestIssueClient:
    """Apply marker-bound issue effects and verify provider-assigned identities."""

    def __init__(
        self,
        *,
        config: GitHubIssueTrackerConfig,
        http_client: httpx.AsyncClient,
        token_provider: TokenProvider,
    ) -> None:
        self._config = config
        self._http = http_client
        self._token_provider = token_provider

    async def ensure_operation(
        self,
        *,
        operation_digest: str,
        request_digest: str,
        fingerprint: str,
        title: str,
        body: str,
        labels: tuple[str, ...],
        created: bool,
    ) -> GitHubIssue:
        _validate_remote_request(fingerprint=fingerprint, title=title, body=body, labels=labels)
        action = "create" if created else "comment"
        fingerprint_digest = _sha256(fingerprint)
        fingerprint_marker = f"<!-- fdai-fingerprint-sha256:{fingerprint_digest} -->"
        operation_marker = (
            f"<!-- fdai-operation:{operation_digest}:{request_digest.removeprefix('sha256:')}"
            f":{action} -->"
        )
        issues = await self._matching_issues(fingerprint_digest)
        replay = await self._find_operation(
            issues,
            operation_digest=operation_digest,
            operation_marker=operation_marker,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return replay
        if created:
            if any(issue.get("state") == "open" for issue in issues):
                raise RuntimeError("GitHub issue create is ordered behind another open generation")
            fingerprint_label = _fingerprint_label(fingerprint_digest)
            response = _object_payload(
                await self._request(
                    "POST",
                    self._issues_path(),
                    expected_status=201,
                    json_body={
                        "title": title,
                        "body": f"{body}\n\n{fingerprint_marker}\n{operation_marker}",
                        "labels": sorted(set((*labels, fingerprint_label))),
                    },
                ),
                "created issue",
            )
            number = _positive_int(response.get("number"), "created issue number")
        else:
            open_issues = [issue for issue in issues if issue.get("state") == "open"]
            if len(open_issues) != 1:
                raise RuntimeError("GitHub issue comment requires one exact open issue")
            number = _positive_int(open_issues[0].get("number"), "open issue number")
            response = _object_payload(
                await self._request(
                    "POST",
                    f"{self._issues_path()}/{number}/comments",
                    expected_status=201,
                    json_body={"body": f"{body}\n\n{operation_marker}"},
                ),
                "created comment",
            )
            comment_id = _positive_int(response.get("id"), "created comment id")
            comment = _object_payload(
                await self._request(
                    "GET",
                    f"{self._repo_path()}/issues/comments/{comment_id}",
                    expected_status=200,
                ),
                "comment readback",
            )
            if operation_marker not in _required_text(comment, "body"):
                raise RuntimeError("GitHub issue comment readback differs")
        issue = await self._read_issue(number)
        comments = await self._read_comments(number)
        if not _contains_marker(issue, comments, operation_marker):
            raise RuntimeError("GitHub issue operation readback omitted its marker")
        if fingerprint_marker not in _required_text(issue, "body"):
            raise RuntimeError("GitHub issue fingerprint readback differs")
        return _project_issue(issue, comments, fingerprint=fingerprint)

    async def ensure_closed(self, *, fingerprint: str, closed_by_pr: str) -> GitHubIssue | None:
        if not closed_by_pr or closed_by_pr != closed_by_pr.strip():
            raise ValueError("GitHub issue close reference MUST be canonical text")
        fingerprint_digest = _sha256(fingerprint)
        issues = await self._matching_issues(fingerprint_digest)
        if not issues:
            return None
        issue = max(issues, key=lambda item: _positive_int(item.get("number"), "issue number"))
        number = _positive_int(issue.get("number"), "issue number")
        close_marker = f"<!-- fdai-close:{fingerprint_digest}:{_sha256(closed_by_pr)} -->"
        comments = await self._read_comments(number)
        if not _contains_marker(issue, comments, close_marker):
            response = _object_payload(
                await self._request(
                    "POST",
                    f"{self._issues_path()}/{number}/comments",
                    expected_status=201,
                    json_body={
                        "body": (f"Closed by reviewed promotion {closed_by_pr}.\n\n{close_marker}")
                    },
                ),
                "close comment",
            )
            comment_id = _positive_int(response.get("id"), "close comment id")
            comment = _object_payload(
                await self._request(
                    "GET",
                    f"{self._repo_path()}/issues/comments/{comment_id}",
                    expected_status=200,
                ),
                "close comment readback",
            )
            if close_marker not in _required_text(comment, "body"):
                raise RuntimeError("GitHub issue close marker readback differs")
        if issue.get("state") != "closed":
            await self._request(
                "PATCH",
                f"{self._issues_path()}/{number}",
                expected_status=200,
                json_body={"state": "closed"},
            )
        readback = await self._read_issue(number)
        comments = await self._read_comments(number)
        if readback.get("state") != "closed" or not _contains_marker(
            readback, comments, close_marker
        ):
            raise RuntimeError("GitHub issue close readback differs")
        projected = _project_issue(readback, comments, fingerprint=fingerprint)
        projected.closed_by_pr = closed_by_pr
        return projected

    async def find_current(self, fingerprint: str) -> GitHubIssue | None:
        issues = await self._matching_issues(_sha256(fingerprint))
        if not issues:
            return None
        issue = max(issues, key=lambda item: _positive_int(item.get("number"), "issue number"))
        number = _positive_int(issue.get("number"), "issue number")
        return _project_issue(
            await self._read_issue(number),
            await self._read_comments(number),
            fingerprint=fingerprint,
        )

    async def _find_operation(
        self,
        issues: tuple[Mapping[str, Any], ...],
        *,
        operation_digest: str,
        operation_marker: str,
        fingerprint: str,
    ) -> GitHubIssue | None:
        marker_prefix = f"<!-- fdai-operation:{operation_digest}:"
        matches: list[GitHubIssue] = []
        for issue in issues:
            number = _positive_int(issue.get("number"), "issue number")
            current = await self._read_issue(number)
            comments = await self._read_comments(number)
            texts = (
                _required_text(current, "body"),
                *(_required_text(item, "body") for item in comments),
            )
            if any(marker_prefix in text and operation_marker not in text for text in texts):
                raise ValueError("GitHub issue operation marker was reused with different content")
            if any(operation_marker in text for text in texts):
                matches.append(_project_issue(current, comments, fingerprint=fingerprint))
        if len(matches) > 1:
            raise RuntimeError("GitHub issue operation marker is not unique")
        return matches[0] if matches else None

    async def _matching_issues(self, fingerprint_digest: str) -> tuple[Mapping[str, Any], ...]:
        payload = await self._request(
            "GET",
            self._issues_path(),
            expected_status=200,
            params={
                "state": "all",
                "labels": _fingerprint_label(fingerprint_digest),
                "per_page": "100",
            },
        )
        if not isinstance(payload, list):
            raise RuntimeError("GitHub issue listing was not an array")
        if len(payload) >= 100:
            raise RuntimeError("GitHub issue listing reached its completeness bound")
        marker = f"<!-- fdai-fingerprint-sha256:{fingerprint_digest} -->"
        matches = tuple(
            item
            for item in payload
            if isinstance(item, Mapping)
            and "pull_request" not in item
            and marker in str(item.get("body") or "")
        )
        if len(matches) > 32:
            raise RuntimeError("GitHub issue fingerprint generations exceed the bound")
        return matches

    async def _read_issue(self, number: int) -> Mapping[str, Any]:
        payload = await self._request(
            "GET",
            f"{self._issues_path()}/{number}",
            expected_status=200,
        )
        if not isinstance(payload, Mapping):
            raise RuntimeError("GitHub issue readback was not an object")
        return payload

    async def _read_comments(self, number: int) -> tuple[Mapping[str, Any], ...]:
        payload = await self._request(
            "GET",
            f"{self._issues_path()}/{number}/comments",
            expected_status=200,
            params={"per_page": "100"},
        )
        if not isinstance(payload, list) or len(payload) >= 100:
            raise RuntimeError("GitHub issue comments are outside the readback bound")
        if not all(isinstance(item, Mapping) for item in payload):
            raise RuntimeError("GitHub issue comments contain a non-object")
        return tuple(payload)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int,
        json_body: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> object:
        token = await self._token_provider()
        try:
            response = await self._http.request(
                method,
                f"{self._config.api_base.rstrip('/')}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": _API_VERSION,
                },
                json=dict(json_body) if json_body is not None else None,
                params=dict(params) if params is not None else None,
                timeout=self._config.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("GitHub issue request failed") from exc
        if response.status_code != expected_status:
            raise RuntimeError(f"GitHub issue request returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError("GitHub issue response was not JSON") from exc

    def _repo_path(self) -> str:
        return f"/repos/{quote(self._config.owner, safe='')}/{quote(self._config.repo, safe='')}"

    def _issues_path(self) -> str:
        return f"{self._repo_path()}/issues"


class GitHubAppIssueTrackerAdapter:
    """Coordinate durable Saga operations with verified remote GitHub effects."""

    def __init__(
        self,
        *,
        store: StateStore,
        remote: GitHubRestIssueClient,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._local = StateStoreIssueTrackerAdapter(store, max_issues=_MAX_ISSUES)
        self._remote = remote
        self._clock = clock or (lambda: datetime.now(UTC))
        self._issues: OrderedDict[str, GitHubIssue] = OrderedDict()

    @property
    def issues(self) -> Mapping[str, GitHubIssue]:
        return self._issues

    async def rehydrate(self) -> int:
        await self._local.rehydrate()
        restored: OrderedDict[str, GitHubIssue] = OrderedDict()
        for fingerprint in self._local.issues:
            issue = await self._remote.find_current(fingerprint)
            if issue is not None:
                restored[fingerprint] = issue
        self._issues = restored
        return len(restored)

    async def create_or_comment(
        self,
        *,
        fingerprint: str,
        title: str,
        body: str,
        labels: tuple[str, ...] = (),
    ) -> tuple[GitHubIssue, bool]:
        request_digest = _request_digest(fingerprint, title, body, labels)
        return await self.create_or_comment_once(
            operation_id=f"legacy:{request_digest}",
            fingerprint=fingerprint,
            title=title,
            body=body,
            labels=labels,
        )

    async def create_or_comment_once(
        self,
        *,
        operation_id: str,
        fingerprint: str,
        title: str,
        body: str,
        labels: tuple[str, ...] = (),
    ) -> tuple[GitHubIssue, bool]:
        operation_digest = _sha256(operation_id)
        request_digest = _request_digest(fingerprint, title, body, labels)
        _validate_remote_request(fingerprint=fingerprint, title=title, body=body, labels=labels)
        local_issue, created = await self._local.create_or_comment_once(
            operation_id=operation_id,
            fingerprint=fingerprint,
            title=title,
            body=body,
            labels=labels,
        )
        claim = await self._acquire(fingerprint)
        try:
            remote_issue = await self._remote.ensure_operation(
                operation_digest=operation_digest,
                request_digest=request_digest,
                fingerprint=fingerprint,
                title=title,
                body=body,
                labels=labels,
                created=created,
            )
        finally:
            await self._release(fingerprint, claim)
        self._remember(fingerprint, remote_issue)
        if created != (len(local_issue.comments) == 0):
            raise RuntimeError("Saga local issue operation result is inconsistent")
        return remote_issue, created

    async def close(self, fingerprint: str, *, closed_by_pr: str) -> None:
        await self._local.close(fingerprint, closed_by_pr=closed_by_pr)
        claim = await self._acquire(fingerprint)
        try:
            remote_issue = await self._remote.ensure_closed(
                fingerprint=fingerprint,
                closed_by_pr=closed_by_pr,
            )
        finally:
            await self._release(fingerprint, claim)
        if remote_issue is not None:
            self._remember(fingerprint, remote_issue)

    async def _acquire(self, fingerprint: str) -> tuple[int, str]:
        key = _lock_key(fingerprint)
        owner = secrets.token_hex(16)
        for _attempt in range(_MAX_CAS_ATTEMPTS):
            now = self._now()
            current = await self._store.read_state(key)
            if current is None:
                value = _lock_state(revision=1, owner=owner, claimed_at=now.isoformat())
                if await self._store.write_state_if_absent(key, value):
                    return 1, owner
                continue
            revision, current_owner, claimed_at = _decode_lock(current)
            if current_owner and now - claimed_at <= _LOCK_LEASE:
                raise RuntimeError("GitHub issue fingerprint mutation is already claimed")
            value = _lock_state(
                revision=revision + 1,
                owner=owner,
                claimed_at=now.isoformat(),
            )
            if await self._store.compare_and_set_state(key, value, expected_revision=revision):
                return revision + 1, owner
        raise RuntimeError("GitHub issue fingerprint claim contention exceeded its bound")

    async def _release(self, fingerprint: str, claim: tuple[int, str]) -> None:
        revision, owner = claim
        key = _lock_key(fingerprint)
        current = await self._store.read_state(key)
        current_revision, current_owner, _claimed_at = _decode_lock(current)
        if current_revision != revision or current_owner != owner:
            return
        await self._store.compare_and_set_state(
            key,
            _lock_state(revision=revision + 1, owner="", claimed_at=""),
            expected_revision=revision,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise RuntimeError("GitHub issue adapter clock MUST be timezone-aware")
        return value.astimezone(UTC)

    def _remember(self, fingerprint: str, issue: GitHubIssue) -> None:
        self._issues[fingerprint] = issue
        self._issues.move_to_end(fingerprint)
        if len(self._issues) > _MAX_ISSUES:
            self._issues.popitem(last=False)


def _validate_remote_request(
    *, fingerprint: str, title: str, body: str, labels: tuple[str, ...]
) -> None:
    if (
        not fingerprint
        or fingerprint != fingerprint.strip()
        or len(fingerprint) > 512
        or not title
        or title != title.strip()
        or len(title) > 512
        or not body
        or len(body) > 20_000
        or _RESERVED_MARKER in body
        or len(labels) > 32
        or any(not label or label != label.strip() or len(label) > 50 for label in labels)
    ):
        raise ValueError("GitHub issue operation request is malformed")


def _request_digest(
    fingerprint: str,
    title: str,
    body: str,
    labels: tuple[str, ...],
) -> str:
    material = json.dumps(
        {
            "fingerprint": fingerprint,
            "title": title,
            "body": body,
            "labels": sorted(labels),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + _sha256(material)


def _project_issue(
    issue: Mapping[str, Any],
    comments: tuple[Mapping[str, Any], ...],
    *,
    fingerprint: str,
) -> GitHubIssue:
    labels_raw = issue.get("labels")
    if not isinstance(labels_raw, list):
        raise RuntimeError("GitHub issue labels were not an array")
    labels: list[str] = []
    for label in labels_raw:
        name = label.get("name") if isinstance(label, Mapping) else label
        if not isinstance(name, str) or not name:
            raise RuntimeError("GitHub issue label was malformed")
        labels.append(name)
    state = issue.get("state")
    if state not in {"open", "closed"}:
        raise RuntimeError("GitHub issue state was invalid")
    return GitHubIssue(
        number=_positive_int(issue.get("number"), "issue number"),
        fingerprint=fingerprint,
        title=_required_text(issue, "title"),
        body=_without_markers(_required_text(issue, "body")),
        labels=labels,
        comments=[_without_markers(_required_text(comment, "body")) for comment in comments],
        open=state == "open",
    )


def _without_markers(value: str) -> str:
    return "\n".join(
        line for line in value.splitlines() if not line.strip().startswith(_RESERVED_MARKER)
    ).rstrip()


def _contains_marker(
    issue: Mapping[str, Any],
    comments: tuple[Mapping[str, Any], ...],
    marker: str,
) -> bool:
    return marker in _required_text(issue, "body") or any(
        marker in _required_text(comment, "body") for comment in comments
    )


def _required_text(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise RuntimeError(f"GitHub issue {field} was invalid")
    return item


def _object_payload(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"GitHub {label} response was not an object")
    return value


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RuntimeError(f"GitHub {label} was invalid")
    return value


def _fingerprint_label(fingerprint_digest: str) -> str:
    return f"fdai:fp:{fingerprint_digest[:40]}"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lock_key(fingerprint: str) -> str:
    return f"{_LOCK_PREFIX}/{_sha256(fingerprint)}"


def _lock_state(*, revision: int, owner: str, claimed_at: str) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "owner": owner,
        "claimed_at": claimed_at,
        "execution_authority": False,
    }


def _decode_lock(value: Mapping[str, Any] | None) -> tuple[int, str, datetime]:
    if value is None:
        raise RuntimeError("GitHub issue fingerprint lock disappeared")
    revision = value.get("revision")
    owner = value.get("owner")
    claimed_at_raw = value.get("claimed_at")
    if (
        set(value) != {"schema_version", "revision", "owner", "claimed_at", "execution_authority"}
        or value.get("schema_version") != "1.0.0"
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or not isinstance(owner, str)
        or not isinstance(claimed_at_raw, str)
        or value.get("execution_authority") is not False
    ):
        raise RuntimeError("GitHub issue fingerprint lock is malformed")
    if not owner and not claimed_at_raw:
        return revision, owner, datetime.min.replace(tzinfo=UTC)
    try:
        claimed_at = datetime.fromisoformat(claimed_at_raw)
    except ValueError as exc:
        raise RuntimeError("GitHub issue fingerprint lock timestamp is invalid") from exc
    if not owner or claimed_at.tzinfo is None:
        raise RuntimeError("GitHub issue fingerprint lock claim is malformed")
    return revision, owner, claimed_at.astimezone(UTC)


__all__ = [
    "GitHubAppIssueTrackerAdapter",
    "GitHubIssueTrackerConfig",
    "GitHubRestIssueClient",
]
