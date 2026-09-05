#!/usr/bin/env python3
"""Materialize sanitized local Settings projections from prepared authoritative inputs."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai.delivery.integration_readiness import integration_projection
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.runtime_settings import RUNTIME_SETTING_SPECS, RuntimeSettingsService

MODEL_SETTINGS_KEY = "operator-projection:iam:model-settings"
RUNTIME_SETTINGS_KEY = "operator-projection:iam:runtime-settings"


def model_settings_projection(
    raw: Mapping[str, Any],
    *,
    observed_at: datetime,
    web_search_enabled: bool,
    allowed_domains: Sequence[str],
    active_digest: str | None = None,
    environment: str = "unspecified",
    document_ocr_provider: str = "local_python",
    document_ocr_endpoint_configured: bool = False,
) -> dict[str, object]:
    """Build a sanitized model projection without identifiers, endpoints, or credentials."""
    if environment not in {"dev", "staging", "prod"}:
        environment = "unspecified"
    if document_ocr_provider not in {
        "local_python",
        "azure_document_intelligence",
    }:
        raise ValueError("document OCR provider is invalid")
    if document_ocr_provider == "azure_document_intelligence" and not (
        document_ocr_endpoint_configured
    ):
        raise ValueError("Azure document OCR requires a configured endpoint")
    raw_capabilities = _mapping_sequence(raw.get("capabilities"))
    capabilities = [
        _capability(item)
        for item in raw_capabilities
        if str(item.get("name", "")).startswith(("t1.", "t2."))
    ]
    deployment_metadata = {
        str(item.get("name")): item for item in raw_capabilities if item.get("name")
    }
    narrator = _mapping(raw.get("narrator"))
    narrator_deployment = _optional_string(narrator.get("deployment"))
    narrator_candidates = [
        _narrator_candidate(item, deployment_metadata)
        for item in _mapping_sequence(raw.get("narrator_candidates"))
        if _optional_string(item.get("deployment")) is not None
    ]
    web_candidates = [
        {
            "deployment": deployment,
            "api_version": _optional_string(item.get("api_version")),
        }
        for item in _mapping_sequence(raw.get("web_search_candidates"))
        if (deployment := _optional_string(item.get("deployment"))) is not None
    ]
    web_deployment = str(web_candidates[0]["deployment"]) if web_candidates else None
    resolved_count = sum(item["status"] == "resolved" for item in capabilities)
    hil_only_count = sum(item["status"] == "hil-only" for item in capabilities)
    t2_choices = _t2_choices(capabilities)
    active_primary = _active_t2_choice(capabilities, "t2.reasoner.primary")
    active_secondary = _active_t2_choice(capabilities, "t2.reasoner.secondary")
    publishers = {
        str(item["publisher"]) for item in t2_choices if item["catalog_status"] == "deployed"
    }
    return {
        "environment": environment,
        "region": _optional_string(raw.get("region")),
        "mixed_model_mode": _optional_string(raw.get("mixed_model_mode")),
        "resolved_metadata": {
            "kind": "resolved-models",
            "source": "prepared-resolved-model-artifact",
            "as_of": observed_at.astimezone(UTC).isoformat(),
            "digest": active_digest,
        },
        "discovery": {
            "automatic": True,
            "source": "azure-model-resolver",
            "status": "enabled",
        },
        "provisioning": {
            "automatic": False,
            "status": "ready" if resolved_count else "degraded",
            "resolved_count": resolved_count,
            "hil_only_count": hil_only_count,
        },
        "capabilities": capabilities,
        "endpoint_inventory": [],
        "narrator": {
            "revision": 0,
            "requested": narrator_deployment or "auto",
            "effective": narrator_deployment or "unavailable",
            "fallback_reason": None,
            "selection_scope": "per-user",
            "current_auto_pick": narrator_deployment,
            "candidates": narrator_candidates,
        },
        "web_search": {
            "available": bool(web_candidates),
            "enabled": web_search_enabled and bool(web_candidates),
            "unavailable_reason": None if web_candidates else "not_configured",
            "allowed_domains": list(dict.fromkeys(allowed_domains)),
            "revision": 0,
            "can_manage": False,
            "provider": "azure-openai",
            "project_configured": bool(web_candidates),
            "agent_name": None,
            "model_deployment": web_deployment,
            "provisioning_status": "configured" if web_candidates else "not-configured",
            "readiness_status": "unavailable",
            "current_auto_pick": web_deployment,
            "candidates": web_candidates,
        },
        "document_ocr": {
            "available": True,
            "effective_provider": document_ocr_provider,
            "local_python_available": True,
            "azure_available": document_ocr_endpoint_configured,
            "azure_resource_state": ("ready" if document_ocr_endpoint_configured else "absent"),
            "korean_enabled": True,
            "can_manage": False,
            "execution_authority": False,
        },
        "model_routing": [],
        "t2_selection_scope": "system-governed",
        "t2_model_policy": {
            "selection_scope": "governance-draft",
            "invariant": "distinct-publisher",
            "primary_candidates": t2_choices,
            "secondary_candidates": t2_choices,
            "active_primary": active_primary,
            "active_secondary": active_secondary,
            "quorum_ready": len(publishers) >= 2,
        },
        "model_catalog": {
            "available": False,
            "source": "live-catalog-not-queried",
            "region": _optional_string(raw.get("region")),
            "models": [],
        },
    }


def runtime_settings_projection(environ: Mapping[str, str]) -> dict[str, object]:
    """Build read-only runtime diagnostics from the validated prepared environment."""
    runtime_settings = RuntimeSettingsService(store=None, env=environ)
    environment_values = runtime_settings.environment_values()
    conversation_settings = [
        {
            "key": spec.key,
            "group": spec.group,
            "value_type": spec.value_type,
            "environment_value": environment_values[spec.key],
            "override_value": None,
            "effective_value": environment_values[spec.key],
            "minimum": spec.minimum,
            "maximum": spec.maximum,
            "options": list(spec.options),
            "restart_required": spec.restart_required,
            "available": True,
            "unavailable_reason": None,
        }
        for spec in RUNTIME_SETTING_SPECS
        if spec.group == "conversation"
    ]
    state_store = bool(environ.get("FDAI_STATE_STORE_DSN", "").strip())
    primary_transport = bool(
        environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
        or environ.get("FDAI_KAFKA_BOOTSTRAP_SERVERS", "").strip()
    )
    # Reuse the one shared readiness implementation so the local projection can
    # never drift from the deployed one, and so notification bindings are
    # represented locally instead of being silently dropped.
    integrations = integration_projection(environ)
    runtime_environment = environ.get("RUNTIME_ENV", "").strip().lower()
    if runtime_environment not in {"dev", "staging", "prod"}:
        runtime_environment = "unspecified"
    return {
        "revision": 0,
        "can_manage": False,
        "updated_at": None,
        "updated_by": None,
        "settings": conversation_settings,
        "integrations": integrations,
        "runtime": {
            "environment": runtime_environment,
            "state_store_durable": state_store,
            "autonomy_default": environ.get("AUTONOMY_MODE_DEFAULT", "shadow") or "shadow",
            "pantheon_enabled": _enabled(environ.get("FDAI_START_PANTHEON"), default=True),
            "workflow_observation_enabled": _enabled(
                environ.get("FDAI_WORKFLOW_SHADOW"), default=True
            ),
            "primary_transport_configured": primary_transport,
            "auxiliary_transport_configured": False,
            "case_history_configured": all(
                environ.get(key, "").strip()
                for key in (
                    "FDAI_CASE_HISTORY_CONTAINER_URL",
                    "FDAI_CASE_HISTORY_MI_CLIENT_ID",
                )
            ),
        },
    }


def _capability(item: Mapping[str, Any]) -> dict[str, object]:
    name = str(item.get("name") or "")
    capacity_record = _mapping(item.get("capacity"))
    capacity_unit = str(capacity_record.get("unit") or "tpm")
    if capacity_unit not in {"tpm", "ptu"}:
        capacity_unit = "tpm"
    capacity = _non_negative_number(
        capacity_record.get("value") if capacity_unit == "ptu" else item.get("capacity_tpm")
    )
    return {
        "name": name,
        "tier": "T1" if name.startswith("t1.") else "T2",
        "publisher": _optional_string(item.get("publisher")),
        "family": _optional_string(item.get("family")),
        "status": str(item.get("status") or "hil-only"),
        "version": _optional_string(item.get("version")),
        "sku": _optional_string(item.get("sku")),
        "selection_mode": str(item.get("selection_mode") or "auto"),
        "capacity_tpm": capacity if capacity_unit == "tpm" else 0,
        "capacity_unit": capacity_unit,
        "capacity_value": capacity,
        "invocation": str(item.get("invocation") or "unknown"),
        "reasons": [str(value) for value in item.get("reasons", ()) if isinstance(value, str)],
    }


def _narrator_candidate(
    item: Mapping[str, Any], metadata: Mapping[str, Mapping[str, Any]]
) -> dict[str, object]:
    deployment = str(item["deployment"])
    details = metadata.get(deployment, {})
    return {
        "deployment": deployment,
        "family": _optional_string(details.get("family")),
        "status": "available",
        "total_p50_ms": None,
        "total_p95_ms": None,
        "total_samples": 0,
        "ttft_p50_ms": None,
        "ttft_p95_ms": None,
        "ttft_samples": 0,
    }


def _t2_choices(capabilities: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    choices: dict[tuple[str, str], dict[str, object]] = {}
    for item in capabilities:
        if item["tier"] != "T2" or item["publisher"] is None or item["family"] is None:
            continue
        key = (str(item["publisher"]), str(item["family"]))
        status = "deployed" if item["status"] == "resolved" else "quota-unavailable"
        choices[key] = {
            "publisher": key[0],
            "family": key[1],
            "version": item.get("version"),
            "catalog_status": status,
            "deployments": [],
            "available_tpm": item["capacity_tpm"],
            "capacity_unit": item["capacity_unit"],
            "capacity_value": item["capacity_value"],
        }
    return [choices[key] for key in sorted(choices)]


def _active_t2_choice(
    capabilities: Sequence[Mapping[str, object]], capability_name: str
) -> dict[str, object] | None:
    item = next((entry for entry in capabilities if entry["name"] == capability_name), None)
    if item is None or item["status"] not in {"resolved", "capacity-reduced"}:
        return None
    choices = _t2_choices((item,))
    return choices[0] if choices else None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_sequence(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _non_negative_number(value: object) -> int | float:
    return (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _enabled(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _canonical_json_digest(value: Mapping[str, object]) -> str:
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


async def materialize(*, model_only: bool = False) -> None:
    """Write sanitized Settings projections without exposing deployment values."""
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    artifact_value = os.environ.get("LLM_RESOLVED_MODELS_PATH", "").strip()
    if not dsn:
        raise RuntimeError("FDAI_STATE_STORE_DSN MUST be configured")
    if not artifact_value:
        raise RuntimeError("LLM_RESOLVED_MODELS_PATH MUST be configured")
    artifact = Path(artifact_value).expanduser().resolve()
    raw = json.loads(artifact.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise RuntimeError("resolved model artifact MUST be a JSON object")
    observed_at = datetime.fromtimestamp(artifact.stat().st_mtime, tz=UTC)
    active_digest = _canonical_json_digest(raw)
    domains = tuple(
        value.strip()
        for value in os.environ.get("FDAI_WEB_SEARCH_ALLOWED_DOMAINS", "").split(",")
        if value.strip()
    )
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    await store.write_state(
        MODEL_SETTINGS_KEY,
        model_settings_projection(
            raw,
            observed_at=observed_at,
            web_search_enabled=_enabled(os.environ.get("FDAI_WEB_SEARCH_ENABLED"), default=False),
            allowed_domains=domains,
            active_digest=active_digest,
            environment=os.environ.get("RUNTIME_ENV", "").strip().lower(),
            document_ocr_provider=os.environ.get(
                "FDAI_DOCUMENT_OCR_PROVIDER", "local_python"
            ).strip(),
            document_ocr_endpoint_configured=bool(os.environ.get("FDAI_OCR_ENDPOINT", "").strip()),
        ),
    )
    if not model_only:
        await store.write_state(RUNTIME_SETTINGS_KEY, runtime_settings_projection(os.environ))


def main(argv: Sequence[str] | None = None) -> int:
    """Materialize selected Settings projections without printing deployment values."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-only", action="store_true")
    args = parser.parse_args(argv)
    asyncio.run(materialize(model_only=args.model_only))
    scope = "model" if args.model_only else "model and runtime"
    print(f"authoritative local {scope} settings projections refreshed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
