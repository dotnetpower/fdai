"""Verify the protected GitHub App installation and repository projection."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import quote

import httpx
from fdai_github_app_auth import GitHubAppTokenProvider

_REQUIRED_PERMISSIONS = (
    ("contents", "write"),
    ("issues", "write"),
    ("metadata", "read"),
    ("pull_requests", "write"),
)


async def verify_catalog_review_github_app(
    *,
    provider: GitHubAppTokenProvider,
    http_client: httpx.AsyncClient,
    owner: str,
    repo: str,
    api_base: str,
) -> str:
    """Return a content digest only after provider scope and repository readback."""

    projection = await provider.projection()
    if (
        projection.repository != repo
        or projection.repository_selection != "selected"
        or projection.permissions != _REQUIRED_PERMISSIONS
    ):
        raise RuntimeError("catalog review GitHub App token projection differs")
    token = await provider()
    url = f"{api_base.rstrip('/')}/installation/repositories?per_page=100"
    try:
        response = await http_client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError("catalog review GitHub App repository readback failed") from exc
    if response.status_code != 200:
        raise RuntimeError("catalog review GitHub App repository readback was rejected")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("catalog review GitHub App repository readback was not JSON") from exc
    repositories = payload.get("repositories") if isinstance(payload, dict) else None
    expected_full_name = f"{owner}/{repo}".casefold()
    if (
        not isinstance(repositories, list)
        or len(repositories) != 1
        or not isinstance(repositories[0], dict)
        or str(repositories[0].get("full_name", "")).casefold() != expected_full_name
        or str(repositories[0].get("name", "")).casefold() != repo.casefold()
    ):
        raise RuntimeError("catalog review GitHub App repository projection differs")
    material = {
        "installation_id": projection.installation_id,
        "owner": owner,
        "repo": repo,
        "repository_selection": projection.repository_selection,
        "permissions": list(projection.permissions),
        "repository_id_digest": hashlib.sha256(
            str(repositories[0].get("id", "")).encode()
        ).hexdigest(),
        "repository_path_digest": hashlib.sha256(
            quote(expected_full_name, safe="").encode()
        ).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(material, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


__all__ = ["verify_catalog_review_github_app"]
