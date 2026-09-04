"""Durable, allowlisted runtime policy settings."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import psycopg

from fdai.delivery.integration_readiness import integration_projection
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
    development_default: object | None = None

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
    RuntimeSettingSpec(
        "human_access.enabled",
        "FDAI_HUMAN_ACCESS_ENABLED",
        "identity",
        "boolean",
        True,
        restart_required=True,
    ),
    RuntimeSettingSpec(
        "human_access.reconciliation_interval_seconds",
        "FDAI_HUMAN_ACCESS_RECONCILIATION_INTERVAL_SECONDS",
        "identity",
        "integer",
        300,
        30,
        3_600,
        restart_required=True,
    ),
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
        "discovery.enabled",
        "FDAI_DISCOVERY_ENABLED",
        "discovery",
        "boolean",
        False,
    ),
    RuntimeSettingSpec(
        "discovery.shadow_decision_threshold",
        "FDAI_DISCOVERY_SHADOW_DECISION_THRESHOLD",
        "discovery",
        "integer",
        1_000,
        1,
        1_000_000,
    ),
    RuntimeSettingSpec(
        "discovery.collector_freshness_seconds",
        "FDAI_DISCOVERY_COLLECTOR_FRESHNESS_SECONDS",
        "discovery",
        "integer",
        691_200,
        60,
        2_678_400,
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
        "incident.auto_open.enabled",
        "FDAI_INCIDENT_AUTO_OPEN_ENABLED",
        "incident",
        "boolean",
        True,
        restart_required=True,
    ),
    RuntimeSettingSpec(
        "incident.auto_open.min_severity",
        "FDAI_INCIDENT_AUTO_OPEN_MIN_SEVERITY",
        "incident",
        "enum",
        "HIGH",
        options=("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"),
        restart_required=True,
    ),
    RuntimeSettingSpec(
        "incident.repeat_threshold",
        "FDAI_INCIDENT_REPEAT_THRESHOLD",
        "incident",
        "integer",
        5,
        2,
        100,
        restart_required=True,
    ),
    RuntimeSettingSpec(
        "incident.repeat_window_seconds",
        "FDAI_INCIDENT_REPEAT_WINDOW_SECONDS",
        "incident",
        "integer",
        300,
        10,
        86_400,
        restart_required=True,
    ),
    RuntimeSettingSpec(
        "incident.security_high_threshold",
        "FDAI_INCIDENT_SECURITY_HIGH_THRESHOLD",
        "incident",
        "integer",
        5,
        1,
        100,
        restart_required=True,
    ),
    RuntimeSettingSpec(
        "incident.security_window_events",
        "FDAI_INCIDENT_SECURITY_WINDOW_EVENTS",
        "incident",
        "integer",
        100,
        1,
        10_000,
        restart_required=True,
    ),
    RuntimeSettingSpec(
        "incident.alert_rate_per_hour",
        "FDAI_INCIDENT_ALERT_RATE_PER_HOUR",
        "incident",
        "integer",
        5,
        1,
        1_000,
        restart_required=True,
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
    RuntimeSettingSpec(
        "conversation.answer_continuity.enabled",
        "FDAI_ANSWER_CONTINUITY_ENABLED",
        "conversation",
        "boolean",
        False,
        restart_required=True,
    ),
    RuntimeSettingSpec(
        "conversation.t2_escalation.aggressive_enabled",
        "FDAI_CONVERSATION_T2_AGGRESSIVE_ENABLED",
        "conversation",
        "boolean",
        False,
    ),
    RuntimeSettingSpec(
        "conversation.prompt_ablation.profile",
        "FDAI_PROMPT_ABLATION_PROFILE",
        "conversation",
        "enum",
        "NONE",
        options=(
            "NONE",
            "PACKS",
            "TOOLS",
            "OPERATOR-MEMORY",
            "SKILLS",
            "OPTIONAL-CONTEXT",
        ),
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

    def environment_values(self) -> dict[str, object]:
        """Return validated startup values without durable overrides."""
        return self._effective_values({})

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
            "integrations": self._integration_projection(effective),
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

    def _integration_projection(self, effective: Mapping[str, object]) -> list[dict[str, object]]:
        """Project source-attributed integration rows for this runtime only."""
        rows = integration_projection(self.env)
        for row in rows:
            if row["key"] == "human-access":
                row["enabled"] = effective["human_access.enabled"]
        return rows

    def _runtime_projection(self) -> dict[str, object]:
        runtime_env = self.env.get("RUNTIME_ENV", "").strip().lower()
        environment = runtime_env if runtime_env in {"dev", "staging", "prod"} else "unspecified"
        autonomy_default = self.env.get("AUTONOMY_MODE_DEFAULT", "shadow").strip().lower()
        autonomy_status = autonomy_default if autonomy_default == "shadow" else "invalid"
        false_values = {"0", "false", "no", "off"}
        return {
            "environment": environment,
            "state_store_durable": self.durable,
            "autonomy_default": autonomy_status,
            "pantheon_enabled": (
                self.env.get("FDAI_START_PANTHEON", "").strip().casefold() not in false_values
            ),
            "workflow_observation_enabled": (
                self.env.get("FDAI_WORKFLOW_SHADOW", "").strip().casefold() not in false_values
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
        try:
            stored = await self.store.read_state(_STATE_KEY)
        except psycopg.Error as exc:
            raise RuntimeSettingsUnavailableError(
                "durable runtime settings are unavailable"
            ) from exc
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
            default = (
                spec.development_default
                if spec.development_default is not None
                and self.env.get("RUNTIME_ENV", "").strip().casefold() == "dev"
                else spec.default
            )
            return spec.validate(default)
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


__all__ = [
    "RUNTIME_SETTING_SPECS",
    "RuntimeSettingSpec",
    "RuntimeSettingsConflictError",
    "RuntimeSettingsService",
    "RuntimeSettingsUnavailableError",
    "runtime_settings_service_from_env",
]
