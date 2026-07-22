"""Production composition for stewardship governance delivery."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx

from fdai.core.notifications import NotificationRouter, load_matrix_from_yaml
from fdai.core.notifications.router import ChannelRegistry
from fdai.core.stewardship import load_stewardship_from_yaml
from fdai.delivery.gitops_pr import GitOpsPrAdapter, GitOpsPrConfig
from fdai.delivery.notifications import (
    StateStoreHilEscalationSink,
    TeamsWebhookChannel,
    TeamsWebhookConfig,
)
from fdai.delivery.stewardship.github_webhook import (
    GitHubStewardshipWebhook,
    GitHubStewardshipWebhookConfig,
)
from fdai.delivery.stewardship.governance import StewardshipGovernanceService
from fdai.shared.providers.notifications.base import NotificationChannel, TrustTier
from fdai.shared.providers.state_store import StateStore

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_REQUIRED_ENV = (
    "FDAI_GITOPS_TOKEN",
    "FDAI_GITOPS_OWNER",
    "FDAI_GITOPS_REPO",
    "FDAI_GITHUB_WEBHOOK_SECRET",
    "FDAI_CHATOPS_WEBHOOK_URL",
)


class StewardshipGovernanceConfigError(ValueError):
    """Raised when production stewardship governance is partially configured."""


@dataclass(frozen=True, slots=True)
class ProductionStewardshipGovernance:
    service: StewardshipGovernanceService
    webhook: GitHubStewardshipWebhook


def build_production_stewardship_governance(
    *,
    env: Mapping[str, str],
    repo_root: Path,
    http_client: httpx.AsyncClient,
    state_store: StateStore,
) -> ProductionStewardshipGovernance | None:
    """Compose governance delivery when explicitly enabled."""
    enabled = env.get("FDAI_STEWARDSHIP_GOVERNANCE_ENABLED", "").strip().casefold() in _TRUTHY
    if not enabled:
        return None
    missing = [name for name in _REQUIRED_ENV if not env.get(name, "").strip()]
    if missing:
        raise StewardshipGovernanceConfigError(
            "stewardship governance environment is missing: " + ", ".join(missing)
        )
    token = env["FDAI_GITOPS_TOKEN"].strip()
    owner = env["FDAI_GITOPS_OWNER"].strip()
    repo = env["FDAI_GITOPS_REPO"].strip()
    api_base = env.get("FDAI_GITOPS_API_BASE", "https://api.github.com").strip()
    timeout = _positive_float(env, "FDAI_GITOPS_TIMEOUT_SECONDS", 15.0)
    current_map = load_stewardship_from_yaml(
        repo_root / "config" / "agent-stewardship.yaml",
        environ=env,
    )
    notifications = NotificationRouter(
        matrix=load_matrix_from_yaml(repo_root / "config" / "notifications-matrix.yaml"),
        registry=ChannelRegistry(
            channels={
                "teams-ops-prd": cast(
                    NotificationChannel,
                    TeamsWebhookChannel(
                        config=TeamsWebhookConfig(
                            channel_id="teams-ops-prd",
                            webhook_url=env["FDAI_CHATOPS_WEBHOOK_URL"].strip(),
                            trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                            timeout_seconds=timeout,
                        ),
                        http_client=http_client,
                    ),
                )
            }
        ),
        audit_store=state_store,
        hil_sink=StateStoreHilEscalationSink(state_store=state_store),
        actor="fdai.delivery.stewardship.governance",
    )
    service = StewardshipGovernanceService(
        current_map=current_map,
        publisher=GitOpsPrAdapter(
            config=GitOpsPrConfig(
                owner=owner,
                repo=repo,
                default_branch=env.get("FDAI_GITOPS_DEFAULT_BRANCH", "main").strip() or "main",
                branch_prefix=env.get(
                    "FDAI_STEWARDSHIP_GITOPS_BRANCH_PREFIX", "fdai/stewardship"
                ).strip()
                or "fdai/stewardship",
                api_base=api_base,
                timeout_seconds=timeout,
            ),
            http_client=http_client,
            token=token,
        ),
        notifications=notifications,
        state_store=state_store,
    )
    return ProductionStewardshipGovernance(
        service=service,
        webhook=GitHubStewardshipWebhook(
            config=GitHubStewardshipWebhookConfig(
                repository=f"{owner}/{repo}",
                webhook_secret=env["FDAI_GITHUB_WEBHOOK_SECRET"].strip(),
                token=token,
                api_base=api_base,
                timeout_seconds=timeout,
            ),
            http_client=http_client,
            governance=service,
        ),
    )


def _positive_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError as exc:
        raise StewardshipGovernanceConfigError(f"{key} MUST be a number") from exc
    if value <= 0:
        raise StewardshipGovernanceConfigError(f"{key} MUST be positive")
    return value


__all__ = [
    "ProductionStewardshipGovernance",
    "StewardshipGovernanceConfigError",
    "build_production_stewardship_governance",
]
