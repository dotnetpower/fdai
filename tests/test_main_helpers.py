"""Smoke tests for the internal helpers used by the process entrypoint.

The `main()` loop itself is a process orchestrator and requires the
Azure runtime environment to exercise end-to-end. The functions covered
here are the pure helpers underneath — path resolution, StateStore
selection, and the config summary — so a smoke change to the entry
point stays green under the CI coverage floor.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from aiopspilot.__main__ import (
    _build_audit_store,
    _build_hil_channel,
    _build_pattern_library,
    _build_publisher,
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


# ---------------------------------------------------------------------------
# _build_publisher — RemediationPrPublisher selection
# ---------------------------------------------------------------------------


def _clear_gitops_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AIOPSPILOT_GITOPS_TOKEN",
        "AIOPSPILOT_GITOPS_OWNER",
        "AIOPSPILOT_GITOPS_REPO",
        "AIOPSPILOT_GITOPS_DEFAULT_BRANCH",
        "AIOPSPILOT_GITOPS_BRANCH_PREFIX",
        "AIOPSPILOT_GITOPS_API_BASE",
        "AIOPSPILOT_GITOPS_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_build_publisher_defaults_to_recording_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_gitops_env(monkeypatch)
    from aiopspilot.shared.providers.testing.remediation_pr import (
        RecordingRemediationPrPublisher,
    )

    publisher = _build_publisher(http_client=None)
    assert isinstance(publisher, RecordingRemediationPrPublisher)


def test_build_publisher_returns_gitops_when_token_owner_repo_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_gitops_env(monkeypatch)
    monkeypatch.setenv("AIOPSPILOT_GITOPS_TOKEN", "ghp_fake")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_OWNER", "example-org")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_REPO", "example-repo")
    from aiopspilot.delivery.gitops_pr.adapter import GitOpsPrAdapter

    client = httpx.AsyncClient()
    try:
        publisher = _build_publisher(http_client=client)
        assert isinstance(publisher, GitOpsPrAdapter)
    finally:
        # AsyncClient.close is async but the object is safe to leak in
        # tests — the event loop is torn down at test exit. Prefer
        # not spinning up an event loop just for this smoke check.
        pass


def test_build_publisher_rejects_partial_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_gitops_env(monkeypatch)
    monkeypatch.setenv("AIOPSPILOT_GITOPS_TOKEN", "ghp_fake")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_OWNER", "example-org")
    # AIOPSPILOT_GITOPS_REPO deliberately missing
    with pytest.raises(RuntimeError, match="AIOPSPILOT_GITOPS_OWNER / AIOPSPILOT_GITOPS_REPO"):
        _build_publisher(http_client=httpx.AsyncClient())


def test_build_publisher_requires_http_client_when_gitops_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_gitops_env(monkeypatch)
    monkeypatch.setenv("AIOPSPILOT_GITOPS_TOKEN", "ghp_fake")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_OWNER", "example-org")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_REPO", "example-repo")
    with pytest.raises(RuntimeError, match="no HTTP client is available"):
        _build_publisher(http_client=None)


def test_build_publisher_rejects_non_float_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_gitops_env(monkeypatch)
    monkeypatch.setenv("AIOPSPILOT_GITOPS_TOKEN", "ghp_fake")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_OWNER", "example-org")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_REPO", "example-repo")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_TIMEOUT_SECONDS", "not-a-number")
    with pytest.raises(RuntimeError, match="not a float"):
        _build_publisher(http_client=httpx.AsyncClient())


def test_build_publisher_rejects_nonpositive_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_gitops_env(monkeypatch)
    monkeypatch.setenv("AIOPSPILOT_GITOPS_TOKEN", "ghp_fake")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_OWNER", "example-org")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_REPO", "example-repo")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_TIMEOUT_SECONDS", "0")
    with pytest.raises(RuntimeError, match="MUST be > 0"):
        _build_publisher(http_client=httpx.AsyncClient())


def test_build_publisher_honors_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_gitops_env(monkeypatch)
    monkeypatch.setenv("AIOPSPILOT_GITOPS_TOKEN", "ghp_fake")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_OWNER", "example-org")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_REPO", "example-repo")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_DEFAULT_BRANCH", "trunk")
    monkeypatch.setenv("AIOPSPILOT_GITOPS_API_BASE", "https://ghe.example.com/api/v3")
    from aiopspilot.delivery.gitops_pr.adapter import GitOpsPrAdapter

    publisher = _build_publisher(http_client=httpx.AsyncClient())
    assert isinstance(publisher, GitOpsPrAdapter)
    # Non-secret config surface is inspectable (secrets — token — are not).
    assert publisher._config.default_branch == "trunk"
    assert publisher._config.api_base == "https://ghe.example.com/api/v3"
    assert publisher._config.owner == "example-org"
    assert publisher._config.repo == "example-repo"


# ---------------------------------------------------------------------------
# _build_pattern_library — PatternLibrary selection (T1 similarity reuse)
# ---------------------------------------------------------------------------


def _clear_pattern_library_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AIOPSPILOT_T1_PATTERN_LIBRARY_DSN",
        "AIOPSPILOT_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS",
        "AIOPSPILOT_T1_PATTERN_LIBRARY_IVFFLAT_PROBES",
    ):
        monkeypatch.delenv(name, raising=False)


def test_build_pattern_library_defaults_to_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    from aiopspilot.core.tiers.t1_lightweight.testing import InMemoryPatternLibrary

    library = _build_pattern_library()
    assert isinstance(library, InMemoryPatternLibrary)


def test_build_pattern_library_selects_pgvector_when_dsn_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    monkeypatch.setenv(
        "AIOPSPILOT_T1_PATTERN_LIBRARY_DSN",
        "postgresql://user:pw@example:5432/db",
    )
    from aiopspilot.delivery.persistence import PgVectorPatternLibrary

    library = _build_pattern_library()
    assert isinstance(library, PgVectorPatternLibrary)


def test_build_pattern_library_honors_tuning_envs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    monkeypatch.setenv(
        "AIOPSPILOT_T1_PATTERN_LIBRARY_DSN",
        "postgresql://user:pw@example:5432/db",
    )
    monkeypatch.setenv("AIOPSPILOT_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS", "5000")
    monkeypatch.setenv("AIOPSPILOT_T1_PATTERN_LIBRARY_IVFFLAT_PROBES", "25")
    from aiopspilot.delivery.persistence import PgVectorPatternLibrary

    library = _build_pattern_library()
    assert isinstance(library, PgVectorPatternLibrary)
    assert library._config.statement_timeout_ms == 5000
    assert library._config.ivfflat_probes == 25


def test_build_pattern_library_rejects_non_int_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    monkeypatch.setenv(
        "AIOPSPILOT_T1_PATTERN_LIBRARY_DSN",
        "postgresql://user:pw@example:5432/db",
    )
    monkeypatch.setenv("AIOPSPILOT_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS", "abc")
    with pytest.raises(RuntimeError, match="not an integer"):
        _build_pattern_library()


def test_build_pattern_library_rejects_nonpositive_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    monkeypatch.setenv(
        "AIOPSPILOT_T1_PATTERN_LIBRARY_DSN",
        "postgresql://user:pw@example:5432/db",
    )
    monkeypatch.setenv("AIOPSPILOT_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS", "0")
    with pytest.raises(RuntimeError, match="MUST be >= 1"):
        _build_pattern_library()


def test_build_pattern_library_rejects_non_int_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    monkeypatch.setenv(
        "AIOPSPILOT_T1_PATTERN_LIBRARY_DSN",
        "postgresql://user:pw@example:5432/db",
    )
    monkeypatch.setenv("AIOPSPILOT_T1_PATTERN_LIBRARY_IVFFLAT_PROBES", "not-int")
    with pytest.raises(RuntimeError, match="not an integer"):
        _build_pattern_library()


def test_build_pattern_library_rejects_nonpositive_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    monkeypatch.setenv(
        "AIOPSPILOT_T1_PATTERN_LIBRARY_DSN",
        "postgresql://user:pw@example:5432/db",
    )
    monkeypatch.setenv("AIOPSPILOT_T1_PATTERN_LIBRARY_IVFFLAT_PROBES", "0")
    with pytest.raises(RuntimeError, match="MUST be >= 1"):
        _build_pattern_library()


# ---------------------------------------------------------------------------
# _build_hil_channel — HilChannel selection (ChatOps A1 approvals)
# ---------------------------------------------------------------------------


def _clear_chatops_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AIOPSPILOT_CHATOPS_WEBHOOK_URL",
        "AIOPSPILOT_CHATOPS_WEBHOOK_SECRET",
        "AIOPSPILOT_CHATOPS_APPROVE_CALLBACK_URL",
        "AIOPSPILOT_CHATOPS_REJECT_CALLBACK_URL",
        "AIOPSPILOT_CHATOPS_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_build_hil_channel_returns_none_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chatops_env(monkeypatch)
    assert _build_hil_channel(http_client=None) is None


def test_build_hil_channel_returns_teams_adapter_when_url_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chatops_env(monkeypatch)
    monkeypatch.setenv(
        "AIOPSPILOT_CHATOPS_WEBHOOK_URL",
        "https://teams.example.com/hook/abc",
    )
    from aiopspilot.delivery.chatops.teams_adapter import TeamsHilAdapter

    channel = _build_hil_channel(http_client=httpx.AsyncClient())
    assert isinstance(channel, TeamsHilAdapter)


def test_build_hil_channel_requires_http_client_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chatops_env(monkeypatch)
    monkeypatch.setenv(
        "AIOPSPILOT_CHATOPS_WEBHOOK_URL",
        "https://teams.example.com/hook/abc",
    )
    with pytest.raises(RuntimeError, match="no HTTP client is available"):
        _build_hil_channel(http_client=None)


def test_build_hil_channel_passes_secret_and_callbacks_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chatops_env(monkeypatch)
    monkeypatch.setenv(
        "AIOPSPILOT_CHATOPS_WEBHOOK_URL",
        "https://teams.example.com/hook/abc",
    )
    monkeypatch.setenv("AIOPSPILOT_CHATOPS_WEBHOOK_SECRET", "shhh")
    monkeypatch.setenv(
        "AIOPSPILOT_CHATOPS_APPROVE_CALLBACK_URL",
        "https://api.example.com/approve",
    )
    monkeypatch.setenv(
        "AIOPSPILOT_CHATOPS_REJECT_CALLBACK_URL",
        "https://api.example.com/reject",
    )

    channel = _build_hil_channel(http_client=httpx.AsyncClient())
    # Internals are inspected only for test purposes.
    assert channel is not None
    cfg = channel._config
    assert cfg.webhook_secret == "shhh"
    assert cfg.approve_callback_url == "https://api.example.com/approve"
    assert cfg.reject_callback_url == "https://api.example.com/reject"


def test_build_hil_channel_rejects_non_float_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chatops_env(monkeypatch)
    monkeypatch.setenv(
        "AIOPSPILOT_CHATOPS_WEBHOOK_URL",
        "https://teams.example.com/hook/abc",
    )
    monkeypatch.setenv("AIOPSPILOT_CHATOPS_TIMEOUT_SECONDS", "not-a-number")
    with pytest.raises(RuntimeError, match="not a float"):
        _build_hil_channel(http_client=httpx.AsyncClient())


def test_build_hil_channel_rejects_nonpositive_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chatops_env(monkeypatch)
    monkeypatch.setenv(
        "AIOPSPILOT_CHATOPS_WEBHOOK_URL",
        "https://teams.example.com/hook/abc",
    )
    monkeypatch.setenv("AIOPSPILOT_CHATOPS_TIMEOUT_SECONDS", "0")
    with pytest.raises(RuntimeError, match="MUST be > 0"):
        _build_hil_channel(http_client=httpx.AsyncClient())


def test_build_hil_channel_honors_timeout_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chatops_env(monkeypatch)
    monkeypatch.setenv(
        "AIOPSPILOT_CHATOPS_WEBHOOK_URL",
        "https://teams.example.com/hook/abc",
    )
    monkeypatch.setenv("AIOPSPILOT_CHATOPS_TIMEOUT_SECONDS", "42.5")

    channel = _build_hil_channel(http_client=httpx.AsyncClient())
    assert channel is not None
    assert channel._config.timeout_seconds == 42.5
