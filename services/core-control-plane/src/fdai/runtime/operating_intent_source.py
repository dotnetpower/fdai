"""Runtime binding and bounded revalidation for the deployment-owned intent source.

Distinct from the generic ``FDAI_OPERATING_MODEL_PATH`` mechanism in
``operating_model.py`` (which may legitimately carry only ``Resource`` instances),
this binding is specifically for ``ServiceObjective``, ``RecoveryObjective``,
``CostObjective``, ``ArchitectureConstraint``, ``Ownership``, and ``ChangeWindow``.
It requires every candidate source to carry the operator-pinned exact revision,
self-consistent provenance, and whole-document digest, and it fails closed -
preserving whatever operating-intent graph is already durably owned - on a missing,
duplicate, stale, or cross-release attempt rather than projecting a partial or wrong
graph.

Admission is *continuous*, not startup-only. A source that was complete and fresh at
startup can later leave its effective interval, exceed its declared freshness, or
vanish from the deployment mount. Every admission attempt therefore records a bounded,
self-expiring admission (:mod:`fdai.core.operational_context.operating_intent_admission`)
that authority consumers gate on; when an attempt fails - including a projection or
ontology-catalog failure - the projected graph is kept as evidence and history while
intent authority is durably quarantined before the attempt returns.

Manifest inspection, interrupted-apply recovery, projection, and the admission write
all run inside the deployment-wide resource lock, on a key disjoint from the continuous
operating-model worker's. Without it a second replica starting concurrently would read
the first replica's in-flight ``applying`` manifest as an interrupted apply and delete
the subgraph out from under it.

The lock serializes writers but does not order releases, so the admission record is
additionally fenced by the operator-declared rollout generation: a departing replica
never overwrites - and so never authorizes or quarantines - the admission of the
rollout that replaced it.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fdai.core.operational_context import (
    OPERATING_INTENT_SOURCE_ADMISSION_KEY,
    OperatingIntentSourceBinding,
    OperatingIntentSourceError,
    OperatingModelProjectionResult,
    OperatingModelProjector,
    validate_operating_intent_source_document,
)
from fdai.core.operational_context.operating_intent_admission import (
    MAX_ADMITTED_OBJECT_IDS,
    MAX_OPERATING_INTENT_ADMISSION_AGE_SECONDS,
)
from fdai.delivery.operating_model import (
    JsonOperatingIntentSourceProvider,
    JsonOperatingModelProviderConfig,
)
from fdai.runtime.change_window_history import record_change_window_history
from fdai.runtime.operating_intent_binding import (
    OPERATING_INTENT_SOURCE_PATH_ENV,
    decode_operating_intent_manifest,
    operating_intent_binding_from_env,
    operating_intent_generation_from_env,
    operating_intent_positive_int,
)
from fdai.runtime.operating_model import (
    operating_model_projection_matches,
    project_operating_model_snapshot,
)
from fdai.shared.contracts.models import OntologyLinkType, OntologyObjectType
from fdai.shared.providers.ontology_instance import OntologyInstanceStore
from fdai.shared.providers.operating_model import (
    OperatingIntentSourceDocument,
    OperatingModelSnapshot,
)
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.operating_intent_source")

OPERATING_INTENT_SOURCE_STATUS_KEY = "operating-intent-source:status"
OPERATING_INTENT_SOURCE_LOCK_KEY = "operating-intent-source:apply"
"""Fixed, bounded lock identity for the whole read-recover-project critical section.

