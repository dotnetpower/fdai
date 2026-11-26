from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.executor.direct_api import DirectApiExecutionOutcome
from fdai.core.risk_gate.gate import RiskGate
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.delivery.persistence.state_store_action_promotion import StateStoreActionPromotionRegistry
from fdai.runtime.isolated_executor_client import EventBusDirectApiExecutionClient
from fdai.runtime.safeguard_isolated_executor import SafeguardBoundEventBusDirectApiExecutionClient
from fdai.shared.contracts.models import Autonomy, Mode, OntologyActionType, Operation
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.venue import ExecutionVenue
from tests.core.executor.test_direct_api_executor import _action as _direct_action
from tests.core.executor.test_executor import _rule
from tests.core.executor.test_safeguard_lifecycle_coordinator import _coordinator

from fdai_aks_commerce import (
    AsyncPlaywrightStorefrontDriver,
    StorefrontJourneyConfig,
    storefront_browser_policy,
)
from fdai_aks_commerce.acceptance import OrderAcceptanceIntent
from fdai_aks_commerce.acceptance_dispatch import AcceptanceIsolatedDispatch
from fdai_aks_commerce.acceptance_material import AcceptanceDispatchMaterial
from fdai_aks_commerce.acceptance_runtime import (
    AcceptanceRuntimeConfig,
    build_recovery_bindings,
    run_acceptance_tick,
)
from fdai_aks_commerce.acceptance_runtime import (
    main as runtime_main,
)

FIXED_NOW = datetime(2026, 9, 17, tzinfo=UTC)


def test_storefront_policy_is_https_read_only_and_exact_host() -> None:
    policy = storefront_browser_policy("store.example.com")

    assert policy.allowed_schemes == ("https",)
    assert policy.allowed_hosts == ("store.example.com",)
    assert policy.auth_profile_ref == "auth-profile:anonymous-read"
    assert policy.redirect_policy.max_redirects == 0


def test_storefront_journey_requires_credential_free_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        StorefrontJourneyConfig(
            url="http://store.example.com",
            authorization_ref="standing-authorization:synthetic-order",
            authorization_expires_at=FIXED_NOW + timedelta(hours=1),
        )

    with pytest.raises(ValueError, match="HTTPS"):
        StorefrontJourneyConfig(
            url="https://user:password@store.example.com",
            authorization_ref="standing-authorization:synthetic-order",
            authorization_expires_at=FIXED_NOW + timedelta(hours=1),
        )


def test_storefront_journey_requires_an_opaque_authorization_reference() -> None:
    with pytest.raises(ValueError, match="authorization_ref"):
        StorefrontJourneyConfig(
            url="https://store.example.com",
            authorization_ref="token=not-allowed",
            authorization_expires_at=FIXED_NOW + timedelta(hours=1),
        )
    with pytest.raises(ValueError, match="timeout must be in"):
        StorefrontJourneyConfig(
            url="https://store.example.com",
            authorization_ref="standing-authorization:synthetic-order",
            authorization_expires_at=FIXED_NOW + timedelta(hours=1),
            timeout_seconds=0,
        )
    with pytest.raises(ValueError, match="selectors and labels must be bounded"):
        StorefrontJourneyConfig(
            url="https://store.example.com",
            authorization_ref="standing-authorization:synthetic-order",
            authorization_expires_at=FIXED_NOW + timedelta(hours=1),
            product_selector="",
        )
    with pytest.raises(ValueError, match="expiry must be timezone-aware"):
        StorefrontJourneyConfig(
            url="https://store.example.com",
            authorization_ref="standing-authorization:synthetic-order",
            authorization_expires_at=datetime(2026, 9, 17),
        )


async def test_expired_authorization_stops_before_browser_launch() -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    driver = AsyncPlaywrightStorefrontDriver(clock=lambda: now)
    config = StorefrontJourneyConfig(
        url="https://store.example.com",
        authorization_ref="standing-authorization:synthetic-order",
        authorization_expires_at=now - timedelta(seconds=1),
    )

    with pytest.raises(RuntimeError, match="expired"):
        await driver.run(config)


class _Route:
    def __init__(self) -> None:
        self.continued = 0
        self.aborted = 0

    async def continue_(self) -> None:
        self.continued += 1

    async def abort(self, reason: str) -> None:
        assert reason == "blockedbyclient"
        self.aborted += 1


