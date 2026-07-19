from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.delivery.azure.llm.latency_routed_cross_check import (
    ModelFailureKind,
    ModelHealthTransition,
)
from fdai.delivery.azure.llm.model_catalog import (
    GptModelCatalogEntry,
    GptModelCatalogSnapshot,
    ModelSkuAvailability,
)
from fdai.delivery.read_api.routes.chat import LatencyRoutedChatBackend, make_chat_route
from fdai.delivery.read_api.routes.model_settings import (
    ModelSettingsService,
    ModelSettingsUnavailableError,
    make_model_settings_routes,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _Backend:
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {"answer": prompt, "model": "test"}


class _WebSearchResolver:
    def __init__(self) -> None:
        self.enabled = True
        self.domains = ("learn.microsoft.com",)

    def descriptor(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "allowed_domains": list(self.domains),
            "router": {"chose": "narrator-fast", "candidates": []},
        }

    def update_settings(self, *, enabled: bool, allowed_domains: tuple[str, ...]) -> None:
        self.enabled = enabled
        self.domains = allowed_domains


class _RoutingStatus:
    async def list_recent(self, *, limit: int = 200) -> tuple[ModelHealthTransition, ...]:
        del limit
        at = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
        return (
            ModelHealthTransition(
                model_role="t2.reasoner.primary",
                deployment="primary-b",
                status="selected",
                failure_kind=None,
                failure_count=0,
                cooldown_seconds=0,
                recorded_at=at,
                reason="failover_after_1_candidate_failure",
            ),
            ModelHealthTransition(
                model_role="t2.reasoner.primary",
                deployment="primary-a",
                status="recovered",
                failure_kind=None,
                failure_count=0,
                cooldown_seconds=0,
                recorded_at=at,
            ),
            ModelHealthTransition(
                model_role="t2.reasoner.primary",
                deployment="primary-b",
                status="unhealthy",
                failure_kind=ModelFailureKind.RATE_LIMIT,
                failure_count=1,
                cooldown_seconds=60,
                recorded_at=at,
            ),
        )


class _CatalogReader:
    async def snapshot(self, *, force_refresh: bool = False) -> GptModelCatalogSnapshot:
        del force_refresh
        return GptModelCatalogSnapshot(
            region="example-region",
            models=(
                GptModelCatalogEntry(
                    family="gpt-5.4",
                    version="2026-03-05",
                    lifecycle="GenerallyAvailable",
                    skus=(ModelSkuAvailability(name="GlobalStandard", available_tpm=125_000),),
                    deployments=("gpt-5.4",),
                    selectable=True,
                ),
                GptModelCatalogEntry(
                    family="gpt-5.4",
                    version="2026-02-01",
                    lifecycle="GenerallyAvailable",
                    skus=(ModelSkuAvailability(name="GlobalStandard", available_tpm=50000),),
                    deployments=(),
                    selectable=True,
                ),
            ),
        )


def _resolved(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "region": "example-region",
                "mixed_model_mode": "hil-only",
                "capabilities": [
                    {
                        "name": "t1.judge",
                        "status": "resolved",
                        "publisher": "OpenAI",
                        "family": "gpt-mini",
                        "capacity_tpm": 1000,
                        "invocation": "always",
                        "reasons": [],
                    },
                    {
                        "name": "t2.reasoner.secondary",
                        "status": "hil-only",
                        "publisher": None,
                        "family": None,
                        "capacity_tpm": 0,
                        "invocation": "always",
                        "reasons": ["not available"],
                    },
                    {
                        "name": "narrator-fast",
                        "status": "resolved",
                        "family": "gpt-fast",
                    },
                    {
                        "name": "narrator-steady",
                        "status": "resolved",
                        "family": "gpt-steady",
                    },
                ],
                "narrator_candidates": [
                    {"deployment": "narrator-fast"},
                    {"deployment": "narrator-steady"},
                ],
                "endpoint_bindings": [
                    {
                        "binding_id": "t2-primary-prod",
                        "capability": "t2.reasoner.primary",
                        "provider_kind": "azure-openai",
                        "route_kind": "apim-gateway",
                        "api_style": "azure-openai",
                        "endpoint_ref": "model-gateway-primary",
                        "deployment": "t2-primary",
                        "api_version": "2024-10-21",
                        "auth": {
                            "kind": "entra",
                            "audience": "api://fdai-model-gateway",
                        },
                        "model": {
                            "publisher": "OpenAI",
                            "family": "gpt-4o",
                            "version": "2024-08-06",
                        },
                        "capacity": {"unit": "ptu", "value": 30},
                        "features": {
                            "streaming": True,
                            "embeddings": False,
                            "structured_output": True,
                            "tool_calling": True,
                        },
                        "discovery": {
                            "source": "apim-management",
                            "resource_ref_digest": "a" * 64,
                            "verified_at": "2026-07-17T00:00:00+00:00",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _registry(path: Path) -> Path:
    path.write_text(
        """schema_version: \"1.0.0\"
mixed_model_mode: azure-foundry
models:
    t2.reasoner.primary:
        preferences:
            - {publisher: OpenAI, family: gpt-4o}
            - {publisher: OpenAI, family: gpt-4.1}
        capacity_tpm: 20000
    t2.reasoner.secondary:
        preferences:
            - {publisher: Anthropic, family: claude-opus-4}
            - {publisher: MistralAI, family: mistral-large-2}
        capacity_tpm: 10000
""",
        encoding="utf-8",
    )
    return path


def _service(tmp_path: Path) -> ModelSettingsService:
    router = LatencyRoutedChatBackend(
        candidates=[("narrator-fast", _Backend()), ("narrator-steady", _Backend())]
    )
    return ModelSettingsService(
        resolved_models_path=_resolved(tmp_path / "resolved-models.json"),
        registry_path=_registry(tmp_path / "llm-registry.yaml"),
        store=InMemoryStateStore(),
        backend=router,
        web_search_resolver=_WebSearchResolver(),
        model_routing_status=_RoutingStatus(),
        model_catalog_reader=_CatalogReader(),
    )


def test_invalid_resolved_metadata_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "resolved-models.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ModelSettingsUnavailableError, match="unavailable"):
        ModelSettingsService(
            resolved_models_path=path,
            store=InMemoryStateStore(),
        )


async def test_projects_capabilities_provisioning_and_latency_candidates(tmp_path: Path) -> None:
    service = _service(tmp_path)

    projection = await service.projection("user-1")

    assert projection["region"] == "example-region"
    assert projection["resolved_metadata"]["kind"] == "generated-file"
    assert projection["resolved_metadata"]["source"] == "resolved-models.json"
    assert datetime.fromisoformat(projection["resolved_metadata"]["as_of"]).tzinfo is not None
    assert projection["discovery"]["automatic"] is True
    assert projection["provisioning"] == {
        "automatic": True,
        "status": "degraded",
        "resolved_count": 1,
        "hil_only_count": 1,
    }
    assert projection["narrator"]["requested"] == "auto"
    assert projection["narrator"]["revision"] == 0
    assert [item["deployment"] for item in projection["narrator"]["candidates"]] == [
        "narrator-fast",
        "narrator-steady",
    ]
    assert projection["t2_selection_scope"] == "system-governed"
    assert projection["t2_model_policy"] == {
        "selection_scope": "governance-draft",
        "invariant": "distinct-publisher",
        "primary_candidates": [
            {
                "publisher": "OpenAI",
                "family": "gpt-4o",
                "catalog_status": "registry-only",
                "version": None,
                "deployments": [],
                "available_tpm": 0,
            },
            {
                "publisher": "OpenAI",
                "family": "gpt-4.1",
                "catalog_status": "registry-only",
                "version": None,
                "deployments": [],
                "available_tpm": 0,
            },
            {
                "publisher": "OpenAI",
                "family": "gpt-5.4",
                "catalog_status": "deployed",
                "version": "2026-03-05",
                "deployments": ["gpt-5.4"],
                "available_tpm": 125_000,
            },
        ],
        "secondary_candidates": [
            {"publisher": "Anthropic", "family": "claude-opus-4"},
            {"publisher": "MistralAI", "family": "mistral-large-2"},
        ],
        "active_primary": None,
        "active_secondary": None,
        "quorum_ready": False,
    }
    assert projection["model_catalog"] == {
        "available": True,
        "source": "azure-control-plane",
        "region": "example-region",
        "models": [
            {
                "publisher": "OpenAI",
                "family": "gpt-5.4",
                "version": "2026-03-05",
                "lifecycle": "GenerallyAvailable",
                "skus": [{"name": "GlobalStandard", "available_tpm": 125_000}],
                "available_tpm": 125_000,
                "deployments": ["gpt-5.4"],
                "deployed": True,
                "provisionable": True,
                "selectable": True,
                "status": "deployed",
            },
            {
                "publisher": "OpenAI",
                "family": "gpt-5.4",
                "version": "2026-02-01",
                "lifecycle": "GenerallyAvailable",
                "skus": [{"name": "GlobalStandard", "available_tpm": 50000}],
                "available_tpm": 50000,
                "deployments": [],
                "deployed": False,
                "provisionable": True,
                "selectable": True,
                "status": "provisionable",
            },
        ],
    }
    assert projection["endpoint_inventory"] == [
        {
            "binding_id": "t2-primary-prod",
            "capability": "t2.reasoner.primary",
            "provider_kind": "azure-openai",
            "route_kind": "apim-gateway",
            "api_style": "azure-openai",
            "deployment": "t2-primary",
            "api_version": "2024-10-21",
            "auth_kind": "entra",
            "publisher": "OpenAI",
            "family": "gpt-4o",
            "version": "2024-08-06",
            "capacity_unit": "ptu",
            "capacity_value": 30,
            "features": {
                "streaming": True,
                "embeddings": False,
                "structured_output": True,
                "tool_calling": True,
            },
            "discovery_source": "apim-management",
            "verified_at": "2026-07-17T00:00:00+00:00",
            "managed_by": "catalog-and-resolver",
            "user_selectable": False,
        }
    ]
    assert "endpoint_ref" not in projection["endpoint_inventory"][0]
    assert "audience" not in projection["endpoint_inventory"][0]
    assert "resource_ref_digest" not in projection["endpoint_inventory"][0]
    assert projection["model_routing"] == [
        {
            "role": "t2.reasoner.primary",
            "selected_deployment": "primary-b",
            "selection_reason": "failover_after_1_candidate_failure",
            "selected_at": "2026-07-17T10:00:00+00:00",
            "candidates": [
                {
                    "deployment": "primary-a",
                    "status": "recovered",
                    "failure_kind": None,
                    "cooldown_seconds": 0,
                    "updated_at": "2026-07-17T10:00:00+00:00",
                },
                {
                    "deployment": "primary-b",
                    "status": "unhealthy",
                    "failure_kind": "rate_limit",
                    "cooldown_seconds": 60,
                    "updated_at": "2026-07-17T10:00:00+00:00",
                },
            ],
        }
    ]
    assert projection["web_search"] == {
        "available": True,
        "enabled": True,
        "allowed_domains": ["learn.microsoft.com"],
        "revision": 0,
        "can_manage": False,
        "provider": "azure-responses",
        "current_auto_pick": "narrator-fast",
        "candidates": [],
    }


async def test_unconfigured_web_search_is_unavailable_and_not_writable(tmp_path: Path) -> None:
    service = ModelSettingsService(
        resolved_models_path=_resolved(tmp_path / "resolved-models.json"),
        store=InMemoryStateStore(),
    )

    projection = await service.projection("user-1", can_manage_web_search=True)

    assert projection["web_search"] == {
        "available": False,
        "enabled": False,
        "allowed_domains": [],
        "revision": 0,
        "can_manage": False,
        "provider": "unavailable",
        "current_auto_pick": None,
        "candidates": [],
    }
    with pytest.raises(ModelSettingsUnavailableError, match="not configured"):
        await service.set_web_search_settings(
            actor_id="user-1",
            enabled=True,
            allowed_domains=("learn.microsoft.com",),
            expected_revision=0,
        )


async def test_persists_allowlisted_user_preference(tmp_path: Path) -> None:
    service = _service(tmp_path)

    await service.set_preference("user-1", "narrator-steady", expected_revision=0)

    assert await service.preferred_model("user-1") == "narrator-steady"
    projection = await service.projection("user-1")
    assert projection["narrator"]["effective"] == "narrator-steady"


async def test_rejects_unavailable_user_preference(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="available candidate"):
        await service.set_preference("user-1", "not-deployed", expected_revision=0)


def test_saved_preference_routes_the_authenticated_users_chat(tmp_path: Path) -> None:
    service = _service(tmp_path)

    async def authorize(request: Request) -> str:
        return request.headers.get("x-user", "anonymous")

    async def authorize_principal(request: Request) -> Principal:
        return Principal(
            oid=await authorize(request),
            roles=frozenset({Role.OWNER}),
        )

    application = Starlette(
        routes=[
            *make_model_settings_routes(
                service=service,
                authorize=authorize,
                authorize_principal=authorize_principal,
            ),
            make_chat_route(
                backend=service.backend,  # type: ignore[arg-type]
                authorize=authorize,
                model_preference_resolver=service.preferred_model,
            ),
        ]
    )
    client = TestClient(application)

    saved = client.put(
        "/me/model-preferences",
        headers={"x-user": "user-1"},
        json={"preferred_narrator_model": "narrator-steady", "expected_revision": 0},
    )
    reply = client.post(
        "/chat",
        headers={"x-user": "user-1"},
        json={"prompt": "Summarize the current view.", "view_context": {}},
    )

    assert saved.status_code == 200
    assert saved.json()["narrator"]["effective"] == "narrator-steady"
    assert reply.status_code == 200
    assert reply.json()["model"] == "narrator-steady"
    assert reply.json()["router"]["reason"] == "user-preferred"


def test_owner_updates_web_search_and_stale_revision_conflicts(tmp_path: Path) -> None:
    service = _service(tmp_path)

    async def authorize(request: Request) -> str:
        return request.headers.get("x-user", "owner-1")

    async def authorize_principal(request: Request) -> Principal:
        return Principal(oid=await authorize(request), roles=frozenset({Role.OWNER}))

    client = TestClient(
        Starlette(
            routes=make_model_settings_routes(
                service=service,
                authorize=authorize,
                authorize_principal=authorize_principal,
            )
        )
    )

    updated = client.put(
        "/models/web-search-settings",
        json={
            "enabled": False,
            "allowed_domains": [" NVD.NIST.GOV ", "nvd.nist.gov"],
            "expected_revision": 0,
        },
    )
    conflict = client.put(
        "/models/web-search-settings",
        json={
            "enabled": True,
            "allowed_domains": ["learn.microsoft.com"],
            "expected_revision": 0,
        },
    )

    assert updated.status_code == 200
    assert updated.json()["web_search"] == {
        "available": True,
        "enabled": False,
        "allowed_domains": ["nvd.nist.gov"],
        "revision": 1,
        "can_manage": True,
        "provider": "azure-responses",
        "current_auto_pick": "narrator-fast",
        "candidates": [],
    }
    assert service.web_search_resolver.enabled is False  # type: ignore[attr-defined]
    assert conflict.status_code == 409


def test_non_owner_cannot_update_web_search(tmp_path: Path) -> None:
    service = _service(tmp_path)

    async def authorize(_request: Request) -> str:
        return "reader-1"

    async def authorize_principal(_request: Request) -> Principal:
        return Principal(oid="reader-1", roles=frozenset({Role.READER}))

    client = TestClient(
        Starlette(
            routes=make_model_settings_routes(
                service=service,
                authorize=authorize,
                authorize_principal=authorize_principal,
            )
        )
    )
    response = client.put(
        "/models/web-search-settings",
        json={
            "enabled": True,
            "allowed_domains": ["learn.microsoft.com"],
            "expected_revision": 0,
        },
    )
    assert response.status_code == 403
