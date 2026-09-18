from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

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
                "name": "t2.reasoner.secondary",
                "publisher": "Anthropic",
                "family": "reasoner-secondary-example",
                "version": "2026-01-01",
                "sku": "GlobalProvisionedManaged",
                "status": "resolved",
                "capacity_tpm": 0,
                "capacity": {"unit": "ptu", "value": 30},
                "selection_mode": "pinned",
                "invocation": "always",
                "reasons": [],
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
        active_digest="sha256:" + "a" * 64,
        environment="dev",
    )

    serialized = json.dumps(projection, sort_keys=True)
    assert "private-resource" not in serialized
    assert "00000000-0000-0000-0000-000000000001" not in serialized
    assert projection["provisioning"] == {
        "automatic": False,
        "status": "ready",
        "resolved_count": 2,
        "hil_only_count": 1,
    }
    assert [item["name"] for item in projection["capabilities"]] == [
        "t1.embedding",
        "t2.reasoner.primary",
        "t2.reasoner.secondary",
    ]
    secondary = projection["capabilities"][2]
    assert secondary["capacity_unit"] == "ptu"
    assert secondary["capacity_value"] == 30
    assert secondary["capacity_tpm"] == 0
    assert secondary["version"] == "2026-01-01"
    assert secondary["selection_mode"] == "pinned"
    assert projection["narrator"]["effective"] == "narrator-example"
    assert projection["web_search"]["enabled"] is False
    assert projection["model_catalog"]["available"] is False
    assert projection["resolved_metadata"]["digest"] == "sha256:" + "a" * 64
    assert projection["environment"] == "dev"
    assert projection["document_ocr"]["effective_provider"] == "local_python"
    assert projection["document_ocr"]["azure_resource_state"] == "absent"
    assert projection["t2_model_policy"]["active_primary"] is None
    assert projection["t2_model_policy"]["active_secondary"]["capacity_unit"] == "ptu"


def test_model_projection_requires_an_endpoint_for_azure_document_ocr() -> None:
    module = _module()

    with pytest.raises(ValueError, match="requires a configured endpoint"):
        module.model_settings_projection(
            {},
            observed_at=datetime(2026, 8, 10, tzinfo=UTC),
            web_search_enabled=False,
            allowed_domains=(),
            document_ocr_provider="azure_document_intelligence",
            document_ocr_endpoint_configured=False,
        )


def test_active_digest_is_independent_of_json_whitespace() -> None:
    module = _module()
    payload = {"schema_version": "1.0.0", "capabilities": [{"name": "t1.example"}]}
    pretty = json.loads(json.dumps(payload, indent=2))
    compact = json.loads(json.dumps(payload, separators=(",", ":")))

    assert module._canonical_json_digest(pretty) == module._canonical_json_digest(compact)


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
            "FDAI_CASE_HISTORY_CONTAINER_URL": "https://example.invalid/cases",
            "FDAI_CASE_HISTORY_MI_CLIENT_ID": "case-history-reader",
        }
    )

    assert projection["runtime"]["state_store_durable"] is True
    assert projection["runtime"]["pantheon_enabled"] is True
    assert projection["runtime"]["workflow_observation_enabled"] is True
    assert projection["runtime"]["case_history_configured"] is True
    integrations = {item["key"]: item for item in projection["integrations"]}
    # The local projection reuses the one shared readiness implementation, so it
    # reports the same source-attributed rows the deployed control plane reports.
    assert integrations["teams-a1-approval-callback"]["configured"] is True
    assert integrations["teams-a1-approval-callback"]["ready"] is False
    assert integrations["teams-a1-approval-callback"]["source"] == "operator-service"
    assert integrations["teams-a1-approval-send"]["configured"] is False
    assert integrations["teams-a2-operational-alert"]["ready"] is False
    assert integrations["notification-bindings"]["configured"] is False
    assert integrations["email"]["configured"] is False
    assert "chatops" not in integrations
    settings = {item["key"]: item for item in projection["settings"]}
    assert set(settings) == {spec.key for spec in module.RUNTIME_SETTING_SPECS}
    assert settings["conversation.answer_continuity.enabled"]["effective_value"] is False
    assert settings["conversation.answer_continuity.enabled"]["restart_required"] is True
    assert settings["conversation.t2_escalation.aggressive_enabled"]["restart_required"] is False
    assert settings["conversation.prompt_ablation.profile"]["effective_value"] == "NONE"
    assert settings["conversation.prompt_ablation.profile"]["restart_required"] is True
    assert settings["incident.auto_open.enabled"]["effective_value"] is True
    assert settings["incident.auto_open.enabled"]["restart_required"] is True
    assert settings["incident.auto_open.min_severity"]["effective_value"] == "HIGH"
    assert settings["incident.repeat_threshold"]["effective_value"] == 5
    assert settings["incident.repeat_window_seconds"]["effective_value"] == 300


