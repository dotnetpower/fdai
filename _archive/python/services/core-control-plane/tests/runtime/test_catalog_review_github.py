from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.runtime.catalog_review_github import verify_catalog_review_github_app
from fdai_github_app_auth import GitHubAppTokenProjection

_PERMISSIONS = (
    ("contents", "write"),
    ("issues", "write"),
    ("metadata", "read"),
    ("pull_requests", "write"),
)


class _Provider:
    def __init__(
        self,
        *,
        repository: str = "catalog",
        permissions: tuple[tuple[str, str], ...] = _PERMISSIONS,
    ) -> None:
        self._projection = GitHubAppTokenProjection(
            installation_id=42,
            repository=repository,
            repository_selection="selected",
            permissions=permissions,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    async def __call__(self) -> str:
        return "installation-token"

    async def projection(self) -> GitHubAppTokenProjection:
        return self._projection


async def test_catalog_review_verifies_exact_app_repository() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"repositories": [{"id": 7, "name": "catalog", "full_name": "example/catalog"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        digest = await verify_catalog_review_github_app(
            provider=_Provider(),  # type: ignore[arg-type]
            http_client=client,
            owner="example",
            repo="catalog",
            api_base="https://api.github.test",
        )

    assert len(digest) == 64


@pytest.mark.parametrize(
    ("provider", "repositories", "message"),
    [
        (
            _Provider(repository="other"),
            [{"id": 7, "name": "catalog", "full_name": "example/catalog"}],
            "token projection differs",
        ),
        (
            _Provider(permissions=(("contents", "read"),)),
            [{"id": 7, "name": "catalog", "full_name": "example/catalog"}],
            "token projection differs",
        ),
        (
            _Provider(),
            [{"id": 8, "name": "other", "full_name": "example/other"}],
            "repository projection differs",
        ),
    ],
)
async def test_catalog_review_rejects_wrong_app_projection(
    provider: _Provider,
    repositories: list[dict[str, object]],
    message: str,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"repositories": repositories})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match=message):
            await verify_catalog_review_github_app(
                provider=provider,  # type: ignore[arg-type]
                http_client=client,
                owner="example",
                repo="catalog",
                api_base="https://api.github.test",
            )
