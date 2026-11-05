from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import fdai_cost_governance.job_cli as job_cli
from fdai_cost_governance.job_cli import (
    _activation_matches,
    _analytics_event,
    _AzureCliCostCredential,
    _common,
    _cost_retry_after_seconds,
    _HttpxCostTransport,
    _ManagedIdentityCostCredential,
    _positive_int,
    _required,
    _run_analytics_loop,
    _run_analyzer,
    _run_collector,
    analytics_main,
    analyzer_main,
    collector_main,
    run_analytics_from_environment,
)
from fdai_cost_governance.scheduled_analytics import ScheduledAnalyticsResult
from fdai_cost_governance.service import CostJobConfig

_ROOT = Path(__file__).resolve().parents[3]
_PAST = datetime(2000, 1, 1, tzinfo=UTC)
_FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


def test_cost_retry_after_uses_longest_provider_delay_case_insensitively() -> None:
    delay = _cost_retry_after_seconds(
        {
            "Retry-After": "2",
            "x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after": "11",
            "X-MS-RATELIMIT-MICROSOFT.COSTMANAGEMENT-ENTITY-RETRY-AFTER": "7",
            "x-ms-ratelimit-microsoft.costmanagement-tenant-retry-after": "5",
        }
    )

    assert delay == 11


def test_partial_analytics_is_ready_for_available_facets_but_failure_waits() -> None:
    assert _analytics_event("complete") == "ready"
    assert _analytics_event("partial") == "ready"
    assert _analytics_event("disabled") == "ready"
    assert _analytics_event("failed") == "waiting"
    assert _analytics_event("failed", retained_snapshot_current=True) == "ready"


def test_package_declares_shared_and_legacy_job_entrypoints() -> None:
    pyproject = (_ROOT / "extensions/cost-governance/pyproject.toml").read_text(encoding="utf-8")
    assert 'fdai-cost-analytics = "fdai_cost_governance.job_cli:analytics_main"' in pyproject
    assert 'fdai-cost-collector = "fdai_cost_governance.job_cli:collector_main"' in pyproject
    assert 'fdai-cost-analyzer = "fdai_cost_governance.job_cli:analyzer_main"' in pyproject
    assert 'fdai-cost-lifecycle = "fdai_cost_governance.lifecycle_cli:main"' in pyproject
    assert 'fdai-cost-validation = "fdai_cost_governance.validation_cli:main"' in pyproject


def test_shared_analytics_command_selects_only_existing_read_identities() -> None:
    source = (_ROOT / "extensions/cost-governance/src/fdai_cost_governance/job_cli.py").read_text(
        encoding="utf-8"
    )

    assert 'venue_value not in {"local", "deployed"}' in source
    assert "AzureCliCredential()" in source
    assert "ManagedIdentityWorkloadIdentity.from_env" in source
    assert 'client_id_env="FDAI_COST_COLLECTION_MI_CLIENT_ID"' in source
    assert "fdai_cost_governance.scheduled_analytics" not in source
    assert (
        "execution"
        not in (
            _ROOT / "extensions/cost-governance/src/fdai_cost_governance/scheduled_analytics.py"
        )
        .read_text(encoding="utf-8")
        .casefold()
    )


def test_optional_jobs_are_serial_and_use_non_executor_collection_identity() -> None:
    terraform = (_ROOT / "infra/cost_governance_jobs.tf").read_text(encoding="utf-8")
    legacy_path = _ROOT / "infra/modules/compute/container-apps/cost_governance_jobs.tf"

    assert not legacy_path.exists()
    assert terraform.count("parallelism              = 1") == 2
    assert (
        terraform.count(
            "identity_ids = [data.azurerm_user_assigned_identity.cost_governance_inventory[0].id]"
        )
        == 2
    )
    assert "var.finops_identity" not in terraform
    assert 'command = ["fdai-cost-analytics"]' in terraform
    assert 'command = ["fdai-cost-collector"]' not in terraform
    assert 'FDAI_EXECUTION_VENUE      = "deployed"' in terraform
    assert "fdai-cost-analyzer" in terraform
    assert "FDAI_COST_COLLECTION_MI_CLIENT_ID" in terraform
    assert 'data "azurerm_container_app_environment" "cost_governance"' in terraform
    assert 'data "azurerm_user_assigned_identity" "cost_governance_inventory"' in terraform
    assert (
        "from = module.compute.azurerm_container_app_job.cost_governance_collector[0]" in terraform
    )
    assert (
        "from = module.compute.azurerm_container_app_job.cost_governance_analyzer[0]" in terraform
    )
    for unrelated_dependency in (
        "module.compute.environment_id",
        "module.network",
        "module.scheduler_identity",
        "module.state_store",
    ):
        assert unrelated_dependency not in terraform


