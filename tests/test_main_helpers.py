"""Smoke tests for the internal helpers used by the process entrypoint.

The `main()` loop itself is a process orchestrator and requires the
Azure runtime environment to exercise end-to-end. The functions covered
here are the pure helpers underneath - path resolution, StateStore
selection, and the config summary - so a smoke change to the entry
point stays green under the CI coverage floor.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fdai.__main__ import (
    _attach_runtime_metric_provider,
    _authoritative_decision,
    _build_audit_store,
    _build_hil_channel,
    _build_idempotency_store,
    _build_notification_registry,
    _build_pattern_library,
    _build_publisher,
    _build_resource_lock,
    _consume,
    _consume_canaries,
    _consume_hil_decisions,
    _resolve_catalog_root,
    _resolve_policies_root,
    _summarize_config,
)
from fdai.core.control_loop import ControlLoopOutcome, ControlLoopResult
from fdai.shared.config import AppConfig
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


@pytest.fixture()
def app_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "resource_group": "rg-fdai",
                "region": "krc",
            },
            "kafka": {
                "bootstrap_servers": "evhns.example:9093",
                "topic_events": "aw.change.events",
            },
            "postgres": {"host": "psql.example", "database": "fdai"},
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
    monkeypatch.setenv("FDAI_CATALOG_ROOT", str(override))
    assert _resolve_catalog_root() == override


def test_resolve_catalog_root_rejects_bad_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FDAI_CATALOG_ROOT", str(tmp_path / "does-not-exist"))
    with pytest.raises(FileNotFoundError, match="FDAI_CATALOG_ROOT"):
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
    monkeypatch.setenv("FDAI_POLICIES_ROOT", str(override))
    catalog = _resolve_catalog_root()
    assert _resolve_policies_root(catalog) == override


def test_resolve_policies_root_rejects_bad_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FDAI_POLICIES_ROOT", str(tmp_path / "nope"))
    with pytest.raises(FileNotFoundError, match="FDAI_POLICIES_ROOT"):
        _resolve_policies_root(_resolve_catalog_root())


def test_build_audit_store_defaults_to_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    store = _build_audit_store()
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    assert isinstance(store, InMemoryStateStore)


def test_build_audit_store_selects_postgres_when_dsn_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://user:pw@example:5432/db")
    store = _build_audit_store()
    from fdai.delivery.persistence import PostgresStateStore

    assert isinstance(store, PostgresStateStore)


@pytest.mark.parametrize("runtime_env", ["staging", "prod"])
@pytest.mark.parametrize(
    ("builder", "backend"),
    [
        (_build_audit_store, "state store"),
        (_build_resource_lock, "resource lock"),
        (_build_idempotency_store, "idempotency store"),
        (_build_pattern_library, "T1 pattern library"),
    ],
)
def test_production_runtime_rejects_in_memory_safety_backends(
    monkeypatch: pytest.MonkeyPatch,
    runtime_env: str,
    builder: object,
    backend: str,
) -> None:
    monkeypatch.setenv("RUNTIME_ENV", runtime_env)
    for name in (
        "FDAI_STATE_STORE_DSN",
        "FDAI_RESOURCE_LOCK_DSN",
        "FDAI_IDEMPOTENCY_DSN",
        "FDAI_T1_PATTERN_LIBRARY_DSN",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match=backend):
        builder()  # type: ignore[operator]


def test_summarize_config_is_secret_free(app_config: AppConfig) -> None:
    from fdai.composition import default_container

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


def test_live_monitor_binding_is_independent_of_llm_mode(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.composition import default_container
    from fdai.shared.providers.routed_metric import RoutedMetricProvider
    from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

    monkeypatch.setenv("FDAI_MONITOR_WORKSPACE_ID", "workspace-customer-id")
    container = default_container(app_config)
    with httpx.Client():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: None))
        wired = _attach_runtime_metric_provider(
            container,
            http_client=http_client,
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default",
                token="test-token",
            ),
        )

    assert isinstance(wired.metric_provider, RoutedMetricProvider)
    asyncio.run(http_client.aclose())


# ---------------------------------------------------------------------------
# _build_publisher - RemediationPrPublisher selection
# ---------------------------------------------------------------------------


def _clear_gitops_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FDAI_GITOPS_TOKEN",
        "FDAI_GITOPS_OWNER",
        "FDAI_GITOPS_REPO",
        "FDAI_GITOPS_DEFAULT_BRANCH",
        "FDAI_GITOPS_BRANCH_PREFIX",
        "FDAI_GITOPS_API_BASE",
        "FDAI_GITOPS_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_build_publisher_defaults_to_recording_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_gitops_env(monkeypatch)
    from fdai.shared.providers.testing.remediation_pr import (
        RecordingRemediationPrPublisher,
    )

    publisher = _build_publisher(http_client=None)
    assert isinstance(publisher, RecordingRemediationPrPublisher)


def test_build_publisher_returns_gitops_when_token_owner_repo_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_gitops_env(monkeypatch)
    monkeypatch.setenv("FDAI_GITOPS_TOKEN", "ghp_fake")
    monkeypatch.setenv("FDAI_GITOPS_OWNER", "example-org")
    monkeypatch.setenv("FDAI_GITOPS_REPO", "example-repo")
    from fdai.delivery.gitops_pr.adapter import GitOpsPrAdapter

    client = httpx.AsyncClient()
    try:
        publisher = _build_publisher(http_client=client)
        assert isinstance(publisher, GitOpsPrAdapter)
    finally:
        # AsyncClient.close is async but the object is safe to leak in
        # tests - the event loop is torn down at test exit. Prefer
        # not spinning up an event loop just for this smoke check.
        pass


def test_build_publisher_rejects_partial_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_gitops_env(monkeypatch)
    monkeypatch.setenv("FDAI_GITOPS_TOKEN", "ghp_fake")
    monkeypatch.setenv("FDAI_GITOPS_OWNER", "example-org")
    # FDAI_GITOPS_REPO deliberately missing
    with pytest.raises(RuntimeError, match="FDAI_GITOPS_OWNER / FDAI_GITOPS_REPO"):
        _build_publisher(http_client=httpx.AsyncClient())


def test_build_publisher_requires_http_client_when_gitops_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_gitops_env(monkeypatch)
    monkeypatch.setenv("FDAI_GITOPS_TOKEN", "ghp_fake")
    monkeypatch.setenv("FDAI_GITOPS_OWNER", "example-org")
    monkeypatch.setenv("FDAI_GITOPS_REPO", "example-repo")
    with pytest.raises(RuntimeError, match="no HTTP client is available"):
        _build_publisher(http_client=None)


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (ControlLoopOutcome.EXECUTED, "auto"),
        (ControlLoopOutcome.HIL, "hil"),
        (ControlLoopOutcome.DENIED, "deny"),
        (ControlLoopOutcome.DEDUPED, "dedupe"),
        (ControlLoopOutcome.ABSTAINED_ROUTING, "abstain"),
        (ControlLoopOutcome.ABSTAINED_T0, "abstain"),
        (ControlLoopOutcome.T1_REUSE_LOGGED, "abstain"),
        (ControlLoopOutcome.GOVERNANCE_OBSERVED, "abstain"),
    ],
)
def test_authoritative_decision_normalizes_outcomes(
    outcome: ControlLoopOutcome, expected: str
) -> None:
    result = ControlLoopResult(outcome=outcome, tier="t0", decision="x", resource_type=None)
    assert _authoritative_decision(result) == expected


class _FailingLoop:
    def __init__(self) -> None:
        self.failures: list[dict[str, object]] = []

    async def process(self, _payload: object) -> None:
        raise RuntimeError("unexpected processing failure")

    async def record_unhandled_failure(self, **entry: object) -> None:
        self.failures.append(dict(entry))


class _RecordingCanaryLoop:
    def __init__(self) -> None:
        self.payloads: list[object] = []

    async def process_canary(self, payload: object) -> ControlLoopResult:
        self.payloads.append(payload)
        return ControlLoopResult(
            outcome=ControlLoopOutcome.CANARY_RECORDED,
            tier="canary",
            decision="no-op",
            resource_type=None,
            event_id="canary-event",
        )

    async def record_unhandled_failure(self, **entry: object) -> None:
        raise AssertionError(f"unexpected canary failure: {entry}")


def test_canary_consumer_uses_dedicated_control_loop_entry_point() -> None:
    bus = InMemoryEventBus()
    loop = _RecordingCanaryLoop()

    async def _run() -> None:
        payload = {"event_id": "canary-event", "idempotency_key": "canary-key"}
        await bus.publish("canaries", "canary-key", payload)
        await _consume_canaries(
            bus=bus,
            topic="canaries",
            control_loop=loop,  # type: ignore[arg-type]
            stop=asyncio.Event(),
        )

    asyncio.run(_run())
    assert loop.payloads == [{"event_id": "canary-event", "idempotency_key": "canary-key"}]


def test_consume_audits_and_dead_letters_before_committing() -> None:
    bus = InMemoryEventBus()
    loop = _FailingLoop()

    async def _run() -> tuple[list[dict], list[dict]]:
        payload = {"event_id": "event-1", "idempotency_key": "key-1"}
        await bus.publish("events", "resource-1", payload)
        await _consume(
            bus=bus,
            topic="events",
            group_id="core",
            control_loop=loop,  # type: ignore[arg-type]
            stop=asyncio.Event(),
        )
        dlq = [dict(item.payload) async for item in bus.subscribe("events.dlq", "reader")]
        remaining = [dict(item.payload) async for item in bus.subscribe("events", "core")]
        return dlq, remaining

    dlq, remaining = asyncio.run(_run())
    assert len(loop.failures) == 1
    assert loop.failures[0]["reason"] == "control_loop_unhandled_error:RuntimeError"
    assert dlq[0]["reason"] == "control_loop_unhandled_error:RuntimeError"
    assert remaining == []


def test_consume_preserves_offset_when_dead_letter_fails() -> None:
    class _FailingDlqBus(InMemoryEventBus):
        async def dead_letter(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("DLQ unavailable")

    bus = _FailingDlqBus()
    loop = _FailingLoop()

    async def _run() -> list[dict]:
        payload = {"event_id": "event-2", "idempotency_key": "key-2"}
        await bus.publish("events", "resource-2", payload)
        with pytest.raises(RuntimeError, match="DLQ unavailable"):
            await _consume(
                bus=bus,
                topic="events",
                group_id="core",
                control_loop=loop,  # type: ignore[arg-type]
                stop=asyncio.Event(),
            )
        return [dict(item.payload) async for item in bus.subscribe("events", "core")]

    remaining = asyncio.run(_run())
    assert remaining == [{"event_id": "event-2", "idempotency_key": "key-2"}]


class _RecordingHilCoordinator:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def resolve(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))


def test_hil_decision_consumer_resolves_durable_park() -> None:
    bus = InMemoryEventBus()
    coordinator = _RecordingHilCoordinator()

    async def _run() -> None:
        await bus.publish(
            "hil-decisions",
            "approval-1",
            {
                "approval_id": "approval-1",
                "decision": "approve",
                "approver_oid": "approver-1",
                "justification": "Reviewed.",
            },
        )
        await _consume_hil_decisions(
            bus=bus,
            topic="hil-decisions",
            coordinator=coordinator,  # type: ignore[arg-type]
            stop=asyncio.Event(),
        )

    asyncio.run(_run())
    assert len(coordinator.calls) == 1
    assert coordinator.calls[0]["approval_id"] == "approval-1"


def test_hil_decision_consumer_dead_letters_malformed_payload() -> None:
    bus = InMemoryEventBus()
    coordinator = _RecordingHilCoordinator()

    async def _run() -> list[dict]:
        await bus.publish("hil-decisions", "approval-2", {"decision": "approve"})
        await _consume_hil_decisions(
            bus=bus,
            topic="hil-decisions",
            coordinator=coordinator,  # type: ignore[arg-type]
            stop=asyncio.Event(),
        )
        return [dict(item.payload) async for item in bus.subscribe("hil-decisions.dlq", "reader")]

    dlq = asyncio.run(_run())
    assert coordinator.calls == []
    assert dlq[0]["reason"] == "hil_decision_consume_error:KeyError"


def test_build_publisher_rejects_non_float_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_gitops_env(monkeypatch)
    monkeypatch.setenv("FDAI_GITOPS_TOKEN", "ghp_fake")
    monkeypatch.setenv("FDAI_GITOPS_OWNER", "example-org")
    monkeypatch.setenv("FDAI_GITOPS_REPO", "example-repo")
    monkeypatch.setenv("FDAI_GITOPS_TIMEOUT_SECONDS", "not-a-number")
    with pytest.raises(RuntimeError, match="not a float"):
        _build_publisher(http_client=httpx.AsyncClient())


def test_build_publisher_rejects_nonpositive_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_gitops_env(monkeypatch)
    monkeypatch.setenv("FDAI_GITOPS_TOKEN", "ghp_fake")
    monkeypatch.setenv("FDAI_GITOPS_OWNER", "example-org")
    monkeypatch.setenv("FDAI_GITOPS_REPO", "example-repo")
    monkeypatch.setenv("FDAI_GITOPS_TIMEOUT_SECONDS", "0")
    with pytest.raises(RuntimeError, match="MUST be > 0"):
        _build_publisher(http_client=httpx.AsyncClient())


def test_build_publisher_honors_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_gitops_env(monkeypatch)
    monkeypatch.setenv("FDAI_GITOPS_TOKEN", "ghp_fake")
    monkeypatch.setenv("FDAI_GITOPS_OWNER", "example-org")
    monkeypatch.setenv("FDAI_GITOPS_REPO", "example-repo")
    monkeypatch.setenv("FDAI_GITOPS_DEFAULT_BRANCH", "trunk")
    monkeypatch.setenv("FDAI_GITOPS_API_BASE", "https://ghe.example.com/api/v3")
    from fdai.delivery.gitops_pr.adapter import GitOpsPrAdapter

    publisher = _build_publisher(http_client=httpx.AsyncClient())
    assert isinstance(publisher, GitOpsPrAdapter)
    # Non-secret config surface is inspectable (secrets - token - are not).
    assert publisher._config.default_branch == "trunk"
    assert publisher._config.api_base == "https://ghe.example.com/api/v3"
    assert publisher._config.owner == "example-org"
    assert publisher._config.repo == "example-repo"


# ---------------------------------------------------------------------------
# _build_pattern_library - PatternLibrary selection (T1 similarity reuse)
# ---------------------------------------------------------------------------


def _clear_pattern_library_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FDAI_T1_PATTERN_LIBRARY_DSN",
        "FDAI_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS",
        "FDAI_T1_PATTERN_LIBRARY_IVFFLAT_PROBES",
    ):
        monkeypatch.delenv(name, raising=False)


def test_build_pattern_library_defaults_to_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    from fdai.core.tiers.t1_lightweight.testing import InMemoryPatternLibrary

    library = _build_pattern_library()
    assert isinstance(library, InMemoryPatternLibrary)


def test_build_pattern_library_selects_pgvector_when_dsn_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    monkeypatch.setenv(
        "FDAI_T1_PATTERN_LIBRARY_DSN",
        "postgresql://user:pw@example:5432/db",
    )
    from fdai.delivery.persistence import PgVectorPatternLibrary

    library = _build_pattern_library()
    assert isinstance(library, PgVectorPatternLibrary)


def test_build_pattern_library_honors_tuning_envs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    monkeypatch.setenv(
        "FDAI_T1_PATTERN_LIBRARY_DSN",
        "postgresql://user:pw@example:5432/db",
    )
    monkeypatch.setenv("FDAI_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS", "5000")
    monkeypatch.setenv("FDAI_T1_PATTERN_LIBRARY_IVFFLAT_PROBES", "25")
    from fdai.delivery.persistence import PgVectorPatternLibrary

    library = _build_pattern_library()
    assert isinstance(library, PgVectorPatternLibrary)
    assert library._config.statement_timeout_ms == 5000
    assert library._config.ivfflat_probes == 25


def test_build_pattern_library_rejects_non_int_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    monkeypatch.setenv(
        "FDAI_T1_PATTERN_LIBRARY_DSN",
        "postgresql://user:pw@example:5432/db",
    )
    monkeypatch.setenv("FDAI_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS", "abc")
    with pytest.raises(RuntimeError, match="not an integer"):
        _build_pattern_library()


def test_build_pattern_library_rejects_nonpositive_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    monkeypatch.setenv(
        "FDAI_T1_PATTERN_LIBRARY_DSN",
        "postgresql://user:pw@example:5432/db",
    )
    monkeypatch.setenv("FDAI_T1_PATTERN_LIBRARY_STATEMENT_TIMEOUT_MS", "0")
    with pytest.raises(RuntimeError, match="MUST be >= 1"):
        _build_pattern_library()


def test_build_pattern_library_rejects_non_int_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    monkeypatch.setenv(
        "FDAI_T1_PATTERN_LIBRARY_DSN",
        "postgresql://user:pw@example:5432/db",
    )
    monkeypatch.setenv("FDAI_T1_PATTERN_LIBRARY_IVFFLAT_PROBES", "not-int")
    with pytest.raises(RuntimeError, match="not an integer"):
        _build_pattern_library()


def test_build_pattern_library_rejects_nonpositive_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_pattern_library_env(monkeypatch)
    monkeypatch.setenv(
        "FDAI_T1_PATTERN_LIBRARY_DSN",
        "postgresql://user:pw@example:5432/db",
    )
    monkeypatch.setenv("FDAI_T1_PATTERN_LIBRARY_IVFFLAT_PROBES", "0")
    with pytest.raises(RuntimeError, match="MUST be >= 1"):
        _build_pattern_library()


# ---------------------------------------------------------------------------
# _build_hil_channel - HilChannel selection (ChatOps A1 approvals)
# ---------------------------------------------------------------------------


def _clear_chatops_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FDAI_CHATOPS_WEBHOOK_URL",
        "FDAI_CHATOPS_WEBHOOK_SECRET",
        "FDAI_CHATOPS_APPROVE_CALLBACK_URL",
        "FDAI_CHATOPS_REJECT_CALLBACK_URL",
        "FDAI_CHATOPS_TIMEOUT_SECONDS",
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
        "FDAI_CHATOPS_WEBHOOK_URL",
        "https://teams.example.com/hook/abc",
    )
    from fdai.delivery.chatops.teams_adapter import TeamsHilAdapter

    channel = _build_hil_channel(http_client=httpx.AsyncClient())
    assert isinstance(channel, TeamsHilAdapter)


def test_build_hil_channel_requires_http_client_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chatops_env(monkeypatch)
    monkeypatch.setenv(
        "FDAI_CHATOPS_WEBHOOK_URL",
        "https://teams.example.com/hook/abc",
    )
    with pytest.raises(RuntimeError, match="no HTTP client is available"):
        _build_hil_channel(http_client=None)


def test_build_hil_channel_passes_secret_and_callbacks_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chatops_env(monkeypatch)
    monkeypatch.setenv(
        "FDAI_CHATOPS_WEBHOOK_URL",
        "https://teams.example.com/hook/abc",
    )
    monkeypatch.setenv("FDAI_CHATOPS_WEBHOOK_SECRET", "shhh")
    monkeypatch.setenv(
        "FDAI_CHATOPS_APPROVE_CALLBACK_URL",
        "https://api.example.com/approve",
    )
    monkeypatch.setenv(
        "FDAI_CHATOPS_REJECT_CALLBACK_URL",
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
        "FDAI_CHATOPS_WEBHOOK_URL",
        "https://teams.example.com/hook/abc",
    )
    monkeypatch.setenv("FDAI_CHATOPS_TIMEOUT_SECONDS", "not-a-number")
    with pytest.raises(RuntimeError, match="not a float"):
        _build_hil_channel(http_client=httpx.AsyncClient())


def test_build_hil_channel_rejects_nonpositive_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chatops_env(monkeypatch)
    monkeypatch.setenv(
        "FDAI_CHATOPS_WEBHOOK_URL",
        "https://teams.example.com/hook/abc",
    )
    monkeypatch.setenv("FDAI_CHATOPS_TIMEOUT_SECONDS", "0")
    with pytest.raises(RuntimeError, match="MUST be > 0"):
        _build_hil_channel(http_client=httpx.AsyncClient())


def test_build_hil_channel_honors_timeout_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_chatops_env(monkeypatch)
    monkeypatch.setenv(
        "FDAI_CHATOPS_WEBHOOK_URL",
        "https://teams.example.com/hook/abc",
    )
    monkeypatch.setenv("FDAI_CHATOPS_TIMEOUT_SECONDS", "42.5")

    channel = _build_hil_channel(http_client=httpx.AsyncClient())
    assert channel is not None
    assert channel._config.timeout_seconds == 42.5


def _clear_email_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FDAI_EMAIL_ENDPOINT",
        "FDAI_EMAIL_SENDER_ADDRESS",
        "FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON",
        "FDAI_NOTIFICATION_MI_CLIENT_ID",
        "IDENTITY_ENDPOINT",
        "IDENTITY_HEADER",
    ):
        monkeypatch.delenv(name, raising=False)


def test_build_notification_registry_is_empty_when_email_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_email_env(monkeypatch)
    assert _build_notification_registry(None).channels == {}


def test_build_notification_registry_binds_a2_and_a4_email_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_email_env(monkeypatch)
    monkeypatch.setenv("FDAI_EMAIL_ENDPOINT", "https://acs.example")
    monkeypatch.setenv("FDAI_EMAIL_SENDER_ADDRESS", "sender@example.com")
    monkeypatch.setenv(
        "FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON",
        '["operator@example.com", "operator@example.com"]',
    )
    monkeypatch.setenv("FDAI_NOTIFICATION_MI_CLIENT_ID", "notification-client")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/identity")
    monkeypatch.setenv("IDENTITY_HEADER", "identity-header")

    registry = _build_notification_registry(httpx.AsyncClient())

    assert set(registry.channels) == {"email-oncall", "email-governance"}
    channel = registry.channels["email-oncall"]
    assert channel._config.recipient_addresses == ("operator@example.com",)


def test_build_notification_registry_rejects_partial_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_email_env(monkeypatch)
    monkeypatch.setenv("FDAI_EMAIL_ENDPOINT", "https://acs.example")
    with pytest.raises(RuntimeError, match="requires FDAI_EMAIL_SENDER_ADDRESS"):
        _build_notification_registry(httpx.AsyncClient())


# ---------------------------------------------------------------------------
# Wave 3 step B pipeline slice 2: operator-memory store composition wire
# ---------------------------------------------------------------------------


def test_build_operator_memory_store_defaults_to_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``FDAI_OPERATOR_MEMORY_DSN`` the composition root
    MUST wire the deterministic in-memory fake so the operator-memory
    layer is fully reachable without a database."""

    monkeypatch.delenv("FDAI_OPERATOR_MEMORY_DSN", raising=False)
    from fdai.__main__ import _build_operator_memory_store
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore

    store = _build_operator_memory_store()
    assert isinstance(store, InMemoryOperatorMemoryStore)