class _Page:
    def __init__(self, *, now: list[datetime], behavior: str) -> None:
        self.now = now
        self.behavior = behavior
        self.requests: list[_Route] = []
        self.closed = False
        self.button = ""
        self.handler: Any = None
        self.dialog_handler: Any = None
        self.response_handler: Any = None

    async def route(self, pattern: str, handler: Any) -> None:
        self.handler = handler

    async def goto(self, url: str, **kwargs: Any) -> SimpleNamespace:
        if self.behavior == "timeout":
            await asyncio.Future()
        if self.behavior == "goto_500":
            return SimpleNamespace(status=500)
        get_route = _Route()
        await self.handler(get_route, SimpleNamespace(url=url, method="GET"))
        await self.response_handler(
            SimpleNamespace(request=SimpleNamespace(url=url, method="GET"), status=200)
        )
        return SimpleNamespace(status=200)

    def locator(self, selector: str) -> _Page:
        return self

    @property
    def first(self) -> _Page:
        return self

    async def wait_for(self, **kwargs: Any) -> None:
        pass

    def get_by_role(self, role: str, *, name: str) -> _Page:
        self.button = name
        return self

    async def click(self, **kwargs: Any) -> None:
        if self.button != "Proceed to Checkout":
            return
        if self.behavior == "expired":
            self.now[0] += timedelta(minutes=2)
        for _attempt in range(2 if self.behavior == "duplicate" else 1):
            route = _Route()
            self.requests.append(route)
            url = (
                "https://other.example.com/api/orders"
                if self.behavior == "cross_origin"
                else "https://store.example.com/api/orders"
            )
            await self.handler(route, SimpleNamespace(url=url, method="POST"))
            if route.continued and self.behavior != "missing_response":
                await self.response_handler(
                    SimpleNamespace(
                        request=SimpleNamespace(url=url, method="POST"),
                        status=503 if self.behavior == "failed_response" else 201,
                    )
                )
        self.now[0] += timedelta(seconds=1)

        async def dismiss() -> None:
            pass

        msg = (
            "Unexpected dialog" if self.behavior == "bad_dialog" else "Order submitted successfully"
        )
        await self.dialog_handler(SimpleNamespace(message=msg, dismiss=dismiss))
        await self.dialog_handler(SimpleNamespace(message=msg, dismiss=dismiss))
        if self.behavior == "late_expired":
            self.now[0] += timedelta(minutes=2)

    def once(self, event: str, handler: Any) -> None:
        assert event == "dialog"
        self.dialog_handler = handler

    def on(self, event: str, handler: Any) -> None:
        assert event == "response"
        self.response_handler = handler

    async def new_context(self, **kwargs: Any) -> _Page:
        return self

    async def new_page(self) -> _Page:
        return self

    async def close(self) -> None:
        self.closed = True

    async def launch(self, **kwargs: Any) -> _Page:
        return self

    async def __aenter__(self) -> SimpleNamespace:
        return SimpleNamespace(chromium=self)

    async def __aexit__(self, *args: Any) -> None:
        pass


@pytest.mark.parametrize(
    "behavior",
    [
        "normal",
        "duplicate",
        "expired",
        "cross_origin",
        "timeout",
        "goto_500",
        "bad_dialog",
        "late_expired",
        "failed_response",
        "missing_response",
    ],
)
async def test_journey_request_limits_and_completion_time(
    monkeypatch: pytest.MonkeyPatch, behavior: str
) -> None:
    started_at = datetime(2026, 9, 17, tzinfo=UTC)
    now = [started_at]
    page = _Page(now=now, behavior=behavior)
    monkeypatch.setattr(
        "fdai_aks_commerce.synthetic.importlib.import_module",
        lambda name: SimpleNamespace(async_playwright=lambda: page),
    )
    config = StorefrontJourneyConfig(
        url="https://store.example.com",
        authorization_ref="standing-authorization:synthetic-order",
        authorization_expires_at=started_at + timedelta(minutes=1),
        timeout_seconds=1,
    )

    result = await AsyncPlaywrightStorefrontDriver(clock=lambda: now[0]).run(config)

    assert page.closed
    assert result.execution_authority is False
    assert result.success is (behavior == "normal")
    assert result.observed_at == now[0]
    if behavior == "normal":
        assert result.observed_at > started_at
        assert sum(request.continued for request in page.requests) == 1
    elif behavior == "duplicate":
        assert sum(request.continued for request in page.requests) == 1
        assert sum(request.aborted for request in page.requests) == 1
    elif behavior in {"expired", "cross_origin"}:
        assert sum(request.continued for request in page.requests) == 0
    elif behavior in {"failed_response", "missing_response"}:
        assert result.failed_step == "order_response"
        assert result.order_http_status == (503 if behavior == "failed_response" else None)
    elif behavior == "bad_dialog":
        assert result.failed_step == "submit_order"
    elif behavior == "late_expired":
        assert result.failed_step == "authorization"
    else:
        assert result.failed_step == "browse"
        assert result.duration_ms < 3000