def test_job_schedules_default_absent() -> None:
    variables = (_ROOT / "infra/variables.tf").read_text(encoding="utf-8")
    for name in (
        "cost_governance_collector_cron_expression",
        "cost_governance_analyzer_cron_expression",
    ):
        declaration = variables.split(f'variable "{name}"', 1)[1].split("}", 1)[0]
        assert 'default     = ""' in declaration


def test_cost_governance_image_is_digest_pinned_and_job_names_are_exported() -> None:
    root_variables = (_ROOT / "infra/variables.tf").read_text(encoding="utf-8")
    root_outputs = (_ROOT / "infra/outputs.tf").read_text(encoding="utf-8")

    declaration = root_variables.split('variable "cost_governance_image"', 1)[1].split("\n}\n", 1)[
        0
    ]
    assert "@sha256:[0-9a-f]{64}" in declaration
    for name in (
        "cost_governance_collector_job_name",
        "cost_governance_analyzer_job_name",
    ):
        assert f'output "{name}"' in root_outputs


def test_cost_retry_after_handles_dates_invalid_values_and_empty_headers() -> None:
    assert _cost_retry_after_seconds({}) is None
    assert (
        _cost_retry_after_seconds(
            {
                "x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after": "not-a-number",
                "retry-after": "not-a-date",
                "x-ms-ratelimit-microsoft.costmanagement-entity-retry-after": "-5",
                "x-ms-ratelimit-microsoft.costmanagement-tenant-retry-after": "nan",
            }
        )
        is None
    )
    naive_delay = _cost_retry_after_seconds({"Retry-After": "Wed, 21 Oct 2099 07:28:00"})
    aware_delay = _cost_retry_after_seconds({"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"})
    assert naive_delay is not None and naive_delay > 0
    assert aware_delay is not None and aware_delay > 0


async def test_credentials_and_httpx_transport_enforce_deadlines_and_byte_budget() -> None:
    @dataclass
    class _FakeToken:
        token: str = "tok-123"

    class _FakeIdentity:
        async def get_token(self, audience: str) -> _FakeToken:
            assert audience.endswith("/.default")
            return _FakeToken()

    mi_cred = _ManagedIdentityCostCredential(_FakeIdentity())  # type: ignore[arg-type]
    with pytest.raises(TimeoutError, match="credential deadline"):
        await mi_cred.access_token(deadline_at=_PAST)
    assert await mi_cred.access_token(deadline_at=_FUTURE) == "tok-123"

    cli_cred = _AzureCliCostCredential(_FakeIdentity())  # type: ignore[arg-type]
    with pytest.raises(TimeoutError, match="credential deadline"):
        await cli_cred.access_token(deadline_at=_PAST)
    assert await cli_cred.access_token(deadline_at=_FUTURE) == "tok-123"

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"ok":true}', headers={"Retry-After": "3"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        transport = _HttpxCostTransport(client)
        with pytest.raises(TimeoutError, match="request deadline"):
            await transport.post(
                "https://example.invalid/cost",
                headers={},
                json_body={},
                max_bytes=100,
                deadline_at=_PAST,
            )
        with pytest.raises(RuntimeError, match="exceeded byte budget"):
            await transport.post(
                "https://example.invalid/cost",
                headers={},
                json_body={},
                max_bytes=2,
                deadline_at=_FUTURE,
            )
        resp = await transport.post(
            "https://example.invalid/cost",
            headers={},
            json_body={},
            max_bytes=100,
            deadline_at=_FUTURE,
        )
        assert resp.status_code == 200
        assert resp.retry_after_seconds == 3.0


