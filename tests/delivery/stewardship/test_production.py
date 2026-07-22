from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from fdai.delivery.stewardship.production import (
    StewardshipGovernanceConfigError,
    build_production_stewardship_governance,
)
from fdai.shared.providers.testing import InMemoryStateStore

_ROOT = Path(__file__).resolve().parents[3]


def test_production_governance_is_opt_in() -> None:
    assert (
        build_production_stewardship_governance(
            env={},
            repo_root=_ROOT,
            http_client=httpx.AsyncClient(),
            state_store=InMemoryStateStore(),
        )
        is None
    )


def test_production_governance_fails_fast_on_partial_config() -> None:
    with pytest.raises(StewardshipGovernanceConfigError, match="FDAI_GITOPS_TOKEN"):
        build_production_stewardship_governance(
            env={"FDAI_STEWARDSHIP_GOVERNANCE_ENABLED": "1"},
            repo_root=_ROOT,
            http_client=httpx.AsyncClient(),
            state_store=InMemoryStateStore(),
        )


def test_production_governance_composes_with_real_bindings() -> None:
    agents = (
        "ODIN",
        "THOR",
        "FORSETI",
        "HUGINN",
        "HEIMDALL",
        "VIDAR",
        "VAR",
        "BRAGI",
        "SAGA",
        "MIMIR",
        "MUNINN",
        "NORNS",
        "NJORD",
        "FREYR",
    )
    env = {
        "FDAI_STEWARDSHIP_GOVERNANCE_ENABLED": "1",
        "FDAI_STEWARDSHIP_REQUIRE_BINDINGS": "1",
        "FDAI_GITOPS_TOKEN": "token",
        "FDAI_GITOPS_OWNER": "acme",
        "FDAI_GITOPS_REPO": "fdai",
        "FDAI_GITOPS_API_BASE": "https://mock.github.local",
        "FDAI_GITHUB_WEBHOOK_SECRET": "s" * 32,
        "FDAI_CHATOPS_WEBHOOK_URL": "https://teams.example.com/webhook",
        "FDAI_MAINTAINERS": (
            "10000000" + "-0000-0000-0000-000000000001,10000000" + "-0000-0000-0000-000000000002"
        ),
    }
    env.update(
        {
            f"FDAI_STEWARD_{agent}": f"user:20000000-0000-0000-0000-{index:012d}"
            for index, agent in enumerate(agents, start=1)
        }
    )

    composed = build_production_stewardship_governance(
        env=env,
        repo_root=_ROOT,
        http_client=httpx.AsyncClient(),
        state_store=InMemoryStateStore(),
    )

    assert composed is not None
    assert composed.service is not None
    assert composed.webhook is not None
