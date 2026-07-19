"""Tests for the deployment-time Entra SPA redirect URI synchronization."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "deployment" / "azure" / "sync-entra-spa-redirect.py"


@pytest.fixture(scope="module")
def script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sync_entra_spa_redirect", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeAzureCli:
    def __init__(
        self,
        *,
        tenant_id: str = "target-tenant",
        redirect_uris: list[str] | None = None,
        apply_patch: bool = True,
    ) -> None:
        self.tenant_id = tenant_id
        self.redirect_uris = list(redirect_uris or [])
        self.apply_patch = apply_patch
        self.calls: list[list[str]] = []

    def __call__(self, command: Any) -> str:
        args = list(command)
        self.calls.append(args)
        if args[:2] == ["account", "show"]:
            return f"{self.tenant_id}\n"
        if args[:3] == ["ad", "app", "show"]:
            return json.dumps(
                {
                    "objectId": "spa-object-id",
                    "redirectUris": self.redirect_uris,
                }
            )
        if args[:2] == ["rest", "--method"]:
            if self.apply_patch:
                body = json.loads(args[args.index("--body") + 1])
                self.redirect_uris = body["spa"]["redirectUris"]
            return ""
        raise AssertionError(f"unexpected Azure CLI call: {args}")


def test_adds_origin_without_replacing_existing_redirects(script_module: ModuleType) -> None:
    runner = FakeAzureCli(redirect_uris=["http://localhost:5273", "https://console.example.com"])

    changed = script_module.synchronize_redirect_uri(
        tenant_id="target-tenant",
        spa_client_id="spa-client-id",
        origin="https://deployed.example.com/",
        runner=runner,
    )

    assert changed is True
    assert runner.redirect_uris == [
        "http://localhost:5273",
        "https://console.example.com",
        "https://deployed.example.com",
    ]
    patch = next(call for call in runner.calls if call[0] == "rest")
    assert patch[patch.index("--uri") + 1].endswith("/spa-object-id")


def test_existing_origin_is_an_idempotent_no_op(script_module: ModuleType) -> None:
    runner = FakeAzureCli(redirect_uris=["https://deployed.example.com"])

    changed = script_module.synchronize_redirect_uri(
        tenant_id="target-tenant",
        spa_client_id="spa-client-id",
        origin="https://deployed.example.com",
        runner=runner,
    )

    assert changed is False
    assert all(call[0] != "rest" for call in runner.calls)


def test_rejects_active_tenant_mismatch_before_reading_app(script_module: ModuleType) -> None:
    runner = FakeAzureCli(tenant_id="other-tenant")

    with pytest.raises(ValueError, match="active Azure CLI tenant"):
        script_module.synchronize_redirect_uri(
            tenant_id="target-tenant",
            spa_client_id="spa-client-id",
            origin="https://deployed.example.com",
            runner=runner,
        )

    assert len(runner.calls) == 1


@pytest.mark.parametrize(
    "origin",
    [
        "http://deployed.example.com",
        "https://deployed.example.com/path",
        "https://deployed.example.com?query=value",
        "https://user@deployed.example.com",
    ],
)
def test_rejects_non_origin_values(script_module: ModuleType, origin: str) -> None:
    with pytest.raises(ValueError, match="HTTPS origin"):
        script_module.normalize_origin(origin)


def test_fails_when_graph_update_is_not_visible(script_module: ModuleType) -> None:
    runner = FakeAzureCli(apply_patch=False)

    with pytest.raises(script_module.AzureCliError, match="not visible"):
        script_module.synchronize_redirect_uri(
            tenant_id="target-tenant",
            spa_client_id="spa-client-id",
            origin="https://deployed.example.com",
            runner=runner,
        )
