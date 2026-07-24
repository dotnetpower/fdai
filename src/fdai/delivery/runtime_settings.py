"""Durable, allowlisted runtime policy settings."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from fdai.shared.providers.state_store import StateStore

_STATE_KEY = "runtime-settings:policy"


class RuntimeSettingsConflictError(ValueError):
    """A runtime settings update used a stale revision."""


class RuntimeSettingsUnavailableError(RuntimeError):
    """Runtime settings cannot produce a valid effective policy."""


@dataclass(frozen=True, slots=True)
class RuntimeSettingSpec:
    """Validation and presentation metadata for one public setting."""

    key: str
    env_name: str
    group: str
    value_type: Literal["boolean", "integer", "number", "enum"]
    default: object
    minimum: float | None = None
    maximum: float | None = None
    options: tuple[str, ...] = ()
    restart_required: bool = False

    def validate(self, value: object) -> object:
        if self.value_type == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"{self.key} MUST be a boolean")
            return value
        if self.value_type == "enum":
            if not isinstance(value, str) or value not in self.options:
                choices = ", ".join(self.options)
                raise ValueError(f"{self.key} MUST be one of {choices}")
            return value
        if self.value_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{self.key} MUST be an integer")
            self._validate_bounds(float(value))
            return value
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{self.key} MUST be a number")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{self.key} MUST be finite")
        self._validate_bounds(number)
        return number

    def _validate_bounds(self, value: float) -> None:
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"{self.key} MUST be >= {self.minimum:g}")
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"{self.key} MUST be <= {self.maximum:g}")


RUNTIME_SETTING_SPECS: tuple[RuntimeSettingSpec, ...] = (
    RuntimeSettingSpec("irp.enabled", "FDAI_IRP_ENABLED", "investigation", "boolean", False),
    RuntimeSettingSpec(
        "irp.budget_seconds",
        "FDAI_IRP_BUDGET_SECONDS",
        "investigation",
        "number",
        60.0,
        1,
        900,
    ),
    RuntimeSettingSpec(
        "inventory.freshness_seconds",
        "FDAI_INVENTORY_FRESHNESS_SECONDS",
        "inventory",
        "integer",
        86_400,
        60,
        604_800,
    ),
    RuntimeSettingSpec(
        "analyzer.window_seconds",
        "FDAI_ANALYZER_WINDOW_SECONDS",
        "analysis",
        "number",
        300.0,
        60,
        86_400,
    ),
    RuntimeSettingSpec(
        "analyzer.budget_seconds",
        "FDAI_ANALYZER_BUDGET_SECONDS",
        "analysis",
        "number",
        60.0,
        1,
        3_600,
    ),
    RuntimeSettingSpec(
        "case_history.retention_days",
        "FDAI_CASE_HISTORY_RETENTION_DAYS",
        "retention",
        "integer",
        30,
        1,
        3_650,
        restart_required=True,
    ),
    RuntimeSettingSpec(
        "case_history.deletion_days",
        "FDAI_CASE_HISTORY_DELETION_DAYS",
        "retention",
        "integer",
        60,
        1,
        3_650,
        restart_required=True,
    ),
    RuntimeSettingSpec(
        "case_history.retention_tick_seconds",
        "FDAI_CASE_HISTORY_RETENTION_TICK_SECONDS",
        "retention",
        "integer",
        86_400,
        60,
        604_800,
    ),
    RuntimeSettingSpec(
        "logging.level",
        "FDAI_LOG_LEVEL",
        "diagnostics",
        "enum",
        "INFO",
        options=("DEBUG", "INFO", "WARNING", "ERROR"),
        restart_required=True,
    ),
)

_SPECS_BY_KEY = {spec.key: spec for spec in RUNTIME_SETTING_SPECS}


@dataclass(frozen=True, slots=True)
class RuntimeSettingsService:
    """Merge environment defaults with audited durable overrides."""

    store: StateStore | None
    env: Mapping[str, str]
    durable: bool = False

    async def effective_values(self) -> dict[str, object]:
        record = await self._record()
        return self._effective_values(dict(record["overrides"]))

    async def projection(self, *, can_manage: bool) -> dict[str, Any]:
        record = await self._record()
        overrides = dict(record["overrides"])
        environment = self._environment_values()
        effective = self._effective_values(overrides, environment=environment)
        return {
            "revision": record["revision"],
            "can_manage": can_manage,
            "updated_at": record.get("updated_at"),
            "updated_by": record.get("updated_by"),
            "integrations": self._integration_projection(),
            "runtime": self._runtime_projection(),
            "settings": [
                {
                    "key": spec.key,
                    "group": spec.group,
                    "value_type": spec.value_type,
                    "environment_value": environment[spec.key],
                    "override_value": overrides.get(spec.key),
                    "effective_value": effective[spec.key],
                    "minimum": spec.minimum,
                    "maximum": spec.maximum,
                    "options": list(spec.options),
                    "restart_required": spec.restart_required,
                    "available": True,
                    "unavailable_reason": None,
                }
                for spec in RUNTIME_SETTING_SPECS
            ],
        }

    def _integration_projection(self) -> list[dict[str, object]]:
        email = self._required_configuration(
            "email",
            (
                "FDAI_EMAIL_ENDPOINT",
                "FDAI_EMAIL_SENDER_ADDRESS",
                "FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON",
                "FDAI_NOTIFICATION_MI_CLIENT_ID",
            ),
        )
        if email["ready"] and not _valid_json_string_array(
            self.env.get("FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON", "")
        ):
            email = _invalid_configuration("email")
        gitops = self._required_configuration(
            "gitops",
            ("FDAI_GITOPS_TOKEN", "FDAI_GITOPS_OWNER", "FDAI_GITOPS_REPO"),
        )
        jira = self._required_configuration(
            "jira",
            (
                "FDAI_JIRA_BASE_URL",
                "FDAI_JIRA_ACCOUNT_EMAIL",
                "FDAI_JIRA_API_TOKEN_SECRET",
                "FDAI_JIRA_TOOL_MAP_JSON",
                "FDAI_STATE_STORE_DSN",
            ),
            mode="enforce" if self.env.get("FDAI_JIRA_ENFORCE", "").strip() == "1" else "shadow",
        )
        if jira["ready"] and not _valid_json_string_map(
            self.env.get("FDAI_JIRA_TOOL_MAP_JSON", "")
        ):
            jira = _invalid_configuration("jira")
        chatops_keys = (
            "FDAI_CHATOPS_WEBHOOK_URL",
            "FDAI_CHATOPS_WEBHOOK_SECRET",
            "FDAI_CHATOPS_APPROVE_CALLBACK_URL",
            "FDAI_CHATOPS_REJECT_CALLBACK_URL",
        )
        chatops_values = tuple(bool(self.env.get(key, "").strip()) for key in chatops_keys)
        callback_values = chatops_values[1:]
        chatops_configured = any(chatops_values)
        chatops_ready = chatops_values[0] and (not any(callback_values) or all(callback_values))
        chatops = {
            "key": "chatops",
            "configured": chatops_configured,
            "ready": chatops_ready,
            "mode": "enabled" if chatops_ready else "disabled",
            "reason": (
                None
                if chatops_ready
                else "configuration is incomplete"
                if chatops_configured
                else "not configured"
            ),
        }
        return [chatops, email, gitops, jira]

    def _runtime_projection(self) -> dict[str, object]:
        runtime_env = self.env.get("RUNTIME_ENV", "").strip().lower()
        environment = runtime_env if runtime_env in {"dev", "staging", "prod"} else "unspecified"
        autonomy_default = self.env.get("AUTONOMY_MODE_DEFAULT", "shadow").strip().lower()
        autonomy_status = autonomy_default if autonomy_default == "shadow" else "invalid"
        false_values = {"0", "false", "no", "off"}
        workflow_values = {"1", "true", "yes", "on"}
        return {
            "environment": environment,
            "state_store_durable": self.durable,
            "autonomy_default": autonomy_status,
            "pantheon_enabled": (
                self.env.get("FDAI_START_PANTHEON", "").strip().casefold() not in false_values
            ),
            "workflow_observation_enabled": (
                self.env.get("FDAI_WORKFLOW_SHADOW", "").strip().casefold() in workflow_values
            ),
            "primary_transport_configured": bool(
                self.env.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
            ),
            "auxiliary_transport_configured": bool(
                self.env.get("FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS", "").strip()
            ),
            "case_history_configured": all(
                self.env.get(key, "").strip()
                for key in (
                    "FDAI_CASE_HISTORY_CONTAINER_URL",
                    "FDAI_CASE_HISTORY_MI_CLIENT_ID",
                )
            ),
        }

    def _required_configuration(
        self,
        key: str,
        required: tuple[str, ...],
        *,
        mode: str = "enabled",
    ) -> dict[str, object]:
        present = tuple(bool(self.env.get(name, "").strip()) for name in required)
        configured = any(present)
        ready = all(present)
        return {
            "key": key,
            "configured": configured,
            "ready": ready,
            "mode": mode if ready else "disabled",
            "reason": (
                None if ready else "configuration is incomplete" if configured else "not configured"
            ),
        }

    async def update(
        self,
        *,
        actor_id: str,
        changes: Mapping[str, object],
        expected_revision: int,
    ) -> None:
        if self.store is None:
            raise RuntimeSettingsUnavailableError("durable runtime settings are unavailable")
        if not changes:
            raise ValueError("runtime settings changes MUST NOT be empty")
        current = await self._record()
        overrides = dict(current["overrides"])
        for key, value in changes.items():
            spec = _SPECS_BY_KEY.get(key)
            if spec is None:
                raise ValueError(f"unknown runtime setting: {key}")
            if value is None:
                overrides.pop(key, None)
            else:
                overrides[key] = spec.validate(value)
        self._effective_values(overrides)
        updated_at = datetime.now(tz=UTC).isoformat()
        record = {
            "revision": expected_revision + 1,
            "overrides": overrides,
            "updated_at": updated_at,
            "updated_by": actor_id,
        }
        updated = await self.store.compare_and_set_state_with_audit(
            _STATE_KEY,
            record,
            expected_revision=expected_revision,
            audit_entry={
                "event_id": str(uuid4()),
                "correlation_id": _STATE_KEY,
                "actor": actor_id,
                "action_kind": "runtime.settings-updated",
                "mode": "enforce",
                "decision": "saved",
                "idempotency_key": f"{_STATE_KEY}:{expected_revision + 1}",
                "timestamp": updated_at,
                "changed_keys": sorted(changes),
            },
        )
        if not updated:
            raise RuntimeSettingsConflictError("runtime settings revision mismatch")

    async def _record(self) -> dict[str, Any]:
        if self.store is None:
            return {"revision": 0, "overrides": {}}
        stored = await self.store.read_state(_STATE_KEY)
        if stored is None:
            return {"revision": 0, "overrides": {}}
        revision = stored.get("revision")
        overrides = stored.get("overrides")
        if (
            not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 1
            or not isinstance(overrides, Mapping)
        ):
            raise RuntimeSettingsUnavailableError("stored runtime settings are invalid")
        validated: dict[str, object] = {}
        try:
            for key, value in overrides.items():
                if not isinstance(key, str) or key not in _SPECS_BY_KEY:
                    raise ValueError("stored runtime settings contain an unknown key")
                validated[key] = _SPECS_BY_KEY[key].validate(value)
            self._effective_values(validated)
        except ValueError as exc:
            raise RuntimeSettingsUnavailableError("stored runtime settings are invalid") from exc
        return {
            "revision": revision,
            "overrides": validated,
            "updated_at": _optional_stored_string(stored, "updated_at"),
            "updated_by": _optional_stored_string(stored, "updated_by"),
        }

    def _environment_values(self) -> dict[str, object]:
        try:
            return {spec.key: self._environment_value(spec) for spec in RUNTIME_SETTING_SPECS}
        except ValueError as exc:
            raise RuntimeSettingsUnavailableError(
                "runtime environment settings are invalid"
            ) from exc

    def _environment_value(self, spec: RuntimeSettingSpec) -> object:
        raw = self.env.get(spec.env_name, "").strip()
        if not raw:
            return spec.default
        if spec.value_type == "boolean":
            normalized = raw.casefold()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
            raise ValueError(f"{spec.env_name} MUST be a boolean")
        if spec.value_type == "integer":
            try:
                return spec.validate(int(raw))
            except ValueError as exc:
                raise ValueError(f"{spec.env_name} MUST be an integer") from exc
        if spec.value_type == "number":
            try:
                return spec.validate(float(raw))
            except ValueError as exc:
                raise ValueError(f"{spec.env_name} MUST be a number") from exc
        return spec.validate(raw.upper())

    def _effective_values(
        self,
        overrides: Mapping[str, object],
        *,
        environment: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        effective = dict(environment or self._environment_values())
        effective.update(overrides)
        retention = effective["case_history.retention_days"]
        deletion = effective["case_history.deletion_days"]
        if not isinstance(retention, int) or not isinstance(deletion, int) or deletion < retention:
            raise ValueError("case_history.deletion_days MUST be >= case_history.retention_days")
        return effective


def runtime_settings_service_from_env(
    env: Mapping[str, str],
) -> RuntimeSettingsService:
    """Build a read-through settings service for a runtime or scheduled job."""
    dsn = env.get("FDAI_STATE_STORE_DSN", "").strip()
    store: StateStore | None = None
    if dsn:
        from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

        store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    return RuntimeSettingsService(store=store, env=env, durable=store is not None)


def _optional_stored_string(record: Mapping[str, Any], key: str) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise RuntimeSettingsUnavailableError("stored runtime settings are invalid")
    return value


def _valid_json_string_array(raw: str) -> bool:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item) for item in value)
    )


def _valid_json_string_map(raw: str) -> bool:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(value, dict)
        and bool(value)
        and all(
            isinstance(key, str) and bool(key) and isinstance(item, str) and bool(item)
            for key, item in value.items()
        )
    )


def _invalid_configuration(key: str) -> dict[str, object]:
    return {
        "key": key,
        "configured": True,
        "ready": False,
        "mode": "disabled",
        "reason": "configuration is invalid",
    }


__all__ = [
    "RUNTIME_SETTING_SPECS",
    "RuntimeSettingSpec",
    "RuntimeSettingsConflictError",
    "RuntimeSettingsService",
    "RuntimeSettingsUnavailableError",
    "runtime_settings_service_from_env",
]