def test_runtime_projection_honors_disabled_workflow_observation() -> None:
    module = _module()

    projection = module.runtime_settings_projection({"FDAI_WORKFLOW_SHADOW": "false"})

    assert projection["runtime"]["workflow_observation_enabled"] is False
    assert projection["runtime"]["case_history_configured"] is False


@pytest.mark.parametrize(
    ("model_only", "seed_runtime_if_missing", "expected_writes", "expected_seeds"),
    [
        (True, False, ("operator-projection:iam:model-settings",), ()),
        (
            False,
            False,
            (
                "operator-projection:iam:model-settings",
                "operator-projection:iam:runtime-settings",
            ),
            (),
        ),
        (
            False,
            True,
            ("operator-projection:iam:model-settings",),
            ("operator-projection:iam:runtime-settings",),
        ),
    ],
)
def test_materialize_can_preserve_runtime_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    model_only: bool,
    seed_runtime_if_missing: bool,
    expected_writes: tuple[str, ...],
    expected_seeds: tuple[str, ...],
) -> None:
    module = _module()
    artifact = tmp_path / "resolved-models.json"
    artifact.write_text(
        json.dumps(
            {
                "capabilities": [],
                "narrator_candidates": [],
                "web_search_candidates": [],
            }
        ),
        encoding="utf-8",
    )
    writes: list[str] = []
    seeds: list[str] = []

    class Store:
        def __init__(self, *, config: object) -> None:
            del config

        async def write_state(self, key: str, value: object) -> None:
            del value
            writes.append(key)

        async def write_state_if_absent(self, key: str, value: object) -> bool:
            del value
            seeds.append(key)
            return True

    monkeypatch.setattr(module, "PostgresStateStore", Store)
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example.invalid/fdai")
    monkeypatch.setenv("LLM_RESOLVED_MODELS_PATH", str(artifact))
    monkeypatch.setenv("RUNTIME_ENV", "dev")

    asyncio.run(
        module.materialize(
            model_only=model_only,
            seed_runtime_if_missing=seed_runtime_if_missing,
        )
    )

    assert tuple(writes) == expected_writes
    assert tuple(seeds) == expected_seeds


def test_materialize_rejects_conflicting_runtime_modes() -> None:
    module = _module()

    with pytest.raises(
        ValueError,
        match="model_only and seed_runtime_if_missing are mutually exclusive",
    ):
        asyncio.run(module.materialize(model_only=True, seed_runtime_if_missing=True))


def test_materialize_writes_no_models_resolved_snapshot_without_an_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No LLM_RESOLVED_MODELS_PATH (for example, no Azure OpenAI account resolved yet)
    MUST still materialize Settings instead of failing preparation."""
    module = _module()
    writes: dict[str, object] = {}

    class Store:
        def __init__(self, *, config: object) -> None:
            del config

        async def write_state(self, key: str, value: object) -> None:
            writes[key] = value

    monkeypatch.setattr(module, "PostgresStateStore", Store)
    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "postgresql://example.invalid/fdai")
    monkeypatch.delenv("LLM_RESOLVED_MODELS_PATH", raising=False)
    monkeypatch.setenv("RUNTIME_ENV", "dev")

    asyncio.run(module.materialize(model_only=True))

    model_settings = writes["operator-projection:iam:model-settings"]
    assert isinstance(model_settings, dict)
    assert model_settings["capabilities"] == []
    assert model_settings["resolved_metadata"]["digest"] is None
    assert model_settings["narrator"]["effective"] == "unavailable"


def test_materialize_requires_state_store_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)

    with pytest.raises(RuntimeError, match="FDAI_STATE_STORE_DSN MUST be configured"):
        asyncio.run(module.materialize(model_only=True))