def test_build_operator_memory_store_selects_postgres_when_dsn_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DSN opts the process into the durable Postgres backend so
    operator notes survive restarts. Adapter is constructed lazily -
    the DSN is validated but no connection is opened here."""

    monkeypatch.setenv(
        "FDAI_OPERATOR_MEMORY_DSN",
        "postgresql://user:pw@example:5432/db",
    )
    from fdai.__main__ import _build_operator_memory_store
    from fdai.delivery.persistence import PostgresOperatorMemoryStore

    store = _build_operator_memory_store()
    assert isinstance(store, PostgresOperatorMemoryStore)


def test_build_operator_memory_store_rejects_empty_dsn_via_postgres_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank DSN is treated as unset (env var absent) so the wire falls
    back to in-memory rather than instantiating a broken Postgres
    adapter."""

    monkeypatch.setenv("FDAI_OPERATOR_MEMORY_DSN", "")
    from fdai.__main__ import _build_operator_memory_store
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore

    store = _build_operator_memory_store()
    # ``os.environ.get`` returns "" here; ``if dsn:`` treats "" as falsy
    # so we land on the in-memory branch. Guarding against a future
    # regression that would accept "" as a real DSN.
    assert isinstance(store, InMemoryOperatorMemoryStore)


# ---------------------------------------------------------------------------
# _build_direct_api_executor - direct-api sibling selection (Wave W2.3e)
# ---------------------------------------------------------------------------


