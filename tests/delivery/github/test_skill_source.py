from __future__ import annotations

import base64
from datetime import UTC, datetime

import httpx
import pytest

from fdai.delivery.github.skill_source import (
    GitHubSkillSourceAdapter,
    GitHubSkillSourceConfig,
    GitHubSkillSourceError,
)
from fdai.shared.providers.skill_source import SkillSourceRateLimitError

REVISION = "a" * 40


async def _token() -> str:
    return "secret-token"


def _adapter(handler) -> tuple[GitHubSkillSourceAdapter, httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        GitHubSkillSourceAdapter(
            config=GitHubSkillSourceConfig(),
            http_client=client,
            token_provider=_token,
        ),
        client,
    )


async def test_resolves_commit_with_etag_without_logging_credentials() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["authorization"]
        return httpx.Response(200, json={"sha": REVISION}, headers={"etag": '"v1"'})

    adapter, client = _adapter(handler)
    async with client:
        resolved = await adapter.resolve_revision(repository="example-org/skills")

    assert resolved.revision == REVISION
    assert resolved.etag == '"v1"'
    assert captured["authorization"] == "Bearer secret-token"


async def test_fetches_only_explicit_files_at_immutable_revision() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/contents/", 1)[1]
        requested.append(path)
        assert request.url.params["ref"] == REVISION
        content = f"content:{path}".encode()
        return httpx.Response(
            200,
            json={
                "type": "file",
                "path": path,
                "encoding": "base64",
                "content": base64.b64encode(content).decode(),
            },
        )

    adapter, client = _adapter(handler)
    async with client:
        files = await adapter.fetch_files(
            repository="example-org/skills",
            revision=REVISION,
            paths=("skills/example/SKILL.md", "skills/example/guide.txt"),
        )

    assert requested == ["skills/example/SKILL.md", "skills/example/guide.txt"]
    assert files[0].content == b"content:skills/example/SKILL.md"


@pytest.mark.parametrize("status", (302, 403))
async def test_redirect_or_auth_failure_has_no_partial_result(status: int) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"location": "https://example.com/other"})

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(GitHubSkillSourceError):
            await adapter.fetch_files(
                repository="example-org/skills",
                revision=REVISION,
                paths=("skills/example/SKILL.md",),
            )


async def test_symlink_or_path_mismatch_is_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"type": "symlink", "path": "other"})

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(GitHubSkillSourceError, match="non-file"):
            await adapter.fetch_files(
                repository="example-org/skills",
                revision=REVISION,
                paths=("skills/example/SKILL.md",),
            )


@pytest.mark.parametrize("path", ("../SKILL.md", "/SKILL.md", "skills\\SKILL.md"))
async def test_unsafe_path_rejected_before_auth_or_http(path: str) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(ValueError, match="safe relative path"):
            await adapter.fetch_files(
                repository="example-org/skills",
                revision=REVISION,
                paths=(path,),
            )
    assert calls == 0


async def test_rate_limit_exposes_server_retry_time_without_token() -> None:
    reset = 1_800_000_000

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)},
        )

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(SkillSourceRateLimitError) as caught:
            await adapter.resolve_revision(repository="example-org/skills")

    assert caught.value.retry_at == datetime.fromtimestamp(reset, tz=UTC)
    assert "secret-token" not in str(caught.value)