async def test_common_helpers_and_activation_matching(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="MUST be set"):
        _required({"KEY": "   "}, "KEY")
    with pytest.raises(ValueError, match="MUST be positive"):
        _positive_int({"NUM": "0"}, "NUM", 1)

    base_env = {
        "FDAI_COST_KNOWN_SERVICE_IDS": '["svc-a"]',
        "FDAI_COST_ONTOLOGY_RELEASE_ID": "rel-1",
        "FDAI_COST_ONTOLOGY_RELEASE_DIGEST": f"sha256:{'a' * 64}",
        "FDAI_COST_STORE_DSN": "postgresql://localhost/fdai",
        "FDAI_COST_SCOPE_ID": "/subscriptions/00000000-0000-0000-0000-000000000000",
    }
    with pytest.raises(ValueError, match="JSON string list"):
        _common({**base_env, "FDAI_COST_KNOWN_SERVICE_IDS": '{"bad": 1}'})

    class _FakeStore:
        def __init__(self, config: Any) -> None:
            self.dsn = config.dsn
            self.snapshot: Any = None

        async def read_cost_activation(self, package_id: str) -> Any:
            return self.snapshot

    monkeypatch.setattr(job_cli, "PostgresCostGovernanceStore", _FakeStore)
    config, scope_id, store = _common(base_env)
    assert scope_id.startswith("/subscriptions/")
    assert await _activation_matches(store, config) is False
    store.snapshot = SimpleNamespace(  # type: ignore[attr-defined]
        package_id="cost-governance",
        available=True,
        enabled=True,
        ontology_release_id="rel-1",
        ontology_release_digest=f"sha256:{'a' * 64}",
        updated_at=_PAST,
    )
    assert await _activation_matches(store, config) is True


async def test_run_analytics_from_environment_and_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[str] = []

    class _FakeStore:
        def __init__(self, config: Any) -> None:
            self.config = config

        async def read_cost_activation(self, package_id: str) -> Any:
            return SimpleNamespace(
                package_id=package_id,
                available=True,
                enabled=True,
                ontology_release_id="rel-store",
                ontology_release_digest=f"sha256:{'b' * 64}",
                updated_at=_PAST,
            )

        async def current_cost_analytics_snapshot_available(self, **kwargs: Any) -> bool:
            return True

    class _FakeCliCred:
        async def close(self) -> None:
            closed.append("cli")

    class _FakeBus:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def close(self) -> None:
            closed.append("bus")

    monkeypatch.setattr(job_cli, "PostgresCostGovernanceStore", _FakeStore)
    monkeypatch.setattr(job_cli, "AzureCliCredential", _FakeCliCred)
    monkeypatch.setattr(
        job_cli.ManagedIdentityWorkloadIdentity,
        "from_env",
        classmethod(lambda cls, **kwargs: SimpleNamespace()),
    )
    monkeypatch.setattr(job_cli, "EventHubsKafkaBus", _FakeBus)
    monkeypatch.setattr(
        job_cli, "EventBusCostSamplePublisher", lambda **kwargs: SimpleNamespace(**kwargs)
    )

    status_box = {"status": "complete"}

    async def _fake_run_scheduled_analytics(**kwargs: Any) -> ScheduledAnalyticsResult:
        receipt = SimpleNamespace(
            status=SimpleNamespace(value=status_box["status"]),
            run_id="run-1",
        )
        return ScheduledAnalyticsResult(
            receipt=receipt,  # type: ignore[arg-type]
            snapshot_stored=False,
            published=0,
            retained_snapshot_current=False,
        )

    monkeypatch.setattr(job_cli, "run_scheduled_analytics", _fake_run_scheduled_analytics)

    env = {
        "FDAI_COST_SCOPE_ID": "/subscriptions/00000000-0000-0000-0000-000000000000",
        "FDAI_COST_STORE_DSN": "postgresql://localhost/fdai",
        "FDAI_EXECUTION_VENUE": "local",
        "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
        "FDAI_COST_RAW_EVENT_TOPIC": "cost.raw",
    }
    res = await run_analytics_from_environment(env, days=7)
    assert res.receipt.status.value == "complete"
    assert closed == ["bus", "cli"]

    with pytest.raises(ValueError, match="FDAI_EXECUTION_VENUE"):
        await run_analytics_from_environment(
            {**env, "FDAI_EXECUTION_VENUE": "invalid"},
            days=7,
        )

    status_box["status"] = "failed"
    res_failed = await run_analytics_from_environment(
        {
            "FDAI_COST_SCOPE_ID": "/subscriptions/00000000-0000-0000-0000-000000000000",
            "FDAI_COST_STORE_DSN": "postgresql://localhost/fdai",
            "FDAI_EXECUTION_VENUE": "deployed",
        },
        days=7,
    )
    assert res_failed.retained_snapshot_current is True

    assert await _run_analytics_loop(env, days=7, interval_seconds=1, loop=False) == 1
    status_box["status"] = "complete"
    assert await _run_analytics_loop(env, days=7, interval_seconds=1, loop=False) == 0

    async def _stop_sleep(seconds: int) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", _stop_sleep)
    with pytest.raises(asyncio.CancelledError):
        await _run_analytics_loop(env, days=7, interval_seconds=1, loop=True)


