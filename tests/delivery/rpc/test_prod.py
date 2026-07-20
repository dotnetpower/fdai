"""Production typed RPC app composition tests."""

from __future__ import annotations

from collections.abc import Mapping

from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.conversation import RuntimeToolDiscovery, ToolSchema
from fdai.core.rpc import (
    InMemoryRpcIdempotencyStore,
    RpcMethod,
    RpcScope,
)
from fdai.core.skills import RuntimeSkill, RuntimeSkillDisclosure, SkillCatalog, skill_body_digest
from fdai.core.supply_chain import (
    TrustedArtifactKind,
    TrustedArtifactRecord,
)
from fdai.delivery.read_api.production.skills import build_production_skill_runtime
from fdai.delivery.rpc.prod import ProductionRpcConfig, build_production_rpc_app


def _discovery() -> RuntimeToolDiscovery:
    schema = ToolSchema(
        verb="query_inventory",
        tool_name="inventory.query",
        argument_hint="<resource-type>",
        summary="Read inventory.",
        rbac_floor="reader",
        side_effect_class="read",
    )
    return RuntimeToolDiscovery(
        schemas=(schema,),
        installed_tool_names=frozenset({schema.tool_name}),
    )


async def _authorize(_request: Request) -> frozenset[RpcScope]:
    return frozenset({RpcScope.READ, RpcScope.WRITE})


class _EmptyTrustedArtifactStore:
    async def list(self, kind: TrustedArtifactKind) -> tuple[TrustedArtifactRecord, ...]:
        assert kind in {TrustedArtifactKind.SKILL, TrustedArtifactKind.SKILL_BUNDLE}
        return ()

    async def get(
        self,
        kind: TrustedArtifactKind,
        artifact_id: str,
    ) -> TrustedArtifactRecord | None:
        del kind, artifact_id
        return None

    async def put(
        self,
        record: TrustedArtifactRecord,
        *,
        expected_revision: int,
    ) -> TrustedArtifactRecord:
        del record, expected_revision
        raise AssertionError("RPC skill startup MUST NOT mutate trusted artifacts")


def test_production_app_exposes_health_and_builtin_tool_discovery() -> None:
    app = build_production_rpc_app(
        config=ProductionRpcConfig(dsn="postgresql://example"),
        discovery=_discovery(),
        authorize=_authorize,
        idempotency_store=InMemoryRpcIdempotencyStore(),
    )
    client = TestClient(app)

    assert client.get("/healthz").json() == {"status": "ok"}
    response = client.post(
        "/rpc",
        json={
            "schema_version": "1.0.0",
            "request_id": "request-1",
            "method": "tools.search",
            "params": {"query": "inventory"},
            "idempotency_key": None,
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["tools"][0]["name"] == "inventory.query"
    methods = app.state.rpc_registry.discover(frozenset({RpcScope.READ}))
    assert all(not method["name"].startswith("skills.") for method in methods)


class _Verifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return True


def _skill_disclosure() -> RuntimeSkillDisclosure:
    body = "Read inventory evidence only."
    raw = f"""---
name: inventory-evidence
version: 1.0.0
description: Read inventory evidence.
source: source:inventory-evidence
body_sha256: "{skill_body_digest(body)}"
required_tools: [inventory.query]
allowed_agents: [Bragi]
---
{body}
""".encode()
    catalog = (
        SkillCatalog()
        .install(raw, verifier=_Verifier())
        .enable(
            "inventory-evidence",
            available_tools=frozenset({"inventory.query"}),
            known_agents=frozenset({"Bragi"}),
        )
    )
    return RuntimeSkillDisclosure(
        catalog=catalog,
        verifier=_Verifier(),
        agent="Bragi",
        available_tools=frozenset({"inventory.query"}),
    )


def test_production_app_registers_skill_methods_only_when_configured() -> None:
    app = build_production_rpc_app(
        config=ProductionRpcConfig(dsn="postgresql://example"),
        discovery=_discovery(),
        authorize=_authorize,
        idempotency_store=InMemoryRpcIdempotencyStore(),
        skill_disclosure=_skill_disclosure(),
    )

    methods = app.state.rpc_registry.discover(frozenset({RpcScope.READ}))

    assert {method["name"] for method in methods if method["name"].startswith("skills.")} == {
        "skills.describe",
        "skills.diagnostics",
        "skills.list",
        "skills.load",
        "skills.read_reference",
    }


async def test_production_skill_runtime_disclosure_is_consumed_by_opt_in_rpc() -> None:
    skill_runtime = build_production_skill_runtime(
        env={},
        dsn="postgresql://example",
        statement_timeout_ms=1,
        connect_timeout_s=1,
        store=_EmptyTrustedArtifactStore(),
    )
    await skill_runtime.startup()

    app = build_production_rpc_app(
        config=ProductionRpcConfig(dsn="postgresql://example"),
        discovery=_discovery(),
        authorize=_authorize,
        idempotency_store=InMemoryRpcIdempotencyStore(),
        skill_disclosure=skill_runtime.disclosure,
    )

    methods = app.state.rpc_registry.discover(frozenset({RpcScope.READ}))
    skill_methods = {method["name"] for method in methods if method["name"].startswith("skills.")}
    assert skill_methods == {
        "skills.describe",
        "skills.diagnostics",
        "skills.list",
        "skills.load",
        "skills.read_reference",
    }


async def _request_workflow(params: Mapping[str, object]) -> Mapping[str, object]:
    return {"status": "submitted", "name": params.get("name", "")}


def test_explicit_side_effect_method_uses_injected_claim_store() -> None:
    app = build_production_rpc_app(
        config=ProductionRpcConfig(dsn="postgresql://example"),
        discovery=_discovery(),
        authorize=_authorize,
        additional_methods=(
            RpcMethod(
                name="workflow.request",
                description="Submit a typed workflow proposal.",
                required_scope=RpcScope.WRITE,
                handler=_request_workflow,
                side_effect=True,
            ),
        ),
        idempotency_store=InMemoryRpcIdempotencyStore(),
    )
    client = TestClient(app)
    payload = {
        "schema_version": "1.0.0",
        "request_id": "request-1",
        "method": "workflow.request",
        "params": {"name": "example"},
        "idempotency_key": "same-key",
    }

    first = client.post("/rpc", json=payload).json()
    payload["request_id"] = "request-2"
    second = client.post("/rpc", json=payload).json()

    assert first["result"] == second["result"]
    assert second["request_id"] == "request-2"