def test_build_direct_api_executor_defaults_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No opt-in env -> None. PR-native remains the sole dispatch path."""

    monkeypatch.delenv("FDAI_DIRECT_API_FAKE", raising=False)
    from fdai.__main__ import _build_direct_api_executor
    from fdai.core.executor.lock import ResourceLockManager
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    got = _build_direct_api_executor(
        audit_store=InMemoryStateStore(),
        resource_lock=ResourceLockManager(),
    )
    assert got is None


def test_build_direct_api_executor_empty_env_still_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FDAI_DIRECT_API_FAKE='' is treated as unset (fail-safe default)."""

    monkeypatch.setenv("FDAI_DIRECT_API_FAKE", "")
    from fdai.__main__ import _build_direct_api_executor
    from fdai.core.executor.lock import ResourceLockManager
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    got = _build_direct_api_executor(
        audit_store=InMemoryStateStore(),
        resource_lock=ResourceLockManager(),
    )
    assert got is None


def test_build_direct_api_executor_arbitrary_value_still_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the literal string '1' opts in; other truthy-looking values
    stay off so a typo cannot silently enable the direct-api path."""

    monkeypatch.setenv("FDAI_DIRECT_API_FAKE", "true")
    from fdai.__main__ import _build_direct_api_executor
    from fdai.core.executor.lock import ResourceLockManager
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    got = _build_direct_api_executor(
        audit_store=InMemoryStateStore(),
        resource_lock=ResourceLockManager(),
    )
    assert got is None


def test_build_direct_api_executor_opt_in_returns_wrapped_fake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FDAI_DIRECT_API_FAKE='1' -> DirectApiShadowExecutor wrapping
    the RecordingDirectApiExecutor fake."""

    monkeypatch.setenv("FDAI_DIRECT_API_FAKE", "1")
    from fdai.__main__ import _build_direct_api_executor
    from fdai.core.executor.direct_api import DirectApiShadowExecutor
    from fdai.core.executor.lock import ResourceLockManager
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    got = _build_direct_api_executor(
        audit_store=InMemoryStateStore(),
        resource_lock=ResourceLockManager(),
    )
    assert isinstance(got, DirectApiShadowExecutor)


