"""Sanitized LLM capability projection and principal-scoped narrator preference."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Capability, has_capability
from fdai.delivery.azure.llm.latency_routed_cross_check import ModelHealthTransition
from fdai.delivery.azure.llm.model_catalog import (
    GptModelCatalogReader,
    GptModelCatalogSnapshot,
    ModelCatalogUnavailableError,
)
from fdai.delivery.read_api.routes.chat import LatencyRoutedChatBackend
from fdai.rule_catalog.schema.llm_registry import (
    LlmRegistry,
    LlmRegistryError,
    load_llm_registry_from_yaml,
)
from fdai.shared.providers.state_store import StateStore

_PREFERENCE_PREFIX = "user-model-preference:"
_WEB_SEARCH_KEY = "model-settings:web-search"
_MAX_BODY_BYTES = 16_000
_DEFAULT_WEB_SEARCH_DOMAINS = (
    "learn.microsoft.com",
    "azure.microsoft.com",
    "nvd.nist.gov",
    "cve.org",
    "datatracker.ietf.org",
    "kubernetes.io",
    "docs.python.org",
    "postgresql.org",
)


class ModelRoutingStatusReader(Protocol):
    async def list_recent(self, *, limit: int = 200) -> Sequence[ModelHealthTransition]: ...


@dataclass(frozen=True, slots=True)
class ModelSettingsService:
    """Combine resolved capability state, runtime metrics, and user preference."""

    resolved_models_path: Path
    store: StateStore
    backend: object | None = None
    web_search_resolver: object | None = None
    automatic_discovery: bool = True
    automatic_provisioning: bool = True
    model_routing_status: ModelRoutingStatusReader | None = None
    registry_path: Path | None = None
    model_catalog_reader: GptModelCatalogReader | None = None

    def __post_init__(self) -> None:
        self._load_resolved()
        self._load_registry()

    async def preferred_model(self, principal_id: str) -> str | None:
        record = await self.store.read_state(_preference_key(principal_id))
        requested = record.get("preferred_narrator_model") if record else None
        if not isinstance(requested, str) or requested == "auto":
            return None
        return requested if requested in self._candidate_names() else None

    async def set_preference(
        self,
        principal_id: str,
        requested: str,
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        normalized = requested.strip()
        if normalized != "auto" and normalized not in self._candidate_names():
            raise ValueError("preferred narrator model MUST be auto or an available candidate")
        record = {
            "principal_id": principal_id,
            "preferred_narrator_model": normalized,
            "revision": expected_revision + 1,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
        updated = await self.store.compare_and_set_state_with_audit(
            _preference_key(principal_id),
            record,
            expected_revision=expected_revision,
            audit_entry={
                "event_id": str(uuid4()),
                "correlation_id": f"model-preference:{principal_id}",
                "actor": principal_id,
                "action_kind": "model.narrator-preference-updated",
                "mode": "enforce",
                "decision": "saved",
                "idempotency_key": f"model-preference:{principal_id}:{expected_revision + 1}",
                "timestamp": record["updated_at"],
            },
        )
        if not updated:
            raise ModelSettingsConflictError("narrator preference revision mismatch")
        return record

    async def projection(
        self,
        principal_id: str,
        *,
        can_manage_web_search: bool = False,
        refresh_model_catalog: bool = False,
    ) -> dict[str, Any]:
        resolved = self._load_resolved()
        capabilities = [
            _capability_view(item)
            for item in resolved.get("capabilities", [])
            if isinstance(item, dict) and str(item.get("name") or "").startswith(("t1.", "t2."))
        ]
        requested_record = await self.store.read_state(_preference_key(principal_id))
        requested = requested_record.get("preferred_narrator_model") if requested_record else "auto"
        if not isinstance(requested, str):
            requested = "auto"
        preference_revision = _record_revision(requested_record)
        candidates = self._candidate_views(resolved)
        candidate_names = {item["deployment"] for item in candidates}
        effective = requested if requested in candidate_names else "auto"
        fallback_reason = (
            "preferred deployment is no longer available; automatic routing is active"
            if requested != "auto" and effective == "auto"
            else None
        )
        resolved_count = sum(
            item["status"] in {"resolved", "capacity-reduced"} for item in capabilities
        )
        hil_only_count = sum(item["status"] == "hil-only" for item in capabilities)
        web_search = await self._web_search_projection(can_manage=can_manage_web_search)
        model_routing = await self._model_routing_projection()
        model_catalog = await self._model_catalog_projection(force_refresh=refresh_model_catalog)
        endpoint_inventory = [
            _endpoint_binding_view(item)
            for item in resolved.get("endpoint_bindings", [])
            if isinstance(item, dict)
        ]
        return {
            "region": resolved.get("region"),
            "mixed_model_mode": resolved.get("mixed_model_mode"),
            "resolved_metadata": {
                "kind": "generated-file",
                "source": self.resolved_models_path.name,
                "as_of": datetime.fromtimestamp(
                    self.resolved_models_path.stat().st_mtime,
                    tz=UTC,
                ).isoformat(),
            },
            "discovery": {
                "automatic": self.automatic_discovery,
                "source": "rule-catalog/llm-registry.yaml",
                "status": "enabled" if self.automatic_discovery else "disabled",
            },
            "provisioning": {
                "automatic": self.automatic_provisioning,
                "status": "degraded" if hil_only_count else "ready",
                "resolved_count": resolved_count,
                "hil_only_count": hil_only_count,
            },
            "capabilities": capabilities,
            "endpoint_inventory": endpoint_inventory,
            "narrator": {
                "selection_scope": "per-user",
                "revision": preference_revision,
                "requested": requested,
                "effective": effective,
                "fallback_reason": fallback_reason,
                "current_auto_pick": (
                    self.backend.current_pick_name()
                    if isinstance(self.backend, LatencyRoutedChatBackend)
                    else None
                ),
                "candidates": candidates,
            },
            "web_search": web_search,
            "model_routing": model_routing,
            "t2_selection_scope": "system-governed",
            "t2_model_policy": self._t2_model_policy_projection(resolved, model_catalog),
            "model_catalog": model_catalog,
        }

    def _t2_model_policy_projection(
        self,
        resolved: dict[str, Any],
        model_catalog: dict[str, Any],
    ) -> dict[str, Any]:
        registry = self._load_registry()
        primary = _resolved_capability(resolved, "t2.reasoner.primary")
        secondary = _resolved_capability(resolved, "t2.reasoner.secondary")
        primary_publisher = _optional_string(primary.get("publisher"))
        secondary_publisher = _optional_string(secondary.get("publisher"))
        return {
            "selection_scope": "governance-draft",
            "invariant": "distinct-publisher",
            "primary_candidates": _primary_candidates(
                registry,
                model_catalog,
            ),
            "secondary_candidates": _registry_candidates(registry, "t2.reasoner.secondary"),
            "active_primary": _resolved_model_choice(primary),
            "active_secondary": _resolved_model_choice(secondary),
            "quorum_ready": (
                primary.get("status") in {"resolved", "capacity-reduced"}
                and secondary.get("status") in {"resolved", "capacity-reduced"}
                and primary_publisher is not None
                and secondary_publisher is not None
                and primary_publisher != secondary_publisher
            ),
        }

    async def _model_catalog_projection(self, *, force_refresh: bool = False) -> dict[str, Any]:
        if self.model_catalog_reader is None:
            return _unavailable_model_catalog()
        try:
            snapshot = await self.model_catalog_reader.snapshot(force_refresh=force_refresh)
        except ModelCatalogUnavailableError:
            return _unavailable_model_catalog()
        return _model_catalog_view(snapshot)

    async def _model_routing_projection(self) -> list[dict[str, Any]]:
        if self.model_routing_status is None:
            return []
        transitions = await self.model_routing_status.list_recent(limit=200)
        roles: dict[str, dict[str, Any]] = {}
        for transition in transitions:
            role = roles.setdefault(
                transition.model_role,
                {
                    "role": transition.model_role,
                    "selected_deployment": None,
                    "selection_reason": None,
                    "selected_at": None,
                    "candidates": {},
                },
            )
            if transition.status == "selected" and role["selected_deployment"] is None:
                role["selected_deployment"] = transition.deployment
                role["selection_reason"] = transition.reason
                role["selected_at"] = transition.recorded_at.isoformat()
            candidates: dict[str, dict[str, Any]] = role["candidates"]
            if (
                transition.status in {"unhealthy", "recovered"}
                and transition.deployment not in candidates
            ):
                candidates[transition.deployment] = {
                    "deployment": transition.deployment,
                    "status": transition.status,
                    "failure_kind": (
                        transition.failure_kind.value
                        if transition.failure_kind is not None
                        else None
                    ),
                    "cooldown_seconds": transition.cooldown_seconds,
                    "updated_at": transition.recorded_at.isoformat(),
                }
        return [
            {
                **{key: value for key, value in role.items() if key != "candidates"},
                "candidates": sorted(
                    role["candidates"].values(),
                    key=lambda candidate: candidate["deployment"],
                ),
            }
            for role in sorted(roles.values(), key=lambda item: item["role"])
        ]

    async def set_web_search_settings(
        self,
        *,
        actor_id: str,
        enabled: bool,
        allowed_domains: tuple[str, ...],
        expected_revision: int,
    ) -> None:
        if self.web_search_resolver is None:
            raise ModelSettingsUnavailableError("web-search resolver is not configured")
        normalized = _normalize_domains(allowed_domains)
        if enabled and not normalized:
            raise ValueError("allowed_domains MUST contain at least one host when enabled")
        record = {
            "enabled": enabled,
            "allowed_domains": list(normalized),
            "revision": expected_revision + 1,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
        updated = await self.store.compare_and_set_state_with_audit(
            _WEB_SEARCH_KEY,
            record,
            expected_revision=expected_revision,
            audit_entry={
                "event_id": str(uuid4()),
                "correlation_id": _WEB_SEARCH_KEY,
                "actor": actor_id,
                "action_kind": "model.web-search-settings-updated",
                "mode": "enforce",
                "decision": "saved",
                "idempotency_key": f"{_WEB_SEARCH_KEY}:{expected_revision + 1}",
                "timestamp": record["updated_at"],
            },
        )
        if not updated:
            raise ModelSettingsConflictError("web-search revision mismatch")
        self._apply_web_search(record)

    def _candidate_names(self) -> tuple[str, ...]:
        if isinstance(self.backend, LatencyRoutedChatBackend):
            return self.backend.candidate_names()
        resolved = self._load_resolved()
        return tuple(
            str(item["deployment"])
            for item in resolved.get("narrator_candidates", [])
            if isinstance(item, dict) and isinstance(item.get("deployment"), str)
        )

    def _candidate_views(self, resolved: dict[str, Any]) -> list[dict[str, Any]]:
        router_stats = (
            self.backend.stats() if isinstance(self.backend, LatencyRoutedChatBackend) else []
        )
        stats = {item["deployment"]: item for item in router_stats}
        families = {
            item.get("name"): item.get("family")
            for item in resolved.get("capabilities", [])
            if isinstance(item, dict)
        }
        return [
            {
                "deployment": name,
                "family": families.get(name),
                "status": "available",
                "total_p50_ms": stats.get(name, {}).get("p50_ms"),
                "total_p95_ms": stats.get(name, {}).get("p95_ms"),
                "total_samples": stats.get(name, {}).get("samples", 0),
                "ttft_p50_ms": stats.get(name, {}).get("ttft_p50_ms"),
                "ttft_p95_ms": stats.get(name, {}).get("ttft_p95_ms"),
                "ttft_samples": stats.get(name, {}).get("ttft_samples", 0),
            }
            for name in self._candidate_names()
        ]

    def _load_resolved(self) -> dict[str, Any]:
        try:
            value = json.loads(self.resolved_models_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ModelSettingsUnavailableError("resolved model metadata is unavailable") from exc
        if not isinstance(value, dict):
            raise ModelSettingsUnavailableError("resolved model metadata is invalid")
        return value

    def _load_registry(self) -> LlmRegistry | None:
        if self.registry_path is None:
            return None
        try:
            return load_llm_registry_from_yaml(self.registry_path)
        except (OSError, LlmRegistryError) as exc:
            raise ModelSettingsUnavailableError("LLM registry metadata is unavailable") from exc

    async def _web_search_projection(self, *, can_manage: bool) -> dict[str, Any]:
        if self.web_search_resolver is None:
            return {
                "available": False,
                "enabled": False,
                "allowed_domains": [],
                "revision": 0,
                "can_manage": False,
                "provider": "unavailable",
                "current_auto_pick": None,
                "candidates": [],
            }
        record = await self._web_search_record()
        self._apply_web_search(record)
        descriptor_fn = getattr(self.web_search_resolver, "descriptor", None)
        descriptor = descriptor_fn() if descriptor_fn is not None else {}
        router = descriptor.get("router") if isinstance(descriptor, Mapping) else None
        return {
            "available": True,
            "enabled": bool(record["enabled"]),
            "allowed_domains": list(record["allowed_domains"]),
            "revision": int(record["revision"]),
            "can_manage": can_manage,
            "provider": "azure-responses",
            "current_auto_pick": (router.get("chose") if isinstance(router, Mapping) else None),
            "candidates": (
                list(router.get("candidates", [])) if isinstance(router, Mapping) else []
            ),
        }

    async def _web_search_record(self) -> dict[str, Any]:
        stored = await self.store.read_state(_WEB_SEARCH_KEY)
        if stored is None:
            descriptor_fn = getattr(self.web_search_resolver, "descriptor", None)
            descriptor = descriptor_fn() if descriptor_fn is not None else {}
            raw_domains = (
                descriptor.get("allowed_domains") if isinstance(descriptor, Mapping) else None
            )
            domains = (
                _normalize_domains(tuple(str(item) for item in raw_domains))
                if isinstance(raw_domains, list) and raw_domains
                else _DEFAULT_WEB_SEARCH_DOMAINS
            )
            enabled = (
                bool(descriptor.get("enabled", True)) if isinstance(descriptor, Mapping) else True
            )
            return {"enabled": enabled, "allowed_domains": list(domains), "revision": 0}
        stored_enabled = stored.get("enabled")
        stored_domains = stored.get("allowed_domains")
        stored_revision = stored.get("revision")
        if (
            not isinstance(stored_enabled, bool)
            or not isinstance(stored_domains, list)
            or not isinstance(stored_revision, int)
            or isinstance(stored_revision, bool)
            or stored_revision < 1
        ):
            raise RuntimeError("stored web-search settings are invalid")
        normalized = _normalize_domains(tuple(str(item) for item in stored_domains))
        if stored_enabled and not normalized:
            raise RuntimeError("stored enabled web-search settings have no domains")
        return {
            "enabled": stored_enabled,
            "allowed_domains": list(normalized),
            "revision": stored_revision,
        }

    def _apply_web_search(self, record: Mapping[str, Any]) -> None:
        update = getattr(self.web_search_resolver, "update_settings", None)
        if update is None:
            return
        update(
            enabled=bool(record["enabled"]),
            allowed_domains=tuple(str(item) for item in record["allowed_domains"]),
        )


class ModelSettingsConflictError(ValueError):
    """A deployment-wide settings write used a stale revision."""


class ModelSettingsUnavailableError(RuntimeError):
    """Resolved model metadata cannot produce a valid Settings projection."""


def make_model_settings_routes(
    *,
    service: ModelSettingsService,
    authorize: Any,
    authorize_principal: Callable[[Request], Awaitable[Principal]],
) -> tuple[Route, ...]:
    async def get_settings(request: Request) -> Response:
        principal = await authorize_principal(request)
        try:
            projection = await service.projection(
                principal.oid,
                can_manage_web_search=has_capability(
                    principal.roles,
                    Capability.MANAGE_GROUP_MEMBERSHIP,
                ),
                refresh_model_catalog=request.query_params.get("refresh_catalog") == "1",
            )
        except ModelSettingsUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return JSONResponse(projection)

    async def put_preference(request: Request) -> Response:
        principal_id = await authorize(request)
        body = await _read_json_body(request)
        requested = body.get("preferred_narrator_model")
        expected_revision = body.get("expected_revision")
        if not isinstance(requested, str):
            raise HTTPException(
                status_code=400,
                detail="preferred_narrator_model MUST be a string",
            )
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise HTTPException(status_code=400, detail="expected_revision MUST be >= 0")
        try:
            await service.set_preference(
                principal_id,
                requested,
                expected_revision=expected_revision,
            )
        except ModelSettingsConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ModelSettingsUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(await service.projection(principal_id))

    async def put_web_search(request: Request) -> Response:
        principal = await authorize_principal(request)
        if not has_capability(principal.roles, Capability.MANAGE_GROUP_MEMBERSHIP):
            raise HTTPException(status_code=403, detail="Owner role is required")
        body = await _read_json_body(request)
        enabled = body.get("enabled")
        domains = body.get("allowed_domains")
        expected_revision = body.get("expected_revision")
        if not isinstance(enabled, bool):
            raise HTTPException(status_code=400, detail="enabled MUST be a boolean")
        if not isinstance(domains, list) or not all(isinstance(item, str) for item in domains):
            raise HTTPException(status_code=400, detail="allowed_domains MUST be a string array")
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise HTTPException(status_code=400, detail="expected_revision MUST be >= 0")
        try:
            await service.set_web_search_settings(
                actor_id=principal.oid,
                enabled=enabled,
                allowed_domains=tuple(domains),
                expected_revision=expected_revision,
            )
        except ModelSettingsConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ModelSettingsUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(await service.projection(principal.oid, can_manage_web_search=True))

    return (
        Route("/models/settings", get_settings, methods=["GET"]),
        Route("/models/web-search-settings", put_web_search, methods=["PUT"]),
        Route("/me/model-preferences", put_preference, methods=["PUT"]),
    )


async def _read_json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request body too large")
    try:
        value = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="request body MUST be JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="request body MUST be an object")
    return value


def _record_revision(record: Mapping[str, Any] | None) -> int:
    if record is None or "revision" not in record:
        return 0
    revision = record.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise RuntimeError("stored narrator preference revision is invalid")
    return revision


def _normalize_domains(domains: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(item.strip().casefold().rstrip(".") for item in domains if item.strip())
    )
    if len(normalized) > 100:
        raise ValueError("allowed_domains MUST contain at most 100 hosts")
    invalid = [
        domain
        for domain in normalized
        if (
            "://" in domain
            or "/" in domain
            or ":" in domain
            or "*" in domain
            or not _valid_domain(domain)
        )
    ]
    if invalid:
        raise ValueError(
            "allowed_domains MUST contain hosts without schemes, paths, ports, or wildcards"
        )
    return normalized


def _valid_domain(domain: str) -> bool:
    if len(domain) > 253 or "." not in domain:
        return False
    return all(
        bool(label)
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in domain.split(".")
    )


def _capability_view(item: dict[str, Any]) -> dict[str, Any]:
    capacity = item.get("capacity") if isinstance(item.get("capacity"), dict) else None
    return {
        "name": item.get("name"),
        "tier": str(item.get("name") or "").split(".", 1)[0].upper(),
        "publisher": item.get("publisher"),
        "family": item.get("family"),
        "status": item.get("status"),
        "capacity_tpm": item.get("capacity_tpm"),
        "capacity_unit": capacity.get("unit") if capacity is not None else "tpm",
        "capacity_value": (
            capacity.get("value") if capacity is not None else item.get("capacity_tpm")
        ),
        "invocation": item.get("invocation"),
        "reasons": item.get("reasons") if isinstance(item.get("reasons"), list) else [],
        "user_selectable": False,
    }


def _endpoint_binding_view(item: dict[str, Any]) -> dict[str, Any]:
    auth = _mapping_value(item, "auth")
    model = _mapping_value(item, "model")
    capacity = _mapping_value(item, "capacity")
    features = _mapping_value(item, "features")
    discovery = _mapping_value(item, "discovery")
    return {
        "binding_id": item.get("binding_id"),
        "capability": item.get("capability"),
        "provider_kind": item.get("provider_kind"),
        "route_kind": item.get("route_kind"),
        "api_style": item.get("api_style"),
        "deployment": item.get("deployment"),
        "api_version": item.get("api_version"),
        "auth_kind": auth.get("kind"),
        "publisher": model.get("publisher"),
        "family": model.get("family"),
        "version": model.get("version"),
        "capacity_unit": capacity.get("unit"),
        "capacity_value": capacity.get("value"),
        "features": {
            "streaming": bool(features.get("streaming", False)),
            "embeddings": bool(features.get("embeddings", False)),
            "structured_output": bool(features.get("structured_output", False)),
            "tool_calling": bool(features.get("tool_calling", False)),
        },
        "discovery_source": discovery.get("source"),
        "verified_at": discovery.get("verified_at"),
        "managed_by": "catalog-and-resolver",
        "user_selectable": False,
    }


def _resolved_capability(resolved: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    capabilities = resolved.get("capabilities")
    if not isinstance(capabilities, list):
        return {}
    return next(
        (item for item in capabilities if isinstance(item, Mapping) and item.get("name") == name),
        {},
    )


def _resolved_model_choice(capability: Mapping[str, Any]) -> dict[str, str] | None:
    publisher = _optional_string(capability.get("publisher"))
    family = _optional_string(capability.get("family"))
    if publisher is None or family is None:
        return None
    return {"publisher": publisher, "family": family}


def _registry_candidates(registry: LlmRegistry | None, role: str) -> list[dict[str, str]]:
    if registry is None or role not in registry.models:
        return []
    return [
        {"publisher": preference.publisher, "family": preference.family}
        for preference in registry.models[role].preferences
    ]


def _primary_candidates(
    registry: LlmRegistry | None,
    model_catalog: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {
        preference["family"]: {
            **preference,
            "catalog_status": "registry-only",
            "version": None,
            "deployments": [],
            "available_tpm": 0,
        }
        for preference in _registry_candidates(registry, "t2.reasoner.primary")
    }
    raw_models = model_catalog.get("models")
    if isinstance(raw_models, list):
        for model in raw_models:
            if not isinstance(model, dict):
                continue
            family = model.get("family")
            if not isinstance(family, str):
                continue
            if not model.get("selectable") and family not in candidates:
                continue
            existing = candidates.get(family)
            if existing is not None and existing.get("catalog_status") != "registry-only":
                continue
            candidates[family] = {
                "publisher": "OpenAI",
                "family": family,
                "catalog_status": model.get("status"),
                "version": model.get("version"),
                "deployments": model.get("deployments", []),
                "available_tpm": model.get("available_tpm", 0),
            }
    return list(candidates.values())


def _model_catalog_view(snapshot: GptModelCatalogSnapshot) -> dict[str, Any]:
    return {
        "available": True,
        "source": "azure-control-plane",
        "region": snapshot.region,
        "models": [
            {
                "publisher": "OpenAI",
                "family": model.family,
                "version": model.version,
                "lifecycle": model.lifecycle,
                "skus": [
                    {"name": sku.name, "available_tpm": sku.available_tpm} for sku in model.skus
                ],
                "available_tpm": max(
                    (sku.available_tpm for sku in model.skus),
                    default=0,
                ),
                "deployments": list(model.deployments),
                "deployed": model.deployed,
                "provisionable": model.provisionable,
                "selectable": model.selectable,
                "status": (
                    "deployed"
                    if model.deployed
                    else "provisionable"
                    if model.provisionable
                    else "quota-unavailable"
                ),
            }
            for model in snapshot.models
        ],
    }


def _unavailable_model_catalog() -> dict[str, Any]:
    return {
        "available": False,
        "source": "unavailable",
        "region": None,
        "models": [],
    }


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _mapping_value(item: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = item.get(key)
    return value if isinstance(value, Mapping) else {}


def _preference_key(principal_id: str) -> str:
    return f"{_PREFERENCE_PREFIX}{principal_id}"


__all__ = ["ModelSettingsService", "make_model_settings_routes"]
