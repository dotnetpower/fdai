"""Exact GitHub merge source verification through synthetic HTTP only."""

from __future__ import annotations

import base64
import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fdai.delivery.identity.scoped_duty_merge import GitHubScopedDutyMergeReader

AT = datetime(2026, 9, 14, 12, tzinfo=UTC)
PATH = "config/scoped-duty-plans/00000000-0000-0000-0000-000000000001.json"
CONTENT = b'{"kind":"reviewed_scoped_duty_plan"}\n'
DIGEST = hashlib.sha256(CONTENT).hexdigest()


def values():
    return {
        "pr": {
            "merged": True,
            "draft": False,
            "base": {"ref": "main", "repo": {"full_name": "example/repo"}},
            "head": {"sha": "b" * 40},
            "merge_commit_sha": "a" * 40,
            "user": {"login": "example-app", "type": "Bot"},
            "merged_by": {"login": "human-merger", "type": "User"},
        },
        "reviews": [
            {
                "user": {"login": "human-reviewer", "type": "User"},
                "state": "APPROVED",
                "commit_id": "b" * 40,
            }
        ],
        "file": {
            "type": "file",
            "path": PATH,
            "encoding": "base64",
            "content": base64.b64encode(CONTENT).decode(),
        },
    }


async def observe(data, *, clock=None, requests=None):
    def handler(request):
        if requests is not None:
            requests.append(request)
        assert request.method == "GET" and request.url.host == "api.github.com"
        if request.url.path.endswith("/reviews"):
            return httpx.Response(200, json=data["reviews"])
        if "/contents/" in request.url.path:
            return httpx.Response(
                200,
                json=(
                    data.get("current_file", data["file"])
                    if request.url.params["ref"] == "main"
                    else data["file"]
                ),
            )
        return httpx.Response(200, json=data["pr"])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = GitHubScopedDutyMergeReader(
            client,
            AsyncMock(return_value="synthetic"),
            "example/repo",
            "main",
            clock or (lambda: AT),
        )
        return await reader.read(pr_ref="example/repo#7", path=PATH, candidate_digest=DIGEST)


async def test_current_reviewed_merge_checks_both_commit_and_current_source():
    requests = []
    receipt = await observe(values(), requests=requests)
    assert receipt is not None and receipt.merge_commit_sha == "a" * 40
    assert receipt.expires_at == AT + timedelta(seconds=60)
    assert len(requests) == 4
    assert requests[-1].url.params["ref"] == "main"
    assert requests[-2].url.params["ref"] == "a" * 40


@pytest.mark.parametrize(
    "case",
    ["unmerged", "draft", "bot_merge", "self_merge", "wrong_repo", "wrong_branch", "wrong_sha"],
)
async def test_unreviewed_or_wrong_merge_cannot_be_an_effect(case):
    data = values()
    if case == "unmerged":
        data["pr"]["merged"] = False
    elif case == "draft":
        data["pr"]["draft"] = True
    elif case == "bot_merge":
        data["pr"]["merged_by"]["type"] = "Bot"
    elif case == "self_merge":
        data["pr"]["merged_by"]["login"] = data["pr"]["user"]["login"]
    elif case == "wrong_repo":
        data["pr"]["base"]["repo"]["full_name"] = "example/other"
    elif case == "wrong_branch":
        data["pr"]["base"]["ref"] = "unreviewed"
    else:
        data["pr"]["merge_commit_sha"] = "unverified"
    assert await observe(data) is None


@pytest.mark.parametrize(
    "case", ["missing", "bot", "self", "wrong_head", "dismissed", "changes_requested", "partial"]
)
async def test_only_current_independent_human_review_counts(case):
    data = values()
    if case == "missing":
        data["reviews"] = []
    elif case == "bot":
        data["reviews"][0]["user"]["type"] = "Bot"
    elif case == "self":
        data["reviews"][0]["user"]["login"] = data["pr"]["user"]["login"]
    elif case == "wrong_head":
        data["reviews"][0]["commit_id"] = "c" * 40
    elif case in {"dismissed", "changes_requested"}:
        later = deepcopy(data["reviews"][0])
        later["state"] = case.upper()
        data["reviews"].append(later)
    else:
        data["reviews"] *= 100
    assert await observe(data) is None


@pytest.mark.parametrize("which", ["file", "current_file"])
async def test_changed_or_withdrawn_artifact_at_either_source_is_not_ownership(which):
    data = values()
    data[which] = {**data["file"], "content": base64.b64encode(b"changed").decode()}
    assert await observe(data) is None


@pytest.mark.parametrize("finish", [AT - timedelta(seconds=1), AT + timedelta(seconds=60)])
async def test_merge_read_cannot_outlive_its_evidence_window(finish):
    assert await observe(values(), clock=Mock(side_effect=[AT, finish])) is None


async def test_wrong_target_is_rejected_before_credentials_or_http():
    token = AsyncMock(return_value="synthetic")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: pytest.fail("unexpected HTTP"))
    ) as client:
        reader = GitHubScopedDutyMergeReader(client, token, "example/repo", "main", lambda: AT)
        for pr, path in (
            ("example/other#7", PATH),
            ("example/repo#7", "config/agent-stewardship.yaml"),
        ):
            with pytest.raises(ValueError):
                await reader.read(pr_ref=pr, path=path, candidate_digest=DIGEST)
    token.assert_not_awaited()


@pytest.mark.parametrize("status", [301, 429, 503])
async def test_source_failure_never_retries_redirects_or_leaks_body(status):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            status, text="private diagnostic", headers={"Location": "https://example.com"}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        reader = GitHubScopedDutyMergeReader(
            client, AsyncMock(return_value="synthetic"), "example/repo", "main", lambda: AT
        )
        with pytest.raises(ValueError) as caught:
            await reader.read(pr_ref="example/repo#7", path=PATH, candidate_digest=DIGEST)
    assert len(seen) == 1 and "private" not in str(caught.value)
