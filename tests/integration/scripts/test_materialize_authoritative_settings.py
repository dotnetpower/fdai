from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/deployment/local/materialize-authoritative-settings.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("materialize_authoritative_settings", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_projection_is_sanitized_and_uses_only_resolved_facts() -> None:
    module = _module()
    raw = {
        "subscription_id": "00000000-0000-0000-0000-000000000001",
        "deployer_object_id": "00000000-0000-0000-0000-000000000002",
        "region": "example-region",
        "mixed_model_mode": "azure-foundry",
        "capabilities": [
            {
                "name": "t1.embedding",
                "publisher": "OpenAI",
                "family": "text-embedding-example",
                "status": "resolved",
                "capacity_tpm": 100,
                "invocation": "always",
                "reasons": [],
            },
            {
                "name": "t2.reasoner.primary",
                "publisher": "OpenAI",
                "family": "reasoner-example",
                "status": "hil-only",
                "capacity_tpm": 0,
                "invocation": "always",
                "reasons": ["quota-unavailable"],
            },
            {
                "name": "narrator-example",
                "publisher": "OpenAI",
                "family": "narrator-family",
                "status": "resolved",
                "capacity_tpm": 100,
                "invocation": "always",
                "reasons": [],
            },
        ],
        "narrator": {
            "deployment": "narrator-example",
            "endpoint": "https://private-resource.example.invalid/",
        },
        "narrator_candidates": [
            {
                "deployment": "narrator-example",
                "api_version": "example",
                "endpoint": "https://private-resource.example.invalid/",
            }
        ],
        "web_search_candidates": [],
    }

    projection = module.model_settings_projection(
        raw,
        observed_at=datetime(2026, 8, 10, tzinfo=UTC),
        web_search_enabled=True,
        allowed_domains=("learn.microsoft.com",),
    )

    serialized = json.dumps(projection, sort_keys=True)
    assert "private-resource" not in serialized
    assert "00000000-0000-0000-0000-000000000001" not in serialized
    assert projection["provisioning"] == {
        "automatic": False,
        "status": "ready",
        "resolved_count": 1,
        "hil_only_count": 1,
    }
    assert [item["name"] for item in projection["capabilities"]] == [
        "t1.embedding",
        "t2.reasoner.primary",
    ]
    assert projection["narrator"]["effective"] == "narrator-example"
    assert projection["web_search"]["enabled"] is False
    assert projection["model_catalog"]["available"] is False


def test_runtime_projection_reports_configuration_without_inventing_readiness() -> None:
    module = _module()

    projection = module.runtime_settings_projection(
        {
            "RUNTIME_ENV": "dev",
            "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/fdai",
            "KAFKA_BOOTSTRAP_SERVERS": "example.invalid:9093",
            "FDAI_AZURE_READER_SUBSCRIPTION_ID": "configured-at-runtime",
            "FDAI_LLM_ENDPOINT": "https://example.invalid/",
            "FDAI_CHATOPS_WEBHOOK_SECRET": "configured-outside-source-control",
            "FDAI_START_PANTHEON": "1",
            "AUTONOMY_MODE_DEFAULT": "shadow",
        }
    )

    assert projection["runtime"]["state_store_durable"] is True
    assert projection["runtime"]["pantheon_enabled"] is True
    integrations = {item["key"]: item for item in projection["integrations"]}
    assert integrations["chatops"]["configured"] is True
    assert integrations["chatops"]["ready"] is False
    assert integrations["email"]["configured"] is False