Constant by design: the lock serializes one deployment-wide manifest, so a per-replica
or per-attempt identity would serialize nothing. It is disjoint from
``OPERATING_MODEL_LOCK_KEY`` because the two sources own disjoint manifests.
"""

_OPERATING_INTENT_SOURCE_MANIFEST_KEY = "operating-intent-source:manifest"
_DEFAULT_REVALIDATION_SECONDS = 300
_ADMISSION_VALIDITY_MULTIPLIER = 3


@dataclass(frozen=True, slots=True)
class OperatingIntentSourceRuntime:
    """Admit the pinned intent source once, and again on every bounded revalidation.

    One instance owns exactly one deployment-owned source binding: its pinned
    expectation, its file provider, its disjoint durable manifest, and the resource
    lock guarding that manifest. ``admit`` is the single entry point used by both
    startup and the revalidation worker, so a post-startup pass applies the identical
    fail-closed checks the first pass did.
    """

    binding: OperatingIntentSourceBinding
    provider: JsonOperatingIntentSourceProvider
    store: OntologyInstanceStore
    object_types: tuple[OntologyObjectType, ...]
    link_types: tuple[OntologyLinkType, ...]
    state_store: StateStore | None
    resource_lock: ResourceLock
    generation: int = 1
    revalidation_seconds: int = _DEFAULT_REVALIDATION_SECONDS

    def __post_init__(self) -> None:
        if self.revalidation_seconds < 1:
            raise ValueError("operating intent source revalidation interval MUST be positive")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int):
            raise ValueError("operating intent source generation MUST be an integer")
        if self.generation < 1:
            raise ValueError("operating intent source generation MUST be >= 1")
        if self.admission_validity_seconds > MAX_OPERATING_INTENT_ADMISSION_AGE_SECONDS:
            raise ValueError(
                "operating intent source revalidation interval exceeds the admission validity bound"
            )

    @property
    def admission_validity_seconds(self) -> int:
        """Return how long one successful admission may keep backing authority.

        A multiple of the revalidation interval, so a single slow or missed pass does
        not immediately withdraw authority while a persistently failing or stopped
        worker still expires it with no further action from anyone.
        """

        return self.revalidation_seconds * _ADMISSION_VALIDITY_MULTIPLIER

    async def admit(self, *, now: datetime) -> OperatingModelProjectionResult | None:
        """Revalidate the pinned source and record what it currently proves.

        Returns the admitted projection result - counts and pinned revision - whenever
        the source is currently admitted, whether this attempt replaced the owned
        subgraph or found the durable manifest already closing exactly this document.
        Every failure path preserves the durably owned graph and durably records a
        denying admission *before* returning, so one bad revalidation neither takes
        the process down nor leaves stale authority alive until expiry.
        """

        try:
            document = await self.provider.load()
            validate_operating_intent_source_document(
                document,
                binding=self.binding,
                now=now,
            )
        except (OSError, ValueError, OperatingIntentSourceError) as exc:
            _LOGGER.warning(
                "operating_intent_source_validation_failed",
                extra={"error_type": type(exc).__name__},
            )
            await self._deny("quarantined", reason="source_validation_failed", now=now)
            return None

        stack = AsyncExitStack()
        try:
            await stack.enter_async_context(
                self.resource_lock.acquire(OPERATING_INTENT_SOURCE_LOCK_KEY)
            )
        except Exception as exc:  # noqa: BLE001 - a distributed backend raises its own error type
            # Never project without the lock: a concurrent replica's in-flight
            # ``applying`` manifest would be misread as an interrupted apply.
            _LOGGER.warning(
                "operating_intent_source_lock_unavailable",
                extra={"error_type": type(exc).__name__},
            )
            await self._deny("unavailable", reason="resource_lock_unavailable", now=now)
            return None
        async with stack:
            try:
                result = await self._apply(document)
            except Exception as exc:  # noqa: BLE001 - any projection defect quarantines
                # Ontology catalog validation, a malformed durable manifest, and a
                # store write failure all land here. Each one means the pinned
                # document did not become the owned graph, so authority is withdrawn
                # immediately instead of surviving on the previous admission until it
                # expires - and startup records the denial rather than aborting.
                _LOGGER.warning(
                    "operating_intent_source_projection_failed",
                    extra={"error_type": type(exc).__name__},
                )
                await self._deny("quarantined", reason="projection_failed", now=now)
                return None
            await self._record_admission(result, document=document, now=now)
        return result

    async def _apply(
        self, document: OperatingIntentSourceDocument
    ) -> OperatingModelProjectionResult:
        """Project the validated document, or restate what the manifest already closes."""

        already_projected = self.state_store is not None and (
            await operating_model_projection_matches(
                status_store=self.state_store,
                source_revision=document.snapshot.source_revision,
                snapshot_digest=self.binding.expected_sha256,
                manifest_key=_OPERATING_INTENT_SOURCE_MANIFEST_KEY,
                expected_object_ids=tuple(item.id for item in document.snapshot.objects),
                expected_link_keys=tuple(
                    (item.from_id, item.link_type, item.to_id) for item in document.snapshot.links
                ),
            )
        )
        if already_projected:
            return OperatingModelProjectionResult(
                source_revision=document.snapshot.source_revision,
                object_count=len(document.snapshot.objects),
                link_count=len(document.snapshot.links),
            )
        return await project_operating_model_snapshot(
            snapshot=document.snapshot,
            store=self.store,
            object_types=self.object_types,
            link_types=self.link_types,
            status_store=self.state_store,
            snapshot_digest=self.binding.expected_sha256,
            manifest_key=_OPERATING_INTENT_SOURCE_MANIFEST_KEY,
            status_key=OPERATING_INTENT_SOURCE_STATUS_KEY,
        )

    async def _record_admission(
        self,
        result: OperatingModelProjectionResult,
        *,
        document: OperatingIntentSourceDocument,
        now: datetime,
    ) -> None:
        """Record the current admission and restate the projection status it backs.

        The record enumerates the object identities this source owns, so a consumer
        can tell an intent-source ``ChangeWindow`` from one the generic or continuous
        operating-model path projected. It also carries the rollout generation, which
        is what lets a reader reject an admission written by a replica of a different
        release.

        The status key is rewritten even when this pass skipped projection, so a
        recovery that follows a quarantine cannot leave the surface reading ``rejected``
        while the admission reads ``admitted``.
        """

        if self.state_store is None:
            return
        await record_change_window_history(
            self.state_store,
            document.snapshot,
            document_digest=self.binding.expected_sha256,
            recorded_at=now,
        )
        owned_object_ids = sorted(item.id for item in document.snapshot.objects)
        if len(owned_object_ids) > MAX_ADMITTED_OBJECT_IDS:
            await self._deny(
                "quarantined",
                reason=(
                    "operating intent source owns more object identities than one admission "
                    "record may enumerate"
                ),
                now=now,
            )
            return
        written = await self._write_fenced(
            OPERATING_INTENT_SOURCE_ADMISSION_KEY,
            {
                "schema_version": "1.1.0",
                "status": "admitted",
                "binding_generation": self.generation,
                "source_revision": result.source_revision,
                "snapshot_digest": self.binding.expected_sha256,
                "owned_object_ids": owned_object_ids,
                "validated_at": now.isoformat(),
                "max_age_seconds": self.admission_validity_seconds,
            },
            now=now,
        )
        if not written:
            return
        await self.state_store.write_state(
            OPERATING_INTENT_SOURCE_STATUS_KEY,
            {
                "schema_version": "1.0.0",
                "status": "projected",
                "source_revision": result.source_revision,
                "object_count": result.object_count,
                "link_count": result.link_count,
            },
        )

    async def _deny(self, status: str, *, reason: str, now: datetime) -> None:
        """Withdraw intent authority while leaving the projected graph intact."""

        if self.state_store is None:
            return
        written = await self._write_fenced(
            OPERATING_INTENT_SOURCE_ADMISSION_KEY,
            {
                "schema_version": "1.1.0",
                "status": status,
                "binding_generation": self.generation,
                "reason": reason,
                "validated_at": now.isoformat(),
            },
            now=now,
        )
        if not written:
            return
        await self.state_store.write_state(
            OPERATING_INTENT_SOURCE_STATUS_KEY,
            {"schema_version": "1.0.0", "status": "rejected", "reason": reason},
        )

    async def _write_fenced(
        self,
        key: str,
        value: Mapping[str, object],
        *,
        now: datetime,
    ) -> bool:
        """Write an admission only while a newer rollout generation currently owns it.

        A rolling deployment runs two releases at once. The departing replica's
        revalidation worker keeps proving its own older pin, and without this fence it
        would overwrite the shared record - either authorizing the new rollout with a
        binding the new replicas never validated, or quarantining a healthy new
        rollout on its way out. The deployment-wide lock serializes writers but says
        nothing about which release should win, so the generation does.

        The fence is bounded rather than permanent. A newer generation's record stops
        proving anything once its own validity window elapses, so from that instant it
        cannot grant authority to anybody and holding the key would only deny a
        rolled-back release forever. Yielding then makes an ordinary rollback recover
        after at most one validity window instead of requiring an operator to delete
        durable state by hand.

        Returns whether the write happened, so a fenced-out caller also leaves the
        operator-facing status surface describing the rollout that actually owns it.
        """

        if self.state_store is None:
            return False
        current = await self.state_store.read_state(key)
        if current is not None and self._newer_generation_is_current(current, now=now):
            _LOGGER.info(
                "operating_intent_source_admission_fenced",
                extra={
                    "generation": self.generation,
                    "current_generation": current.get("binding_generation"),
                },
            )
            return False
        await self.state_store.write_state(key, value)
        return True

    def _newer_generation_is_current(self, record: Mapping[str, object], *, now: datetime) -> bool:
        """Return whether ``record`` belongs to a newer generation that is still live."""

        generation = record.get("binding_generation")
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation <= self.generation
        ):
            return False
        raw_validated_at = record.get("validated_at")
        if not isinstance(raw_validated_at, str):
            # A newer generation's record with no usable proof time cannot be aged out
            # by anyone, so it is treated as live and this older replica stands down.
            return True
        try:
            validated_at = datetime.fromisoformat(raw_validated_at)
        except ValueError:
            return True
        if validated_at.tzinfo is None:
            return True
        max_age_seconds = record.get("max_age_seconds")
        if max_age_seconds is None and record.get("status") in {"quarantined", "unavailable"}:
            # A denying record declares no window of its own; bound it by this
            # replica's so a quarantine from a departed rollout still ages out.
            max_age_seconds = self.admission_validity_seconds
        if (
            isinstance(max_age_seconds, bool)
            or not isinstance(max_age_seconds, int)
            or max_age_seconds < 1
            or max_age_seconds > MAX_OPERATING_INTENT_ADMISSION_AGE_SECONDS
        ):
            return True
        age_seconds = (now - validated_at).total_seconds()
        return age_seconds < 0 or age_seconds <= max_age_seconds


async def bind_operating_intent_source_from_env(
    *,
    store: OntologyInstanceStore | None,
    object_types: Sequence[OntologyObjectType],
    link_types: Sequence[OntologyLinkType],
    status_store: StateStore | None = None,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
    resource_lock: ResourceLock | None = None,
) -> tuple[OperatingModelProjectionResult | None, OperatingIntentSourceRuntime | None]:
    """Admit the pinned source once and return the runtime that keeps admitting it.

    The returned runtime is ``None`` only when no source is configured, in which case
    any previously owned intent subgraph is released. Composition uses this instead of
    building the binding twice - once to project and once to supervise revalidation.
    """

    values = env if env is not None else os.environ
    runtime = build_operating_intent_source_runtime(
        store=store,
        object_types=object_types,
        link_types=link_types,
        state_store=status_store,
        environment=values,
        resource_lock=resource_lock,
    )
    if runtime is None:
        await _clear_unconfigured_binding(
            store=store,
            object_types=object_types,
            link_types=link_types,
            status_store=status_store,
            resource_lock=resource_lock,
        )
        return None, None
    return await runtime.admit(now=now if now is not None else datetime.now(UTC)), runtime


async def project_operating_intent_source_from_env(
    *,
    store: OntologyInstanceStore | None,
    object_types: Sequence[OntologyObjectType],
    link_types: Sequence[OntologyLinkType],
    status_store: StateStore | None = None,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
    resource_lock: ResourceLock | None = None,
) -> OperatingModelProjectionResult | None:
    """Load, validate, and project the pinned six-type operating-intent source.

    Returns ``None`` when the source is unconfigured (clearing any previously owned
    instances) or when the candidate source fails a fail-closed check; in the latter
    case the failure is recorded durably with its reason, intent authority is
    quarantined, and the already-projected graph is left untouched. Raises only on a
    genuine startup/config defect (a missing required binding env var) - the same
    convention ``project_operating_model_from_env`` uses for its own
    required-store/path checks.
    """

    result, _ = await bind_operating_intent_source_from_env(
        store=store,
        object_types=object_types,
        link_types=link_types,
        status_store=status_store,
        env=env,
        now=now,
        resource_lock=resource_lock,
    )
    return result


def build_operating_intent_source_runtime(
    *,
    store: OntologyInstanceStore | None,
    object_types: Sequence[OntologyObjectType],
    link_types: Sequence[OntologyLinkType],
    state_store: StateStore | None,
    environment: Mapping[str, str],
    resource_lock: ResourceLock | None = None,
) -> OperatingIntentSourceRuntime | None:
    """Compose the pinned intent-source runtime, or ``None`` when unconfigured."""

    raw_path = environment.get(OPERATING_INTENT_SOURCE_PATH_ENV, "").strip()
    if not raw_path:
        return None
    if store is None:
        raise RuntimeError("FDAI_OPERATING_INTENT_SOURCE_PATH requires an ontology instance store")
    binding = operating_intent_binding_from_env(environment)
    max_bytes = operating_intent_positive_int(
        environment,
        "FDAI_OPERATING_INTENT_SOURCE_MAX_BYTES",
        16 * 1024 * 1024,
    )
    revalidation_seconds = operating_intent_positive_int(
        environment,
        "FDAI_OPERATING_INTENT_SOURCE_REVALIDATE_SECONDS",
        _DEFAULT_REVALIDATION_SECONDS,
    )
    if resource_lock is None:
        from fdai.runtime.providers import _build_resource_lock

        resource_lock = _build_resource_lock(environment)
    return OperatingIntentSourceRuntime(
        binding=binding,
        provider=JsonOperatingIntentSourceProvider(
            config=JsonOperatingModelProviderConfig(path=Path(raw_path), max_bytes=max_bytes)
        ),
        store=store,
        object_types=tuple(object_types),
        link_types=tuple(link_types),
        state_store=state_store,
        resource_lock=resource_lock,
        generation=operating_intent_generation_from_env(environment),
        revalidation_seconds=revalidation_seconds,
    )


async def _clear_unconfigured_binding(
    *,
    store: OntologyInstanceStore | None,
    object_types: Sequence[OntologyObjectType],
    link_types: Sequence[OntologyLinkType],
    status_store: StateStore | None,
    resource_lock: ResourceLock | None = None,
) -> None:
    """Release any previously owned intent subgraph and record the empty binding.

    Releasing is itself a manifest read plus a destructive projection, so it holds the
    same deployment-wide lock the admission path does. A lock that cannot be acquired
    records ``unavailable`` and clears nothing: leftover objects then grant no
    authority, because that denying admission is exactly what consumers gate on.
    """

    stack = AsyncExitStack()
    if resource_lock is not None:
        try:
            await stack.enter_async_context(resource_lock.acquire(OPERATING_INTENT_SOURCE_LOCK_KEY))
        except Exception as exc:  # noqa: BLE001 - a distributed backend raises its own error type
            _LOGGER.warning("operating_intent_source_lock_unavailable", exc_info=True)
            if status_store is not None:
                await status_store.write_state(
                    OPERATING_INTENT_SOURCE_ADMISSION_KEY,
                    {
                        "schema_version": "1.0.0",
                        "status": "unavailable",
                        "reason": f"resource lock unavailable: {exc}",
                    },
                )
            return
    async with stack:
        await _release_unconfigured_subgraph(
            store=store,
            object_types=object_types,
            link_types=link_types,
            status_store=status_store,
        )


async def _release_unconfigured_subgraph(
    *,
    store: OntologyInstanceStore | None,
    object_types: Sequence[OntologyObjectType],
    link_types: Sequence[OntologyLinkType],
    status_store: StateStore | None,
) -> None:
    if store is not None:
        prior_manifest = (
            await status_store.read_state(_OPERATING_INTENT_SOURCE_MANIFEST_KEY)
            if status_store is not None
            else None
        )
        previous_object_ids, previous_link_keys = decode_operating_intent_manifest(prior_manifest)
        if previous_object_ids or previous_link_keys:
            await OperatingModelProjector(
                store=store,
                object_types=object_types,
                link_types=link_types,
            ).project(
                OperatingModelSnapshot(source_revision="unconfigured", objects=(), links=()),
                previous_object_ids=previous_object_ids,
                previous_link_keys=previous_link_keys,
            )
    if status_store is None:
        return
    await status_store.write_state(
        _OPERATING_INTENT_SOURCE_MANIFEST_KEY,
        {
            "schema_version": "1.0.0",
            "status": "unconfigured",
            "source_revision": "unconfigured",
            "object_ids": [],
            "link_keys": [],
        },
    )
    await status_store.write_state(
        OPERATING_INTENT_SOURCE_STATUS_KEY,
        {"schema_version": "1.0.0", "status": "unconfigured"},
    )
    await status_store.write_state(
        OPERATING_INTENT_SOURCE_ADMISSION_KEY,
        {"schema_version": "1.0.0", "status": "unconfigured"},
    )


__all__ = [
    "OPERATING_INTENT_SOURCE_LOCK_KEY",
    "OPERATING_INTENT_SOURCE_STATUS_KEY",
    "OperatingIntentSourceRuntime",
    "bind_operating_intent_source_from_env",
    "build_operating_intent_source_runtime",
    "project_operating_intent_source_from_env",
]
