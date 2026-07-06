"""Smoke tests for the internal helpers used by the process entrypoint.

The `main()` loop itself is a process orchestrator and requires the
Azure runtime environment to exercise end-to-end. The functions covered
here are the pure helpers underneath — path resolution, StateStore
selection, and the config summary — so a smoke change to the entry
point stays green under the CI coverage floor.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aiopspilot.__main__ import (
    _build_audit_store,
    _resolve_catalog_root,
    _resolve_policies_root,
    _summarize_config,
)
from aiopspilot.shared.config import AppConfig


@pytest.fixture()
def app_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "resource_group": "rg-aiopspilot",
                "region": "krc",
            },
            "kafka": {
                "bootstrap_servers": "evhns.example:9093",
                "topic_events": "aw.change.events",
            },
            "postgres": {"host": "psql.example", "database": "aiopspilot"},
            "runtime": {"env": "dev"},
        }
    )


def test_resolve_catalog_root_uses_repo_sibling() -> None:
    catalog = _resolve_catalog_root()
    assert (catalog / "catalog").is_dir()
    assert (catalog / "action-types").is_dir()


def test_resolve_catalog_root_respects_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = tmp_path / "custom-catalog"
    (override / "catalog").mkdir(parents=True)
    monkeypatch.setenv("AIOPSPILOT_CATALOG_ROOT", str(override))
    assert _resolve_catalog_root() == override


def test_resolve_catalog_root_rejects_bad_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AIOPSPILOT_CATALOG_ROOT", str(tmp_path / "does-not-exist"))
    with pytest.raises(FileNotFoundError, match="AIOPSPILOT_CATALOG_ROOT"):
        _resolve_catalog_root()


def test_resolve_policies_root_uses_sibling() -> None:
    catalog = _resolve_catalog_root()
    policies = _resolve_policies_root(catalog)
    assert (policies / "object_storage").is_dir() or policies.is_dir()


def test_resolve_policies_root_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = tmp_path / "policies-x"
    override.mkdir()
    monkeypatch.setenv("AIOPSPILOT_POLICIES_ROOT", str(override))
    catalog = _resolve_catalog_root()
    assert _resolve_policies_root(catalog) == override


def test_resolve_policies_root_rejects_bad_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AIOPSPILOT_POLICIES_ROOT", str(tmp_path / "nope"))
    with pytest.raises(FileNotFoundError, match="AIOPSPILOT_POLICIES_ROOT"):
        _resolve_policies_root(_resolve_catalog_root())


def test_build_audit_store_defaults_to_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AIOPSPILOT_STATE_STORE_DSN", raising=False)
    store = _build_audit_store()
    from aiopspilot.shared.providers.testing.state_store import InMemoryStateStore

    assert isinstance(store, InMemoryStateStore)


def test_build_audit_store_selects_postgres_when_dsn_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIOPSPILOT_STATE_STORE_DSN", "postgresql://user:pw@example:5432/db")
    store = _build_audit_store()
    from aiopspilot.delivery.persistence import PostgresStateStore

    assert isinstance(store, PostgresStateStore)


def test_summarize_config_is_secret_free(app_config: AppConfig) -> None:
    from aiopspilot.composition import default_container

    container = default_container(app_config)
    summary = _summarize_config(container)
    # Fields that MUST NOT leak into logs.
    forbidden = ("password", "secret", "token", "connection_string")
    joined = repr(summary).lower()
    for word in forbidden:
        assert word not in joined
    # Fields that MUST be present so the audit trail is reconstructable.
    assert summary["env"] == "dev"
    assert summary["azure_region"] == "krc"
    assert summary["llm_bindings_available"] is True