async def test_driver_rejects_naive_clock_and_missing_playwright(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = StorefrontJourneyConfig(
        url="https://store.example.com",
        authorization_ref="standing-authorization:synthetic-order",
        authorization_expires_at=FIXED_NOW + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="clock must be timezone-aware"):
        await AsyncPlaywrightStorefrontDriver(clock=lambda: datetime(2026, 9, 17)).run(config)

    def _raise_import(_name: str) -> Any:
        raise ImportError("no playwright")

    monkeypatch.setattr("fdai_aks_commerce.synthetic.importlib.import_module", _raise_import)
    with pytest.raises(RuntimeError, match="Playwright is unavailable"):
        await AsyncPlaywrightStorefrontDriver(clock=lambda: FIXED_NOW).run(config)


async def test_acceptance_dispatch_and_runtime_edges(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    intent = OrderAcceptanceIntent(
        policy_ref="policy:example",
        resource_ref="resource:deployment",
        service_resource_ref="resource:service",
        cluster_ref="cluster:example",
        namespace="example-store",
        deployment_name="order-api",
        deployment_uid="uid-order",
        valid_from=FIXED_NOW - timedelta(minutes=1),
        valid_until=FIXED_NOW + timedelta(minutes=1),
    )
    rule = _rule().model_copy(
        update={
            "remediates": "ops.scale-out",
            "resource_type": "kubernetes.deployment",
            "check_logic": _rule().check_logic.model_copy(
                update={"reference": "fdai.aks_commerce.order_acceptance.v1"}
            ),
        }
    )
    action = _direct_action(
        action_id="00000000-0000-0000-0000-000000000010",
        target=intent.resource_ref,
        mode=Mode.ENFORCE,
        citing_rules=(rule.id,),
        params={"target_resource_ref": intent.resource_ref, "replica_count": 1},
    ).model_copy(update={"action_type": "ops.scale-out", "operation": Operation.SCALE})
    material = AcceptanceDispatchMaterial(
        action.model_dump_json(),
        "corr-1",
        "key-1",
    )

    class _PassGuard:
        def bind(self, _ctx: dict[str, Any]) -> Any:
            return _noop_async

    recorded_cmds: list[str] = []

    async def _rec(_act: Any, cmd_id: str) -> None:
        recorded_cmds.append(cmd_id)

    client_result: list[Any] = []

    class _FakeClient:
        async def execute(self, *, action: Any, source_guard: Any) -> Any:
            await source_guard()
            return client_result[0]

    dispatch = AcceptanceIsolatedDispatch(
        guard=_PassGuard(),  # type: ignore[arg-type]
        read_material=lambda _id: _return_val(material),
        check_authority=lambda _act, _ctx: _noop_async(),
        client=_FakeClient(),  # type: ignore[arg-type]
        clock=lambda: FIXED_NOW,
        record_command=_rec,
    )
    base_run = SimpleNamespace(
        action_id=str(action.action_id),
        action_type="ops.scale-out",
        resource_id=intent.resource_ref,
        params=dict(action.params),
        idempotency_key="key-1",
        correlation_id="corr-1",
        rollback_contract=action.rollback_ref.kind.value,
        shadow_mode=False,
        verdict="hil",
        resolved_autonomy_ceiling=Autonomy.ENFORCE_HIL,
        state=SimpleNamespace(value="executing"),
        execution_audit_receipt="receipt:1",
        approval_expires_at=FIXED_NOW + timedelta(seconds=30),
        to_dict=lambda: {"action_id": str(action.action_id)},
    )
    no_id_run = SimpleNamespace(**{**base_run.__dict__, "action_id": ""})
    with pytest.raises(ValueError, match="original prepared Action id"):
        await dispatch({"run": no_id_run})

    client_result[:] = [
        SimpleNamespace(
            action_id=str(action.action_id),
            mode=Mode.ENFORCE,
            outcome=DirectApiExecutionOutcome.AWAITING_EFFECT_EVIDENCE,
            audit_context={"command_id": "cmd-1", "dispatch_status": "pending"},
            safeguard_bundle_digest="sha256:" + "a" * 64,
        )
    ]
    assert await dispatch({"run": base_run}) is True
    assert recorded_cmds == ["cmd-1"]

    client_result[:] = [
        SimpleNamespace(
            action_id=str(action.action_id),
            mode=Mode.ENFORCE,
            outcome=DirectApiExecutionOutcome.AWAITING_EFFECT_EVIDENCE,
            audit_context={"dispatch_status": "pending"},
            safeguard_bundle_digest="",
        )
    ]
    with pytest.raises(TimeoutError, match="receipt is incomplete"):
        await dispatch({"run": base_run})

    client_result[:] = [
        SimpleNamespace(
            action_id=str(action.action_id),
            mode=Mode.ENFORCE,
            outcome="other_outcome",
            audit_context={"effect_possible": True},
            safeguard_bundle_digest="",
        )
    ]
    with pytest.raises(TimeoutError, match="may have been accepted"):
        await dispatch({"run": base_run})

    client_result[:] = [
        SimpleNamespace(
            action_id=str(action.action_id),
            mode=Mode.ENFORCE,
            outcome="other_outcome",
            audit_context={"effect_possible": False},
            safeguard_bundle_digest="",
        )
    ]
    assert await dispatch({"run": base_run}) is False

    key = Ed25519PrivateKey.generate()
    pub_hex = key.public_key().public_bytes_raw().hex()
    base_cfg = {
        "intent": asdict(intent),
        "trust": {
            "key-1": {
                "issuer": "issuer:1",
                "source_identity": "source:1",
                "public_key_hex": pub_hex,
            }
        },
        "executor_identity": "exec:1",
        "severity": "high",
        "publication_window_seconds": 5,
    }
    for override, match in (
        ({"publication_window_seconds": 0}, "publication window must fit"),
        ({"executor_identity": ""}, "executor lineage must be explicit"),
        ({"trust": {}}, "pinned observation keys"),
        ({"trust": {"k": {"issuer": "i"}}}, "trust binding fields are invalid"),
        (
            {"trust": {"k": {"issuer": "", "source_identity": "s", "public_key_hex": pub_hex}}},
            "non-empty strings",
        ),
    ):
        with pytest.raises(ValueError, match=match):
            AcceptanceRuntimeConfig.from_json(
                json.dumps({**base_cfg, **override}, default=lambda v: v.isoformat())
            )

    raw_json = json.dumps(base_cfg, default=lambda v: v.isoformat())
    monkeypatch.setattr(
        "fdai_aks_commerce.acceptance_runtime.resolve_execution_venue",
        lambda _env: None,
    )
    with pytest.raises(RuntimeError, match="deployed observer venue"):
        await run_acceptance_tick({"FDAI_AKS_ACCEPTANCE_JSON": raw_json})

    monkeypatch.setattr(
        "fdai_aks_commerce.acceptance_runtime.resolve_execution_venue",
        lambda _env: ExecutionVenue.DEPLOYED,
    )
    with pytest.raises(RuntimeError, match="FDAI_STATE_STORE_DSN is required"):
        await run_acceptance_tick({"FDAI_AKS_ACCEPTANCE_JSON": raw_json})

    closed_bus: list[bool] = []

    class _FakeBus:
        def __init__(self, **_kw: Any) -> None:
            pass

        async def close(self) -> None:
            closed_bus.append(True)

    class _FakeRunner:
        async def run_once(self, _targets: Any) -> Any:
            return SimpleNamespace(
                targets=1,
                findings=1,
                published=1,
                duplicates_suppressed=0,
                uncertain=0,
                failed=False,
            )

    monkeypatch.setattr(
        "fdai_aks_commerce.acceptance_runtime.PostgresStateStore", lambda **_kw: object()
    )
    monkeypatch.setattr(
        "fdai_aks_commerce.acceptance_runtime.PostgresAnalyzerPublicationLedger",
        lambda **_kw: object(),
    )
    monkeypatch.setattr(
        "fdai_aks_commerce.acceptance_runtime.ManagedIdentityWorkloadIdentity.from_env",
        lambda **_kw: object(),
    )
    monkeypatch.setattr("fdai_aks_commerce.acceptance_runtime.EventHubsKafkaBus", _FakeBus)
    monkeypatch.setattr(
        "fdai_aks_commerce.acceptance_runtime.build_acceptance_runner",
        lambda **_kw: _FakeRunner(),
    )
    tick_report = await run_acceptance_tick(
        {
            "FDAI_AKS_ACCEPTANCE_JSON": raw_json,
            "FDAI_STATE_STORE_DSN": "postgresql+psycopg://localhost:5432/fdai",
            "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
            "KAFKA_TOPIC_EVENTS": "fdai.events",
            "FDAI_MI_CLIENT_ID": "client-1",
        }
    )
    assert tick_report.published == 1
    assert closed_bus == [True]

    store = InMemoryStateStore()
    registry = StateStoreActionPromotionRegistry(store=store)
    action_type = OntologyActionType.model_validate(
        yaml.safe_load(
            (
                Path(__file__).resolve().parents[3] / "rule-catalog/action-types/ops.scale-out.yaml"
            ).read_text()
        )
    )
    coordinator, _lock = _coordinator(store)
    port = SafeguardBoundEventBusDirectApiExecutionClient(
        client=EventBusDirectApiExecutionClient(
            event_bus=InMemoryEventBus(), audit_store=store, instance_id="test"
        ),
        coordinator=coordinator,
    )
    refreshed_ks: list[bool] = []

    async def _ks_refresh() -> None:
        refreshed_ks.append(True)

    loop = SimpleNamespace(
        _rules_by_id={rule.id: rule},
        _action_builder=ActionBuilder({action_type.name: action_type}),
        _risk_gate=RiskGate(registry=registry),
        _risk_table=load_risk_table(
            Path(__file__).resolve().parents[3] / "rule-catalog/risk-classification.yaml"
        ),
        _direct_api_executor=port,
        _kill_switch_refresher=_ks_refresh,
        _kill_switch=SimpleNamespace(is_engaged=lambda: True),
        _degradation=SimpleNamespace(autonomy_permitted=lambda: True),
    )
    env = {
        "FDAI_AKS_ACCEPTANCE_JSON": raw_json,
        "FDAI_AKS_ACCEPTANCE_RULE_ID": rule.id,
        "FDAI_PANTHEON_APPROVER_ACTIONS_JSON": '{"reviewer@example.com":["ops.scale-out"]}',
    }
    with pytest.raises(RuntimeError, match="Incident episode resolution"):
        build_recovery_bindings(
            environment=env,
            loop=loop,  # type: ignore[arg-type]
            store=store,
            fallback=None,
            resolve_verified_incident=None,
        )

    bindings = build_recovery_bindings(
        environment=env,
        loop=loop,  # type: ignore[arg-type]
        store=store,
        fallback=None,
        resolve_verified_incident=lambda **_kw: _return_val("inc:1"),
    )
    with pytest.raises(RuntimeError, match="unbound executor fallback"):
        await bindings.execute({"run": SimpleNamespace(resource_id="resource:other")})
    with pytest.raises(ValueError, match="original prepared Action id"):
        await bindings.execute({"run": no_id_run})
    src_obj = bindings.sources["analyzer.aks_commerce.order_acceptance_unavailable.observed"]
    await src_obj._refresh_policy()  # type: ignore[attr-defined]
    assert refreshed_ks == [True]
    assert bindings.preflight_simulator._check_authority._safety_held() is True  # type: ignore[attr-defined]


async def _noop_async() -> None:
    return None


async def _return_val(value: Any) -> Any:
    return value


def test_acceptance_runtime_main_reports_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = SimpleNamespace(
        targets=1,
        findings=1,
        published=1,
        duplicates_suppressed=0,
        uncertain=0,
        failed=False,
    )
    monkeypatch.setattr(
        "fdai_aks_commerce.acceptance_runtime.run_acceptance_tick",
        lambda: _return_val(report),
    )
    assert runtime_main() == 0
    assert '"published": 1' in capsys.readouterr().out