def test_build_direct_api_executor_shares_audit_and_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wrapped executor holds the exact audit_store + resource_lock
    passed in (composition-root contract)."""

    monkeypatch.setenv("FDAI_DIRECT_API_FAKE", "1")
    from fdai.__main__ import _build_direct_api_executor
    from fdai.core.executor.lock import ResourceLockManager
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    audit = InMemoryStateStore()
    lock = ResourceLockManager()
    got = _build_direct_api_executor(audit_store=audit, resource_lock=lock)
    assert got is not None
    # Introspect the private fields to prove the contract; the test is
    # OK to touch these because it lives in the same repo and the
    # composition wire is safety-critical.
    assert got._audit_store is audit
    assert got._resource_lock is lock


# ---------------------------------------------------------------------------
# _build_control_loop - detection/HIL seams wiring
# ---------------------------------------------------------------------------


def test_build_tool_executor_wires_configured_jira_shadow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.__main__ import _build_tool_executor
    from fdai.core.executor.lock import ResourceLockManager
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    monkeypatch.setenv("FDAI_JIRA_BASE_URL", "https://jira.example.com")
    monkeypatch.setenv("FDAI_JIRA_ACCOUNT_EMAIL", "operator@example.com")
    monkeypatch.setenv("FDAI_JIRA_API_TOKEN_SECRET", "jira-token")
    monkeypatch.setenv(
        "FDAI_JIRA_TOOL_MAP_JSON",
        '{"tool.open-incident-ticket":"OPS"}',
    )
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example")
    client = httpx.AsyncClient()

    executor = _build_tool_executor(
        audit_store=InMemoryStateStore(),
        resource_lock=ResourceLockManager(),
        http_client=client,
    )

    assert executor is not None
    assert executor._enforce is False  # noqa: SLF001 - composition assertion
    asyncio.run(client.aclose())


def test_build_tool_executor_jira_enforce_requires_explicit_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.__main__ import _build_tool_executor
    from fdai.core.executor.lock import ResourceLockManager
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    monkeypatch.setenv("FDAI_JIRA_BASE_URL", "https://jira.example.com")
    monkeypatch.setenv("FDAI_JIRA_ACCOUNT_EMAIL", "operator@example.com")
    monkeypatch.setenv("FDAI_JIRA_API_TOKEN_SECRET", "jira-token")
    monkeypatch.setenv(
        "FDAI_JIRA_TOOL_MAP_JSON",
        '{"tool.open-incident-ticket":"OPS"}',
    )
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example")
    monkeypatch.setenv("FDAI_JIRA_ENFORCE", "1")
    client = httpx.AsyncClient()

    executor = _build_tool_executor(
        audit_store=InMemoryStateStore(),
        resource_lock=ResourceLockManager(),
        http_client=client,
    )

    assert executor is not None
    assert executor._enforce is True  # noqa: SLF001 - composition assertion
    asyncio.run(client.aclose())


def test_build_control_loop_wires_rca_and_correlator(
    monkeypatch: pytest.MonkeyPatch, app_config: AppConfig
) -> None:
    """The loop always carries an RCA coordinator + event correlator
    (read-only explanation seams), regardless of the HIL channel."""
    monkeypatch.delenv("FDAI_CHATOPS_WEBHOOK_URL", raising=False)
    from fdai.__main__ import _build_control_loop
    from fdai.composition import default_container

    container = default_container(app_config)
    loop = _build_control_loop(container, http_client=None)
    assert loop._rca_coordinator is not None
    assert loop._rca_coordinator.has_symptom_index
    assert loop._event_correlator is not None
    assert loop._risk_table is not None
    assert loop._risk_table.version == "1.0.0"
    assert loop._risk_gate is not None
    assert loop._risk_gate._exemptions is container.exemption_registry
    assert loop._t1_engine is not None
    assert loop._t2_engine is not None
    assert loop._inventory_age_provider is None


def test_build_control_loop_requires_opa_in_production(
    monkeypatch: pytest.MonkeyPatch,
    app_config: AppConfig,
) -> None:
    from fdai.__main__ import _build_control_loop
    from fdai.composition import default_container
    from fdai.core.tiers.t0_deterministic import opa_evaluator

    monkeypatch.setenv("RUNTIME_ENV", "prod")
    monkeypatch.setattr(opa_evaluator.shutil, "which", lambda _binary: None)

    with pytest.raises(RuntimeError, match="requires the OPA binary"):
        _build_control_loop(default_container(app_config), http_client=None)


def test_build_control_loop_keeps_opa_abstain_fallback_in_dev(
    monkeypatch: pytest.MonkeyPatch,
    app_config: AppConfig,
) -> None:
    from fdai.__main__ import _build_control_loop
    from fdai.composition import default_container
    from fdai.core.tiers.t0_deterministic import AbstainEvaluator, opa_evaluator

    monkeypatch.setenv("RUNTIME_ENV", "dev")
    monkeypatch.setattr(opa_evaluator.shutil, "which", lambda _binary: None)

    loop = _build_control_loop(default_container(app_config), http_client=None)

    assert isinstance(loop._t0_engine._evaluator, AbstainEvaluator)


def test_build_control_loop_uses_injected_symptom_index(app_config: AppConfig) -> None:
    from fdai.__main__ import _build_control_loop
    from fdai.composition import default_container
    from fdai.core.chaos.symptom_index import build_from_entries

    symptom_index = build_from_entries([])
    loop = _build_control_loop(
        default_container(app_config),
        http_client=None,
        symptom_index=symptom_index,
    )

    assert loop._rca_coordinator._symptom_index is symptom_index  # noqa: SLF001


def test_build_control_loop_uses_injected_stage_publisher(
    app_config: AppConfig,
) -> None:
    from fdai.__main__ import _build_control_loop
    from fdai.composition import default_container
    from fdai.shared.providers.testing import RecordingStagePublisher

    publisher = RecordingStagePublisher()
    loop = _build_control_loop(
        default_container(app_config),
        http_client=None,
        stage_publisher=publisher,
    )

    assert loop._stage_publisher is publisher


def test_build_control_loop_wires_inventory_age_provider(
    monkeypatch: pytest.MonkeyPatch, app_config: AppConfig
) -> None:
    monkeypatch.setenv("FDAI_INVENTORY_DSN", "postgresql://example/db")
    from fdai.__main__ import _build_control_loop
    from fdai.composition import default_container

    loop = _build_control_loop(default_container(app_config), http_client=None)
    assert loop._inventory_age_provider is not None
    # No push channel configured -> coordinator still parks durably for
    # the persisted queue/callback path.
    assert loop._hil_resume_coordinator is not None


def test_build_control_loop_wires_hil_coordinator_when_webhook_set(
    monkeypatch: pytest.MonkeyPatch, app_config: AppConfig
) -> None:
    """Setting the ChatOps webhook opts the loop into the HIL approval
    round-trip: a HIL-routed action parks + pushes an A1 card."""
    monkeypatch.setenv("FDAI_CHATOPS_WEBHOOK_URL", "https://example.com/webhook")
    from fdai.__main__ import _build_control_loop
    from fdai.composition import default_container

    loop = _build_control_loop(default_container(app_config), http_client=httpx.AsyncClient())
    assert loop._hil_resume_coordinator is not None
