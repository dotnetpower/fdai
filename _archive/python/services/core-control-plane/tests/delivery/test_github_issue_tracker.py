from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fdai.delivery.github_issue_tracker import (
    GitHubAppIssueTrackerAdapter,
    GitHubIssueTrackerConfig,
    GitHubRestIssueClient,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _GitHubServer:
    def __init__(self) -> None:
        self.issues: dict[int, dict[str, Any]] = {}
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self.comment_index: dict[int, dict[str, Any]] = {}
        self.next_issue = 1
        self.next_comment = 100
        self.authorization_headers: list[str] = []
        self.fail_issue_read_once = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.authorization_headers.append(request.headers.get("Authorization", ""))
        path = request.url.path
        if request.method == "GET" and path == "/repos/example/fdai/issues":
            label = request.url.params.get("labels")
            issues = [
                issue
                for issue in self.issues.values()
                if any(item["name"] == label for item in issue["labels"])
            ]
            return httpx.Response(200, json=issues)
        if request.method == "POST" and path == "/repos/example/fdai/issues":
            payload = json.loads(request.content)
            number = self.next_issue
            self.next_issue += 1
            issue = {
                "number": number,
                "title": payload["title"],
                "body": payload["body"],
                "labels": [{"name": label} for label in payload["labels"]],
                "state": "open",
            }
            self.issues[number] = issue
            self.comments[number] = []
            return httpx.Response(201, json=issue)
        parts = path.split("/")
        if len(parts) == 6 and parts[:5] == ["", "repos", "example", "fdai", "issues"]:
            number = int(parts[5])
            if request.method == "GET":
                if self.fail_issue_read_once:
                    self.fail_issue_read_once = False
                    return httpx.Response(503, json={"message": "temporary readback failure"})
                return httpx.Response(200, json=self.issues[number])
            if request.method == "PATCH":
                payload = json.loads(request.content)
                self.issues[number]["state"] = payload["state"]
                return httpx.Response(200, json=self.issues[number])
        if (
            len(parts) == 7
            and parts[:5] == ["", "repos", "example", "fdai", "issues"]
            and parts[6] == "comments"
        ):
            number = int(parts[5])
            if request.method == "GET":
                return httpx.Response(200, json=self.comments[number])
            if request.method == "POST":
                payload = json.loads(request.content)
                comment = {"id": self.next_comment, "body": payload["body"]}
                self.next_comment += 1
                self.comments[number].append(comment)
                self.comment_index[comment["id"]] = comment
                return httpx.Response(201, json=comment)
        if (
            request.method == "GET"
            and len(parts) == 7
            and parts[:6] == ["", "repos", "example", "fdai", "issues", "comments"]
        ):
            return httpx.Response(200, json=self.comment_index[int(parts[6])])
        return httpx.Response(404, json={"message": "not found"})


async def _token() -> str:
    return "installation-token"


def _adapter(
    server: _GitHubServer,
    store: InMemoryStateStore,
) -> tuple[GitHubAppIssueTrackerAdapter, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(server.handle))
    remote = GitHubRestIssueClient(
        config=GitHubIssueTrackerConfig(owner="example", repo="fdai"),
        http_client=http,
        token_provider=_token,
    )
    return GitHubAppIssueTrackerAdapter(store=store, remote=remote), http


async def test_remote_issue_operations_replay_exact_readback_across_restart() -> None:
    server = _GitHubServer()
    store = InMemoryStateStore()
    adapter, http = _adapter(server, store)
    try:
        created_issue, created = await adapter.create_or_comment_once(
            operation_id="handoff:operation-1",
            fingerprint="a" * 64,
            title="[incident] Saga handoff",
            body="First bounded handoff.",
            labels=("review-needed",),
        )
        replay_issue, replay_created = await adapter.create_or_comment_once(
            operation_id="handoff:operation-1",
            fingerprint="a" * 64,
            title="[incident] Saga handoff",
            body="First bounded handoff.",
            labels=("review-needed",),
        )
        commented_issue, comment_created = await adapter.create_or_comment_once(
            operation_id="handoff:operation-2",
            fingerprint="a" * 64,
            title="[incident] Saga handoff",
            body="Second bounded handoff.",
            labels=("review-needed",),
        )
        await adapter.close("a" * 64, closed_by_pr="https://example.com/pull/7")

        restarted, restarted_http = _adapter(server, store)
        try:
            assert await restarted.rehydrate() == 1
            restored = restarted.issues["a" * 64]
        finally:
            await restarted_http.aclose()
    finally:
        await http.aclose()

    assert created is replay_created is True
    assert created_issue.number == replay_issue.number == commented_issue.number == 1
    assert comment_created is False
    assert "Second bounded handoff." in commented_issue.comments
    assert restored.open is False
    assert all(header == "Bearer installation-token" for header in server.authorization_headers)
    assert len(server.issues) == 1


async def test_remote_operation_id_rejects_changed_label_content() -> None:
    server = _GitHubServer()
    store = InMemoryStateStore()
    adapter, http = _adapter(server, store)
    try:
        await adapter.create_or_comment_once(
            operation_id="handoff:collision",
            fingerprint="b" * 64,
            title="[incident] Saga handoff",
            body="Bounded handoff.",
            labels=("review-needed",),
        )
        with pytest.raises(ValueError, match="different content"):
            await adapter.create_or_comment_once(
                operation_id="handoff:collision",
                fingerprint="b" * 64,
                title="[incident] Saga handoff",
                body="Bounded handoff.",
                labels=("completed",),
            )
    finally:
        await http.aclose()

    assert len(server.issues) == 1


async def test_remote_create_readback_failure_retries_without_duplicate_issue() -> None:
    server = _GitHubServer()
    server.fail_issue_read_once = True
    store = InMemoryStateStore()
    adapter, http = _adapter(server, store)
    try:
        with pytest.raises(RuntimeError, match="HTTP 503"):
            await adapter.create_or_comment_once(
                operation_id="handoff:ambiguous-create",
                fingerprint="c" * 64,
                title="[incident] Saga handoff",
                body="Ambiguous bounded handoff.",
                labels=("review-needed",),
            )

        issue, created = await adapter.create_or_comment_once(
            operation_id="handoff:ambiguous-create",
            fingerprint="c" * 64,
            title="[incident] Saga handoff",
            body="Ambiguous bounded handoff.",
            labels=("review-needed",),
        )
    finally:
        await http.aclose()

    assert created is True
    assert issue.number == 1
    assert len(server.issues) == 1
