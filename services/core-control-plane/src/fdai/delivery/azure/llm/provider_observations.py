"""Process- and binding-qualified observations of normal embedding provider calls."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from threading import Lock
from uuid import uuid4

import httpx
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.model_provider_health import (
    ConfiguredModelBindingV1,
    ModelProviderHealth,
    ModelProviderObservationV1,
    ModelProviderRegistrationV1,
    ModelProviderScopeSnapshotV1,
)

from fdai.shared.providers.self_health import (
    ModelProviderObservationSource,
    SelfHealthExporterUnavailableError,
)


@dataclass(slots=True)
class ProviderInvocationObservation:
    result: bool | None = None


class EmbeddingProviderObservations:
    """Retain one fully settled invocation cohort, never a rate or all-model health."""

    def __init__(
        self,
        *,
        binding_digest: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.exporter_id = (
            f"process:provider:t1.embedding:{uuid4().hex}:{binding_digest.removeprefix('sha256:')}"
        )
        self.binding_digest = binding_digest
        self._clock = clock
        self._lock = Lock()
        self._pending: set[object] = set()
        self._last: tuple[bool, datetime] | None = None
        self._missing_reason = "source_missing"
        self._cohort_result: bool | None = True

    @contextmanager
    def invocation(self) -> Iterator[ProviderInvocationObservation]:
        """Observe one logical call; unresolved or cancelled work never becomes success."""
        token = object()
        observation = ProviderInvocationObservation()
        with self._lock:
            if not self._pending:
                self._cohort_result = True
            self._pending.add(token)
        try:
            yield observation
        finally:
            with self._lock:
                recorded_at = self._clock()
                self._pending.remove(token)
                if observation.result is None:
                    self._cohort_result = None
                elif self._cohort_result is not None:
                    self._cohort_result = self._cohort_result and observation.result
                if not self._pending:
                    self._last = (
                        (self._cohort_result, recorded_at)
                        if self._cohort_result is not None
                        else None
                    )
                    self._missing_reason = "source_incomplete"

    def snapshot(self) -> tuple[bool, datetime]:
        with self._lock:
            if self._pending:
                raise SelfHealthExporterUnavailableError(reason="source_incomplete")
            if self._last is None:
                raise SelfHealthExporterUnavailableError(reason=self._missing_reason)
            return self._last


@dataclass(frozen=True, slots=True)
class EmbeddingProviderObservationSource:
    observations: EmbeddingProviderObservations
    client: httpx.AsyncClient
    maximum_age_seconds: int
    role: str = field(default="t1.embedding", init=False)

    @property
    def binding_digest(self) -> str:
        return self.observations.binding_digest

    @property
    def exporter_id(self) -> str:
        return self.observations.exporter_id

    async def observe(self, *, now: datetime) -> ModelProviderObservationV1:
        if self.client.is_closed:
            raise SelfHealthExporterUnavailableError(reason="source_unreachable")
        success, observed_at = self.observations.snapshot()
        age = (now - observed_at).total_seconds()
        if age < 0:
            raise SelfHealthExporterUnavailableError(reason="source_from_future")
        if age > self.maximum_age_seconds:
            raise SelfHealthExporterUnavailableError(reason="source_stale")
        return ModelProviderObservationV1(
            role=self.role,
            binding_digest=self.binding_digest,
            health=ModelProviderHealth.HEALTHY if success else ModelProviderHealth.UNHEALTHY,
            value=Decimal(int(success)),
            observed_at=observed_at,
            source=self.exporter_id,
            maximum_age_seconds=self.maximum_age_seconds,
            fresh=True,
            reason="observed_provider_contract",
        )


class ConfiguredModelProviderScope:
    """Preserve every configured model obligation and expose sub-adapter evidence separately."""

    def __init__(
        self,
        *,
        configured_bindings: tuple[ConfiguredModelBindingV1, ...],
        registration_digest: str | None,
        sources: dict[str, ModelProviderObservationSource],
        maximum_age_seconds: int,
    ) -> None:
        self._bindings = tuple(sorted(configured_bindings, key=lambda item: item.role))
        self._registration = registration_digest
        self._sources = dict(sources)
        self._age = maximum_age_seconds
        self._instance = uuid4().hex
        registration_body = {
            "process_instance": self._instance,
            "source_artifact_digest": registration_digest,
            "configured_bindings": [binding.model_dump(mode="json") for binding in self._bindings],
        }
        self.registration = ModelProviderRegistrationV1.model_validate(
            {
                **registration_body,
                "registration_digest": canonical_digest(registration_body),
            }
        )

    async def observe(
        self, *, now: datetime, parent_snapshot_digest: str
    ) -> ModelProviderScopeSnapshotV1:
        rows: list[ModelProviderObservationV1] = []
        for binding in self._bindings:
            source = self._sources.get(binding.role)
            reason = "source_missing"
            if source is not None:
                try:
                    row = await source.observe(now=now)
                except SelfHealthExporterUnavailableError as exc:
                    reason = exc.reason
                else:
                    if row.role == binding.role and row.binding_digest == binding.binding_digest:
                        rows.append(row)
                        continue
                    reason = "source_binding_mismatch"
            rows.append(
                ModelProviderObservationV1(
                    role=binding.role,
                    binding_digest=binding.binding_digest,
                    source=f"unavailable:model-provider:{binding.role}",
                    health=ModelProviderHealth.UNKNOWN,
                    maximum_age_seconds=self._age,
                    fresh=False,
                    reason=reason,
                )
            )
        complete = (
            bool(rows)
            and self._registration is not None
            and all(row.health is not ModelProviderHealth.UNKNOWN for row in rows)
        )
        health = (
            ModelProviderHealth.UNKNOWN
            if not complete
            else ModelProviderHealth.UNHEALTHY
            if any(row.health is ModelProviderHealth.UNHEALTHY for row in rows)
            else ModelProviderHealth.HEALTHY
        )
        body = {
            "schema_version": "1.0.0",
            "scope_kind": "process_configured_model_roles",
            "process_instance": self._instance,
            "registration_digest": (
                self.registration.registration_digest if self._registration is not None else None
            ),
            "parent_snapshot_digest": parent_snapshot_digest,
            "configured_bindings": [row.model_dump(mode="json") for row in self._bindings],
            "observations": [row.model_dump(mode="json") for row in rows],
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "coverage_complete": complete,
            "health": health,
            "execution_authority": False,
        }
        return ModelProviderScopeSnapshotV1.model_validate(
            {**body, "snapshot_digest": canonical_digest(body)}
        )
