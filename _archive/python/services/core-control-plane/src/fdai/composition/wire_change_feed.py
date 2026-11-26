"""Composition wire - change-feed adapter bindings.

Change-feed (``ChangeFeed`` Protocol) adapters are the read-side deploy /
commit signal that RCA's ``correlate_changes`` grounding reads against an
incident. Every backend (GitHub, Azure DevOps, and future GitLab /
Bitbucket adapters) satisfies the same Protocol so the RCA path never
branches on the source.

Kept out of ``composition/__init__.py`` per the split contract (one
adapter *family* per wire file); the facade re-exports the ``bind_*``
functions for a fork's composition root.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import httpx

from ._helpers import Container

if TYPE_CHECKING:
    from ..delivery.azure_devops.change_feed import AzureDevOpsChangeFeedConfig
    from ..delivery.github.change_feed import GitHubChangeFeedConfig, TokenProvider


def bind_github_change_feed(
    container: Container,
    *,
    config: GitHubChangeFeedConfig,
    http_client: httpx.AsyncClient,
    token_provider: TokenProvider,
) -> Container:
    """Return a new :class:`Container` with a live GitHub change feed in
    place of the default :class:`EmptyChangeFeed`.

    Supplies the read-side deploy/commit signal RCA correlates against an
    incident (``correlate_changes``). Dev / local-fake runs keep the empty
    default so no GitHub call is made and the parity contract holds.
    """
    from ..delivery.github.change_feed import GitHubChangeFeed

    feed = GitHubChangeFeed(
        config=config,
        http_client=http_client,
        token_provider=token_provider,
    )
    return replace(container, change_feed=feed)


def bind_azure_devops_change_feed(
    container: Container,
    *,
    config: AzureDevOpsChangeFeedConfig,
    http_client: httpx.AsyncClient,
    token_provider: TokenProvider,
) -> Container:
    """Return a new :class:`Container` with a live Azure DevOps change feed
    in place of the default :class:`EmptyChangeFeed`.

    The Azure DevOps counterpart to :func:`bind_github_change_feed`: both
    satisfy the same :class:`~fdai.shared.providers.change_feed.ChangeFeed`
    Protocol, so RCA's ``correlate_changes`` grounding works identically
    whichever VCS a fork runs. Dev / local-fake runs keep the empty default
    so no Azure DevOps call is made and the parity contract holds.
    """
    from ..delivery.azure_devops.change_feed import AzureDevOpsChangeFeed

    feed = AzureDevOpsChangeFeed(
        config=config,
        http_client=http_client,
        token_provider=token_provider,
    )
    return replace(container, change_feed=feed)


__all__ = [
    "bind_azure_devops_change_feed",
    "bind_github_change_feed",
]
