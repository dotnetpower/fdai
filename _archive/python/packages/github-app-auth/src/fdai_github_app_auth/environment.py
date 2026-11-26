"""Resolve one GitHub token provider from deployment-owned environment values."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from fdai_github_app_auth.provider import (
    GitHubAppTokenConfig,
    GitHubAppTokenError,
    GitHubAppTokenProvider,
    TokenProvider,
    static_token_provider,
)

_APP_KEYS = (
    "FDAI_GITHUB_APP_CLIENT_ID",
    "FDAI_GITHUB_APP_INSTALLATION_ID",
    "FDAI_GITHUB_APP_PRIVATE_KEY",
)


def _credential_values(
    environment: Mapping[str, str],
) -> tuple[str, dict[str, str], list[str]]:
    static_token = environment.get("FDAI_GITOPS_TOKEN", "").strip()
    app_values = {key: environment.get(key, "").strip() for key in _APP_KEYS}
    app_configured = [key for key, value in app_values.items() if value]
    if static_token and app_configured:
        raise GitHubAppTokenError(
            "FDAI_GITOPS_TOKEN is mutually exclusive with GitHub App credentials"
        )
    if app_configured and len(app_configured) != len(_APP_KEYS):
        missing = sorted(set(_APP_KEYS) - set(app_configured))
        raise GitHubAppTokenError("GitHub App environment is incomplete: " + ", ".join(missing))
    return static_token, app_values, app_configured


def github_credentials_configured(environment: Mapping[str, str]) -> bool:
    """Return whether one complete, mutually exclusive GitHub credential set exists."""

    static_token, _, app_configured = _credential_values(environment)
    return bool(static_token or app_configured)


def build_github_token_provider(
    environment: Mapping[str, str],
    *,
    http_client: httpx.AsyncClient,
    repository: str,
    permissions: tuple[tuple[str, str], ...] | None = None,
) -> TokenProvider | None:
    """Build one static compatibility or refreshable GitHub App token provider."""

    static_token, app_values, app_configured = _credential_values(environment)
    if static_token:
        return static_token_provider(static_token)
    if not app_configured:
        return None
    try:
        installation_id = int(app_values["FDAI_GITHUB_APP_INSTALLATION_ID"])
    except ValueError as exc:
        raise GitHubAppTokenError("FDAI_GITHUB_APP_INSTALLATION_ID MUST be an integer") from exc
    config = GitHubAppTokenConfig(
        client_id=app_values["FDAI_GITHUB_APP_CLIENT_ID"],
        installation_id=installation_id,
        private_key_pem=app_values["FDAI_GITHUB_APP_PRIVATE_KEY"],
        repository=repository,
        api_base=(
            environment.get("FDAI_GITOPS_API_BASE", "https://api.github.com").strip()
            or "https://api.github.com"
        ),
    )
    if permissions is not None:
        config = GitHubAppTokenConfig(
            client_id=config.client_id,
            installation_id=config.installation_id,
            private_key_pem=config.private_key_pem,
            repository=config.repository,
            permissions=permissions,
            api_base=config.api_base,
        )
    return GitHubAppTokenProvider(
        config=config,
        http_client=http_client,
    )


__all__ = ["build_github_token_provider", "github_credentials_configured"]
