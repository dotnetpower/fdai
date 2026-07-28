from __future__ import annotations

from typing import Any

import pytest

from fdai.delivery.runtime_settings import (
    RuntimeSettingsConflictError,
    RuntimeSettingsService,
    RuntimeSettingsUnavailableError,
    runtime_settings_service_from_env,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def test_projection_merges_environment_and_override() -> None:
    store = InMemoryStateStore()
    service = RuntimeSettingsService(
        store=store,
        env={"FDAI_IRP_ENABLED": "1", "FDAI_LOG_LEVEL": "WARNING"},
    )

    initial = await service.projection(can_manage=True)
    await service.update(
        actor_id="owner-1",
        changes={"irp.budget_seconds": 90, "logging.level": "DEBUG"},
        expected_revision=0,
    )
    updated = await service.projection(can_manage=True)

    assert initial["revision"] == 0
    assert _setting(initial, "irp.enabled")["effective_value"] is True
    assert _setting(updated, "irp.budget_seconds")["effective_value"] == 90.0
    assert _setting(updated, "logging.level")["environment_value"] == "WARNING"
    assert _setting(updated, "logging.level")["override_value"] == "DEBUG"
    assert updated["updated_by"] == "owner-1"
    assert len(tuple(store.audit_entries)) == 1


async def test_null_change_restores_environment_value() -> None:
    service = RuntimeSettingsService(
        store=InMemoryStateStore(),
        env={"FDAI_LOG_LEVEL": "ERROR"},
    )
    await service.update(
        actor_id="owner-1",
        changes={"logging.level": "DEBUG"},
        expected_revision=0,
    )

    await service.update(
        actor_id="owner-1",
        changes={"logging.level": None},
        expected_revision=1,
    )

    restored = await service.projection(can_manage=True)
    assert _setting(restored, "logging.level")["override_value"] is None
    assert _setting(restored, "logging.level")["effective_value"] == "ERROR"


async def test_rejects_stale_revision_unknown_key_and_unsafe_retention() -> None:
    service = RuntimeSettingsService(store=InMemoryStateStore(), env={})
    await service.update(
        actor_id="owner-1",
        changes={"inventory.freshness_seconds": 120},
        expected_revision=0,
    )

    with pytest.raises(RuntimeSettingsConflictError, match="revision mismatch"):
        await service.update(
            actor_id="owner-2",
            changes={"inventory.freshness_seconds": 180},
            expected_revision=0,
        )
    with pytest.raises(ValueError, match="unknown runtime setting"):
        await service.update(actor_id="owner-1", changes={"secret": "value"}, expected_revision=1)
    with pytest.raises(ValueError, match="deletion_days MUST be >="):
        await service.update(
            actor_id="owner-1",
            changes={"case_history.retention_days": 90},
            expected_revision=1,
        )
    with pytest.raises(ValueError, match="MUST NOT be empty"):
        await service.update(actor_id="owner-1", changes={}, expected_revision=1)


async def test_invalid_environment_fails_closed() -> None:
    service = RuntimeSettingsService(
        store=InMemoryStateStore(),
        env={"FDAI_IRP_ENABLED": "sometimes"},
    )

    with pytest.raises(RuntimeSettingsUnavailableError, match="environment"):
        await service.projection(can_manage=False)


async def test_in_memory_store_is_not_reported_as_durable() -> None:
    service = RuntimeSettingsService(store=InMemoryStateStore(), env={})

    projection = await service.projection(can_manage=False)

    assert projection["runtime"]["state_store_durable"] is False


async def test_environment_only_runtime_reader_uses_no_persistent_override() -> None:
    service = runtime_settings_service_from_env(
        {"FDAI_IRP_ENABLED": "true", "FDAI_ANALYZER_BUDGET_SECONDS": "12.5"}
    )

    effective = await service.effective_values()

    assert effective["irp.enabled"] is True
    assert effective["analyzer.budget_seconds"] == 12.5
    with pytest.raises(RuntimeSettingsUnavailableError, match="durable"):
        await service.update(
            actor_id="owner-1",
            changes={"irp.enabled": False},
            expected_revision=0,
        )


async def test_incident_auto_open_settings_are_bounded_and_startup_bound() -> None:
    service = RuntimeSettingsService(store=InMemoryStateStore(), env={})

    projection = await service.projection(can_manage=True)

    expected = {
        "incident.auto_open.enabled": True,
        "incident.auto_open.min_severity": "HIGH",
        "incident.repeat_threshold": 5,
        "incident.repeat_window_seconds": 300,
    }
    for key, value in expected.items():
        setting = _setting(projection, key)
        assert setting["effective_value"] == value
        assert setting["restart_required"] is True


async def test_incident_auto_open_settings_accept_audited_override() -> None:
    service = RuntimeSettingsService(store=InMemoryStateStore(), env={})

    await service.update(
        actor_id="owner-1",
        changes={
            "incident.auto_open.enabled": False,
            "incident.auto_open.min_severity": "CRITICAL",
            "incident.repeat_threshold": 9,
            "incident.repeat_window_seconds": 600,
        },
        expected_revision=0,
    )

    effective = await service.effective_values()
    assert effective["incident.auto_open.enabled"] is False
    assert effective["incident.auto_open.min_severity"] == "CRITICAL"
    assert effective["incident.repeat_threshold"] == 9
    assert effective["incident.repeat_window_seconds"] == 600


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"FDAI_INCIDENT_AUTO_OPEN_MIN_SEVERITY": "urgent"}, "min_severity"),
        ({"FDAI_INCIDENT_REPEAT_THRESHOLD": "1"}, "REPEAT_THRESHOLD"),
        ({"FDAI_INCIDENT_REPEAT_WINDOW_SECONDS": "0"}, "REPEAT_WINDOW_SECONDS"),
    ],
)
async def test_invalid_incident_auto_open_environment_fails_closed(
    env: dict[str, str], message: str
) -> None:
    service = RuntimeSettingsService(store=InMemoryStateStore(), env=env)

    with pytest.raises(RuntimeSettingsUnavailableError, match="environment") as exc:
        await service.effective_values()

    assert message in str(exc.value.__cause__)


