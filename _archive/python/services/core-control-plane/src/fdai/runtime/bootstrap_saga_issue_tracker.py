"""Select Saga's local or verified GitHub App issue delivery adapter."""

from __future__ import annotations

from collections.abc import Mapping

import httpx
from fdai_github_app_auth import GitHubAppTokenProvider

from fdai.agents import IssueTrackerAdapter, Saga, StateStoreIssueTrackerAdapter
from fdai.delivery.github_issue_tracker import (
    GitHubAppIssueTrackerAdapter,
    GitHubIssueTrackerConfig,
    GitHubRestIssueClient,
)
from fdai.runtime.bootstrap_lifecycle import build_runtime_saga
from fdai.runtime.github_auth import build_github_token_provider
from fdai.shared.providers.state_store import StateStore

_ENABLED_ENV = "FDAI_SAGA_GITHUB_ISSUES_ENABLED"
_OWNER_ENV = "FDAI_SAGA_GITHUB_OWNER"
_REPO_ENV = "FDAI_SAGA_GITHUB_REPO"
_REQUIRED_PERMISSIONS = (("issues", "write"), ("metadata", "read"))


async def build_saga_issue_tracker(
    *,
    environment: Mapping[str, str],
    store: StateStore,
    http_client: httpx.AsyncClient | None,
) -> IssueTrackerAdapter:
    """Return local storage by default or an exact GitHub App binding when opted in."""

    enabled = environment.get(_ENABLED_ENV, "").strip().lower()
    if enabled not in {"", "0", "false", "no", "off", "1", "true", "yes", "on"}:
        raise RuntimeError(f"{_ENABLED_ENV} MUST be a boolean")
    if enabled in {"", "0", "false", "no", "off"}:
        return StateStoreIssueTrackerAdapter(store)
    owner = environment.get(_OWNER_ENV, "").strip()
    repo = environment.get(_REPO_ENV, "").strip()
    if not owner or not repo:
        raise RuntimeError("Saga GitHub issue delivery requires owner and repository")
    if http_client is None:
        raise RuntimeError("Saga GitHub issue delivery requires an HTTP client")
    provider = build_github_token_provider(
        environment,
        http_client=http_client,
        repository=repo,
        permissions=_REQUIRED_PERMISSIONS,
    )
    if not isinstance(provider, GitHubAppTokenProvider):
        raise RuntimeError("Saga GitHub issue delivery requires refreshable GitHub App credentials")
    api_base = (
        environment.get("FDAI_GITOPS_API_BASE", "https://api.github.com").strip()
        or "https://api.github.com"
    )
    await _verify_repository(
        provider=provider,
        http_client=http_client,
        owner=owner,
        repo=repo,
        api_base=api_base,
    )
    remote = GitHubRestIssueClient(
        config=GitHubIssueTrackerConfig(owner=owner, repo=repo, api_base=api_base),
        http_client=http_client,
        token_provider=provider,
    )
    return GitHubAppIssueTrackerAdapter(store=store, remote=remote)


async def build_saga_runtime(
    *,
    environment: Mapping[str, str],
    store: StateStore,
    http_client: httpx.AsyncClient | None,
) -> Saga:
    issue_tracker = await build_saga_issue_tracker(
        environment=environment,
        store=store,
        http_client=http_client,
    )
    return build_runtime_saga(store, issue_tracker=issue_tracker)


async def _verify_repository(
    *,
    provider: GitHubAppTokenProvider,
    http_client: httpx.AsyncClient,
    owner: str,
    repo: str,
    api_base: str,
) -> None:
    projection = await provider.projection()
    if (
        projection.repository != repo
        or projection.repository_selection != "selected"
        or projection.permissions != _REQUIRED_PERMISSIONS
    ):
        raise RuntimeError("Saga GitHub App token projection differs")
    token = await provider()
    try:
        response = await http_client.get(
            f"{api_base.rstrip('/')}/installation/repositories",
            params={"per_page": "100"},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError("Saga GitHub App repository readback failed") from exc
    if response.status_code != 200:
        raise RuntimeError("Saga GitHub App repository readback was rejected")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Saga GitHub App repository readback was not JSON") from exc
    repositories = payload.get("repositories") if isinstance(payload, dict) else None
    full_name = f"{owner}/{repo}".casefold()
    if (
        not isinstance(repositories, list)
        or len(repositories) != 1
        or not isinstance(repositories[0], dict)
        or str(repositories[0].get("full_name", "")).casefold() != full_name
        or str(repositories[0].get("name", "")).casefold() != repo.casefold()
    ):
        raise RuntimeError("Saga GitHub App repository projection differs")


__all__ = ["build_saga_issue_tracker", "build_saga_runtime"]