async def test_collector_analyzer_and_cli_mains(monkeypatch: pytest.MonkeyPatch) -> None:
    base_env = {
        "FDAI_COST_KNOWN_SERVICE_IDS": '["svc-a"]',
        "FDAI_COST_ONTOLOGY_RELEASE_ID": "rel-1",
        "FDAI_COST_ONTOLOGY_RELEASE_DIGEST": f"sha256:{'a' * 64}",
        "FDAI_COST_STORE_DSN": "postgresql://localhost/fdai",
        "FDAI_COST_SCOPE_ID": "/subscriptions/00000000-0000-0000-0000-000000000000",
        "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
        "FDAI_COST_RAW_EVENT_TOPIC": "cost.raw",
    }
    active_box = {"active": False, "status": "complete"}

    monkeypatch.setattr(
        job_cli,
        "PostgresCostGovernanceStore",
        lambda config: SimpleNamespace(dsn=config.dsn),
    )

    async def _fake_matches(store: Any, config: CostJobConfig) -> bool:
        return active_box["active"]

    monkeypatch.setattr(job_cli, "_activation_matches", _fake_matches)
    monkeypatch.setattr(
        job_cli.ManagedIdentityWorkloadIdentity,
        "from_env",
        classmethod(lambda cls, **kwargs: SimpleNamespace()),
    )
    monkeypatch.setattr(job_cli, "EventHubsKafkaBus", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(job_cli, "EventBusCostSamplePublisher", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(
        job_cli,
        "CostCollectorService",
        lambda **kwargs: SimpleNamespace(
            collect=lambda **kw: _async_val(SimpleNamespace(status=active_box["status"]))
        ),
    )
    monkeypatch.setattr(
        job_cli,
        "CostAnalyzerService",
        lambda **kwargs: SimpleNamespace(
            analyze=lambda **kw: _async_val(SimpleNamespace(status=active_box["status"]))
        ),
    )

    assert await _run_collector(base_env) == 0
    assert await _run_analyzer(base_env) == 0
    active_box["active"] = True
    assert await _run_collector(base_env) == 0
    assert await _run_analyzer(base_env) == 0
    active_box["status"] = "failed"
    assert await _run_collector(base_env) == 1
    assert await _run_analyzer(base_env) == 1


def test_cli_mains_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_cli, "_run_collector", lambda env: _async_val(0))
    monkeypatch.setattr(job_cli, "_run_analyzer", lambda env: _async_val(0))
    monkeypatch.setattr(job_cli, "_run_analytics_loop", lambda *a, **kw: _async_val(0))
    with pytest.raises(SystemExit) as exc_col:
        collector_main()
    assert exc_col.value.code == 0
    with pytest.raises(SystemExit) as exc_ana:
        analyzer_main()
    assert exc_ana.value.code == 0

    monkeypatch.setattr("sys.argv", ["fdai-cost-analytics", "--days", "7"])
    with pytest.raises(SystemExit) as exc_main:
        analytics_main()
    assert exc_main.value.code == 0

    monkeypatch.setattr("sys.argv", ["fdai-cost-analytics", "--days", "0"])
    with pytest.raises(SystemExit) as exc_err:
        analytics_main()
    assert exc_err.value.code == 2


async def _async_val(val: Any) -> Any:
    return val
