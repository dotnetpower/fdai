from __future__ import annotations

import base64
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime

import httpx
import pytest
from fdai.delivery.github.skill_source import (
    GitHubSkillSourceAdapter,
    GitHubSkillSourceError,
)
from fdai.shared.providers.skill_source import SkillSourceRateLimitError

NOW = datetime(2026, 8, 14, 6, 0, tzinfo=UTC)
REVISION = "a" * 40


async def _token() -> str:
    return "test-token"  # noqa: S105 - synthetic test credential


def _adapter(
    handler: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
) -> tuple[GitHubSkillSourceAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        GitHubSkillSourceAdapter(
            http_client=client,
            token_provider=_token,
            clock=lambda: NOW,
        ),
        client,
    )


def _file(path: str, raw: bytes, **changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "type": "file",
        "path": path,
        "size": len(raw),
        "encoding": "base64",
        "content": base64.b64encode(raw).decode(),
    }
    result.update(changes)
    return result


async def test_resolve_revision_uses_auth_etag_and_full_commit_sha() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"etag": '"v2"'}, json={"sha": REVISION})

    adapter, client = _adapter(handler)
    try:
        result = await adapter.resolve_revision(
            repository="example-org/skills",
            prior_etag='"v1"',
        )
    finally:
        await client.aclose()

    assert result.revision == REVISION
    assert result.etag == '"v2"'
    assert seen[0].url.path.endswith("/repos/example-org/skills/commits/HEAD")
    assert seen[0].headers["authorization"] == "Bearer test-token"
    assert seen[0].headers["if-none-match"] == '"v1"'


async def test_resolve_revision_preserves_etag_on_not_modified() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(304)

    adapter, client = _adapter(handler)
    try:
        result = await adapter.resolve_revision(
            repository="example-org/skills",
            prior_etag='"v1"',
        )
    finally:
        await client.aclose()

    assert result.not_modified is True
    assert result.revision is None
    assert result.etag == '"v1"'


async def test_resolve_revision_rejects_nonimmutable_ref() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sha": "main"})

    adapter, client = _adapter(handler)
    try:
        with pytest.raises(GitHubSkillSourceError, match="full commit SHA"):
            await adapter.resolve_revision(repository="example-org/skills")
    finally:
        await client.aclose()


async def test_fetch_files_preserves_order_and_exact_content() -> None:
    requested = {
        "skills/example/SKILL.md": b"---\nname: example\n---\n",
        "skills/example/SKILL.md.sig": bytes(range(64)),
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/contents/", 1)[1]
        assert request.url.params["ref"] == REVISION
        return httpx.Response(200, json=_file(path, requested[path]))

    adapter, client = _adapter(handler)
    try:
        result = await adapter.fetch_files(
            repository="example-org/skills",
            revision=REVISION,
            paths=tuple(requested),
        )
    finally:
        await client.aclose()

    assert tuple(item.path for item in result) == tuple(requested)
    assert tuple(item.content for item in result) == tuple(requested.values())
    assert result[0].media_type == "text/markdown"


@pytest.mark.parametrize("kind", ("symlink", "submodule", "dir"))
async def test_fetch_files_rejects_non_regular_content(kind: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_file("skills/example/SKILL.md", b"valid", type=kind))

    adapter, client = _adapter(handler)
    try:
        with pytest.raises(GitHubSkillSourceError, match="regular file"):
            await adapter.fetch_files(
                repository="example-org/skills",
                revision=REVISION,
                paths=("skills/example/SKILL.md",),
            )
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        (_file("substituted/SKILL.md", b"valid"), "path does not match"),
        (_file("skills/example/SKILL.md", b"valid", size=300_000), "size"),
        (_file("skills/example/SKILL.md", b"valid", content="not-base64"), "base64"),
        (_file("skills/example/SKILL.md", b"valid", size=4), "decoded size"),
        (_file("skills/example/SKILL.md", b"\xff"), "UTF-8"),
    ),
)
async def test_fetch_files_rejects_substituted_or_malformed_content(
    payload: dict[str, object],
    message: str,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter, client = _adapter(handler)
    try:
        with pytest.raises(GitHubSkillSourceError, match=message):
            await adapter.fetch_files(
                repository="example-org/skills",
                revision=REVISION,
                paths=("skills/example/SKILL.md",),
            )
    finally:
        await client.aclose()


async def test_fetch_files_rejects_invalid_signature_length() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_file("skills/example/SKILL.md.sig", b"short"))

    adapter, client = _adapter(handler)
    try:
        with pytest.raises(GitHubSkillSourceError, match="64 bytes"):
            await adapter.fetch_files(
                repository="example-org/skills",
                revision=REVISION,
                paths=("skills/example/SKILL.md.sig",),
            )
    finally:
        await client.aclose()


async def test_fetch_files_rejects_partial_response_without_returning_files() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        path = request.url.path.split("/contents/", 1)[1]
        if calls == 2:
            return httpx.Response(404)
        return httpx.Response(200, json=_file(path, b"first"))

    adapter, client = _adapter(handler)
    try:
        with pytest.raises(GitHubSkillSourceError, match="HTTP 404"):
            await adapter.fetch_files(
                repository="example-org/skills",
                revision=REVISION,
                paths=("skills/example/SKILL.md", "skills/example/reference.md"),
            )
    finally:
        await client.aclose()
    assert calls == 2


async def test_fetch_files_rejects_aggregate_overflow() -> None:
    content = b"a" * (256 * 1024)

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/contents/", 1)[1]
        return httpx.Response(200, json=_file(path, content))

    adapter, client = _adapter(handler)
    try:
        with pytest.raises(GitHubSkillSourceError, match="total size"):
            await adapter.fetch_files(
                repository="example-org/skills",
                revision=REVISION,
                paths=tuple(f"skills/example/reference-{index}.md" for index in range(5)),
            )
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "paths",
    (
        (),
        ("../SKILL.md",),
        ("skills/example/SKILL.md", "skills/example/SKILL.md"),
    ),
)
async def test_fetch_files_rejects_unbounded_or_unsafe_paths(paths: tuple[str, ...]) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid paths MUST fail before HTTP")

    adapter, client = _adapter(handler)
    try:
        with pytest.raises(ValueError):
            await adapter.fetch_files(
                repository="example-org/skills",
                revision=REVISION,
                paths=paths,
            )
    finally:
        await client.aclose()


async def test_redirect_is_rejected_without_following() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"location": "https://example.com/redirect"})

    adapter, client = _adapter(handler)
    try:
        with pytest.raises(GitHubSkillSourceError, match="redirects"):
            await adapter.resolve_revision(repository="example-org/skills")
    finally:
        await client.aclose()
    assert calls == 1


async def test_rate_limit_preserves_server_reset_time() -> None:
    reset = int(NOW.timestamp()) + 300

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)},
        )

    adapter, client = _adapter(handler)
    try:
        with pytest.raises(SkillSourceRateLimitError) as raised:
            await adapter.resolve_revision(repository="example-org/skills")
    finally:
        await client.aclose()
    assert raised.value.retry_at == datetime.fromtimestamp(reset, tz=UTC)


async def test_authentication_failure_is_redacted() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="test-token private response")

    adapter, client = _adapter(handler)
    try:
        with pytest.raises(GitHubSkillSourceError) as raised:
            await adapter.resolve_revision(repository="example-org/skills")
    finally:
        await client.aclose()
    assert "test-token" not in str(raised.value)
    assert "private response" not in str(raised.value)