async def test_projection_sanitizes_integration_and_runtime_status() -> None:
    service = RuntimeSettingsService(
        store=InMemoryStateStore(),
        env={
            "RUNTIME_ENV": "prod",
            "AUTONOMY_MODE_DEFAULT": "shadow",
            "FDAI_WORKFLOW_SHADOW": "1",
            "FDAI_CHATOPS_WEBHOOK_URL": "configured",
            "FDAI_EMAIL_ENDPOINT": "configured",
            "FDAI_EMAIL_SENDER_ADDRESS": "configured",
            "FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON": '["ops@example.com"]',
            "FDAI_NOTIFICATION_MI_CLIENT_ID": "configured",
            "FDAI_JIRA_BASE_URL": "configured",
            "FDAI_JIRA_ENFORCE": "1",
        },
        durable=True,
    )

    projection = await service.projection(can_manage=False)
    integrations = {item["key"]: item for item in projection["integrations"]}

    assert integrations["chatops"] == {
        "key": "chatops",
        "configured": True,
        "ready": True,
        "mode": "enabled",
        "reason": None,
    }
    assert integrations["email"]["ready"] is True
    assert integrations["jira"]["configured"] is True
    assert integrations["jira"]["ready"] is False
    assert integrations["jira"]["mode"] == "disabled"
    assert projection["runtime"] == {
        "environment": "prod",
        "state_store_durable": True,
        "autonomy_default": "shadow",
        "pantheon_enabled": True,
        "workflow_observation_enabled": True,
        "primary_transport_configured": False,
        "auxiliary_transport_configured": False,
        "case_history_configured": False,
    }
    assert "FDAI_EMAIL_ENDPOINT" not in str(projection)


async def test_malformed_integration_json_is_not_ready() -> None:
    service = RuntimeSettingsService(
        store=InMemoryStateStore(),
        env={
            "FDAI_EMAIL_ENDPOINT": "configured",
            "FDAI_EMAIL_SENDER_ADDRESS": "configured",
            "FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON": "not-json",
            "FDAI_NOTIFICATION_MI_CLIENT_ID": "configured",
            "FDAI_JIRA_BASE_URL": "configured",
            "FDAI_JIRA_ACCOUNT_EMAIL": "configured",
            "FDAI_JIRA_API_TOKEN_SECRET": "configured",
            "FDAI_JIRA_TOOL_MAP_JSON": "[]",
            "FDAI_STATE_STORE_DSN": "configured",
        },
    )

    integrations = {
        item["key"]: item for item in (await service.projection(can_manage=False))["integrations"]
    }

    assert integrations["email"]["reason"] == "configuration is invalid"
    assert integrations["email"]["ready"] is False
    assert integrations["jira"]["reason"] == "configuration is invalid"
    assert integrations["jira"]["ready"] is False


def _setting(projection: dict[str, Any], key: str) -> dict[str, Any]:
    return next(item for item in projection["settings"] if item["key"] == key)
