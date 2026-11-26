"""Tests for the coding-agent provider export gate."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml
from fdai.core.security.code_findings.export_gate import (
    AgentProviderPolicy,
    ExportDeniedError,
    authorize_export,
)
from fdai.core.security.code_findings.pack import PackMode

from ._support import REPO_ROOT

_POLICY = {
    "schema_version": 1,
    "version": "1.0.0",
    "providers": [
        {
            "id": "example-agent",
            "display_name": "Example agent",
            "modes": ["minimized"],
            "data_residency": "example-region",
            "training_use": "none",
            "retention_days": 0,
            "approved_until": "2026-12-31",
        }
    ],
}


def test_approved_provider_and_mode_pass() -> None:
    policy = AgentProviderPolicy.from_mapping(_POLICY)
    provider = authorize_export(policy, "example-agent", PackMode.MINIMIZED, date(2026, 10, 7))
    assert provider.data_residency == "example-region"


@pytest.mark.parametrize(
    ("provider_id", "mode", "today", "message"),
    [
        ("unknown-agent", PackMode.MINIMIZED, date(2026, 10, 7), "not approved"),
        ("example-agent", PackMode.FULL, date(2026, 10, 7), "may receive only"),
        ("example-agent", PackMode.MINIMIZED, date(2027, 1, 1), "expired"),
    ],
)
def test_export_fails_closed(provider_id: str, mode: PackMode, today: date, message: str) -> None:
    with pytest.raises(ExportDeniedError, match=message):
        authorize_export(AgentProviderPolicy.from_mapping(_POLICY), provider_id, mode, today)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["providers"][0].update(training_use="allowed"),
        lambda p: p["providers"][0].update(modes=[]),
        lambda p: p.update(surprise=1),
        lambda p: p["providers"].append(dict(p["providers"][0])),
    ],
)
def test_invalid_policy_is_rejected(mutate) -> None:  # type: ignore[no-untyped-def]
    import copy

    document = copy.deepcopy(_POLICY)
    mutate(document)
    with pytest.raises(ValueError):
        AgentProviderPolicy.from_mapping(document)


def test_upstream_policy_approves_nothing() -> None:
    path = REPO_ROOT / "config" / "code-security-agent-providers.yaml"
    policy = AgentProviderPolicy.from_mapping(yaml.safe_load(Path(path).read_text()))
    assert policy.providers == ()
