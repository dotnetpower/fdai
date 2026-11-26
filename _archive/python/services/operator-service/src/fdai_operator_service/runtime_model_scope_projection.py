"""Validate optional model sub-scope evidence without changing global runtime health."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from fdai_service_contracts.model_provider_health import (
    ModelProviderRegistrationV1,
    ModelProviderScopeSnapshotV1,
    validate_model_provider_registration,
)
from fdai_service_contracts.self_health import OperationalStateSnapshotV1

from fdai_operator_service.families.operations import ProjectionUnavailableError


def project_runtime_operational_state(
    value: object, *, read_now: Callable[[], datetime]
) -> dict[str, object]:
    """Decode the existing runtime record and retain its optional model-scope validation."""
    if not isinstance(value, Mapping):
        raise ProjectionUnavailableError("runtime operational state is malformed")
    revision = value.get("revision")
    snapshot_raw = value.get("snapshot")
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
        or not isinstance(snapshot_raw, Mapping)
    ):
        raise ProjectionUnavailableError("runtime operational state is malformed")
    try:
        snapshot = OperationalStateSnapshotV1.model_validate(snapshot_raw)
    except ValueError as exc:
        raise ProjectionUnavailableError("runtime operational state is malformed") from exc
    result: dict[str, object] = {
        "source": "postgresql:state_kv",
        "durable": True,
        "revision": revision,
        "snapshot": snapshot.model_dump(mode="json"),
    }
    result.update(project_runtime_model_scope(value, snapshot, read_now=read_now))
    return result


def project_runtime_model_scope(
    value: Mapping[str, object],
    snapshot: OperationalStateSnapshotV1,
    *,
    read_now: Callable[[], datetime],
) -> dict[str, object]:
    """Return only validated sub-scope siblings; never narrow the global adapter aggregate."""
    if any(
        row.signal.value == "adapter_healthcheck" and row.status.value == "healthy"
        for row in snapshot.self_health.signals
    ):
        raise ProjectionUnavailableError("configured-adapter coverage is unavailable")
    result: dict[str, object] = {}
    scope_raw = value.get("model_provider_scope")
    if scope_raw is not None:
        try:
            scope = ModelProviderScopeSnapshotV1.model_validate(scope_raw)
            registration = ModelProviderRegistrationV1.model_validate(
                value.get("model_provider_registration")
            )
            validate_model_provider_registration(scope, registration)
            if (
                scope.parent_snapshot_digest != snapshot.snapshot_digest
                or scope.generated_at != snapshot.generated_at
            ):
                raise ValueError("provider scope belongs to another runtime snapshot")
            adapter_age = next(
                row.maximum_age_seconds
                for row in snapshot.self_health.signals
                if row.signal.value == "adapter_healthcheck"
            )
            if any(row.maximum_age_seconds != adapter_age for row in scope.observations):
                raise ValueError("provider scope does not match catalog freshness")
            read_at = read_now()
            if any(
                row.observed_at is not None
                and row.fresh
                and not 0 <= (read_at - row.observed_at).total_seconds() <= row.maximum_age_seconds
                for row in scope.observations
            ):
                raise ValueError("model-provider scope is stale at read time")
        except ValueError as exc:
            raise ProjectionUnavailableError("model-provider scope is malformed") from exc
        result["model_provider_scope"] = scope.model_dump(mode="json")
        result["model_provider_registration"] = registration.model_dump(mode="json")
    elif value.get("model_provider_registration") is not None:
        raise ProjectionUnavailableError("model-provider scope is malformed")
    return result
