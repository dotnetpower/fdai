"""Heimdall owns independent observation, bounded anomaly episodes and evidence relays.

Admin notifications retain per-initiator/action deduplication; observation grants no authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import Counter, deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.action_semantics import ActionSemanticsCatalog, is_irreversible
from fdai.agents._framework.alert_noise_callbacks import HeimdallAlertNoiseMixin
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.heimdall_action_observation import (
    ActionObservationHook,
    HeimdallActionObservationMixin,
)
from fdai.agents._framework.heimdall_alert_window import (
    MAX_EPISODES_PER_RESOURCE as _MAX_EPISODES_PER_RESOURCE,
)
from fdai.agents._framework.heimdall_alert_window import (
    MAX_TRACKED_KEYS as _MAX_TRACKED_KEYS,
)
from fdai.agents._framework.heimdall_alert_window import EpisodeKey as _EpisodeKey
from fdai.agents._framework.heimdall_alert_window import HeimdallAlertWindowMixin
from fdai.agents._framework.heimdall_alert_window import (
    anomaly_idempotency_key as _anomaly_idempotency_key,
)
from fdai.agents._framework.heimdall_alert_window import (
    event_window_time as _event_window_time,
)
from fdai.agents._framework.heimdall_alert_window import (
    incident_episode_id as _incident_episode_id,
)
from fdai.agents._framework.heimdall_forecast import HeimdallForecastMixin
from fdai.agents._framework.heimdall_helpers import (
    TRACE_CONTINUITY_REASONS as _TRACE_CONTINUITY_REASONS,
)
from fdai.agents._framework.heimdall_helpers import event_severity as _event_severity
from fdai.agents._framework.heimdall_helpers import evict_oldest as _evict_oldest
from fdai.agents._framework.heimdall_helpers import (
    trace_continuity_evidence as _trace_continuity_evidence,
)
from fdai.agents._framework.heimdall_huginn_projection import (
    RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
    evidence_conflict_record,
    recovery_effect_observation_record,
)
from fdai.agents._framework.heimdall_provider_schema import HeimdallProviderSchemaMixin
from fdai.agents._framework.heimdall_retrieval_validation import (
    retrieval_validation_from_event,
)
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    attach_agent_state_evidence,
    capability_facts,
    capped_list,
    evidence_backed_result,
    mentioned,
    semantic_intents,
)
from fdai.agents._framework.outbox_publication import (
    PublicationClaim,
    claim_expired,
    new_publication_claim_owner,
    publish_claimed_outbox,
)
from fdai.agents._framework.pantheon import _HEIMDALL
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.role_answers import heimdall_role_answer
from fdai.agents._framework.specialist_ingress import CHAOS_ACTION_TYPES, SPECIALIST_EVENT_PREFIX
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.detection.forecast_closure import ForecastClosureCoordinator
from fdai.core.detection.forecast_episode import ForecastEpisodeStore
from fdai.core.detection.forecast_evaluation import ForecastEpisodeEvaluator
from fdai.core.readiness import (
    AuthorityCeiling,
    DetectionReadinessDimension,
    DetectionReadinessObservation,
    DetectionReadinessSnapshot,
    reduce_detection_readiness,
)
from fdai.core.rule_semantic_generation import RuleGenerationValidationHandler
from fdai.rule_catalog.schema.rule_semantic_generation_events import (
    RULE_GENERATION_BUILD_RESULT_TOPIC,
    RuleGenerationBuildResultEvent,
)
from fdai.shared.providers.provider_schema import ProviderSchemaDriftProjector
from fdai.shared.providers.state_store import StateStore

AlerterHook = Callable[[dict[str, Any]], Awaitable[None]]
"""Var-provided hook that delivers the admin notification card."""

IncidentCandidateHook = Callable[[dict[str, Any]], Awaitable[bool]]
"""Composition hook returning whether the lifecycle accepted a candidate."""

ReadInvestigationHook = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]
"""Composition-provided read-only investigation responder."""

OperationalEvidenceHook = Callable[[dict[str, Any]], Awaitable[Mapping[str, Any]]]
"""Composition-provided bounded evidence collector for one operational Event."""

_LOG = logging.getLogger(__name__)

_INCIDENT_CORRELATION_DISABLED = frozenset({"none", "disabled"})
_SEVERITY_RANK = {
    severity: rank for rank, severity in enumerate(("critical", "high", "medium", "low", "info"))
}
_DETECTION_READINESS_EVENT = "detection.readiness.observed"
_STATE_KEY = "pantheon/heimdall/sensing-state"
_EPISODE_PREFIX = "pantheon/heimdall/sensing-state/episodes/"
_READINESS_PREFIX = "pantheon/heimdall/sensing-state/readiness/"
_PENDING_READINESS_PREFIX = "pantheon/heimdall/sensing-state/readiness-pending/"
_PUBLICATION_PREFIX = "pantheon/heimdall/publications/"
_PUBLICATION_REPLAY_PAYLOAD_MAX_BYTES = 8192
_PUBLICATION_CLAIM_LEASE = timedelta(minutes=5)
_PUBLICATION_CAS_ATTEMPTS = 8
_PUBLICATION_RECOVERY_LIMIT = 5_000
_PUBLICATION_MAINTENANCE_PAGE = 16
_RULE_VALIDATION_TIMEOUT_SECONDS = 5.0
_FULL_SNAPSHOT_LIMIT = 128
_MAX_KPI_SAMPLES = 512


def _kpi_measured(
    value: float,
    *,
    numerator: int | float,
    denominator: int | float,
    unit: str = "ratio",
) -> dict[str, Any]:
    return {
        "value": float(value),
        "evidence_state": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
    }


def _kpi_unavailable(evidence_state: str, reason: str, *, unit: str = "ratio") -> dict[str, Any]:
    return {
        "value": None,
        "evidence_state": evidence_state,
        "reason": reason,
        "numerator": 0,
        "denominator": 0,
        "unit": unit,
    }


def _ratio_kpi(numerator: object, denominator: object, *, reason: str) -> dict[str, Any]:
    if (
        isinstance(numerator, bool)
        or isinstance(denominator, bool)
        or not isinstance(numerator, int | float)
        or not isinstance(denominator, int | float)
        or denominator <= 0
    ):
        return _kpi_unavailable("insufficient_sample", reason)
    return _kpi_measured(
        float(numerator) / float(denominator),
        numerator=numerator,
        denominator=denominator,
    )


def _mean_kpi(samples: deque[float], *, reason: str, unit: str) -> dict[str, Any]:
    if not samples:
        return _kpi_unavailable("insufficient_sample", reason, unit=unit)
    return _kpi_measured(
        sum(samples) / len(samples),
        numerator=len(samples),
        denominator=len(samples),
        unit=unit,
    )


class Heimdall(
    HeimdallAlertNoiseMixin,
    HeimdallActionObservationMixin,
    HeimdallAlertWindowMixin,
    HeimdallProviderSchemaMixin,
    HeimdallForecastMixin,
    Agent,
):
    """Wave-3 anomaly detection + Wave 6 security correlator."""

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        rate_threshold: int = 5,
        rate_window: int = 300,
        security_high_threshold: int = 5,
        security_window_events: int = 100,
        alerter_hook: AlerterHook | None = None,
        incident_candidate_hook: IncidentCandidateHook | None = None,
        read_investigation_hook: ReadInvestigationHook | None = None,
        operational_evidence_hook: OperationalEvidenceHook | None = None,
        action_observation_hook: ActionObservationHook | None = None,
        alert_rate_per_hour: int = 5,
        clock: Callable[[], float] | None = None,
        forecast_clock: Callable[[], datetime] | None = None,
        forecast_evaluator: ForecastEpisodeEvaluator | None = None,
        forecast_closer: ForecastClosureCoordinator | None = None,
        forecast_store: ForecastEpisodeStore | None = None,
        action_semantics: ActionSemanticsCatalog | None = None,
        provider_schema_drift_projector: ProviderSchemaDriftProjector | None = None,
        state_store: StateStore | None = None,
    ) -> None:
        if rate_threshold < 1:
            raise ValueError("rate_threshold MUST be >= 1")
        if rate_window < 1:
            raise ValueError("rate_window MUST be >= 1")
        super().__init__(spec=_HEIMDALL)
        self.bus = bus
        self._provider_schema_drift_projector = provider_schema_drift_projector
        self._state_store = state_store
        self._rate_threshold = rate_threshold
        self._rate_window = rate_window
        self._max_tracked_keys = _MAX_TRACKED_KEYS
        self._max_episodes_per_resource = _MAX_EPISODES_PER_RESOURCE
        self._recent_events: dict[_EpisodeKey, deque[tuple[float, str, str]]] = {}
        self._recent_episode_keys: dict[str, dict[_EpisodeKey, None]] = {}
        self._incident_episode_ids: dict[_EpisodeKey, str] = {}
        self._incident_episode_severities: dict[_EpisodeKey, str] = {}
        self._security_recent: deque[dict[str, Any]] = deque(maxlen=security_window_events)
        self._security_high_threshold = security_high_threshold
        self._alert_counters: Counter[tuple[str, str]] = Counter()
        self._alerter_hook = alerter_hook
        self._incident_candidate_hook = incident_candidate_hook
        self._read_investigation_hook = read_investigation_hook
        self._operational_evidence_hook = operational_evidence_hook
        self._action_observation_hook = action_observation_hook
        self._alert_rate_per_hour = alert_rate_per_hour
        # Per-initiator rolling-hour alert budget: (window_start, count).
        # Injected clock keeps the window deterministic under test; defaults
        # to a monotonic source so a wall-clock jump cannot reopen the budget.
        self._clock = clock or time.monotonic
        self._forecast_clock = forecast_clock or (lambda: datetime.now(UTC))
        self._forecast_evaluator = forecast_evaluator
        self._forecast_closer = forecast_closer
        self._forecast_store = forecast_store
        self._action_semantics = action_semantics
        self._rule_generation_validation_handler: RuleGenerationValidationHandler | None = None
        self._alert_windows: dict[str, tuple[float, int]] = {}
        self._detection_readiness: dict[str, dict[str, DetectionReadinessObservation]] = {}
        self._detection_readiness_pending: dict[
            tuple[str, str], dict[str, DetectionReadinessObservation]
        ] = {}
        self._detection_readiness_pass_order: dict[str, tuple[str, datetime]] = {}
        self._publication_locks: dict[str, asyncio.Lock] = {}
        self._dirty_episode_keys: set[_EpisodeKey] = set()
        self._dirty_readiness_resources: set[str] = set()
        self._dirty_pending_readiness: set[tuple[str, str]] = set()
        self._publication_lock_refs: dict[str, int] = {}
        self._anomaly_outcomes = Counter[str]()
        self._forecast_absolute_percentage_errors: deque[float] = deque(maxlen=_MAX_KPI_SAMPLES)
        self._readiness_observed_dimensions = 0
        self._readiness_expected_dimensions = 0
        self._stale_inventory_delays_seconds: deque[float] = deque(maxlen=_MAX_KPI_SAMPLES)
        self._pending_effect_observations = 0

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    async def _producer_topic_markers(self) -> None:
        if TYPE_CHECKING and self.bus is not None:
            await self.bus.publish("Heimdall", "object.evidence-conflict", {})
            await self.bus.publish("Heimdall", "object.retrieval-validation", {})

    async def rehydrate(self) -> int:
        """Restore restart-sensitive sensing windows and duplicate fences."""
        if self._state_store is None:
            return 0
        record = await self._state_store.read_state(_STATE_KEY)
        if record is None:
            return 0
        restored = 0
        self._recent_events.clear()
        self._recent_episode_keys.clear()
        episode_rows, _episode_total = await self._state_store.read_state_page(
            _EPISODE_PREFIX,
            limit=_MAX_TRACKED_KEYS,
        )
        for episode_record in reversed(episode_rows):
            episode_key = _decode_episode_key(str(episode_record.get("episode_key") or ""))
            raw_history = episode_record.get("history")
            if episode_key is None or not isinstance(raw_history, list):
                continue
            legacy_history: deque[tuple[float, str, str]] = deque(maxlen=self._rate_threshold * 2)
            for item in raw_history:
                if (
                    isinstance(item, list)
                    and len(item) == 3
                    and isinstance(item[0], int | float)
                    and isinstance(item[1], str)
                    and isinstance(item[2], str)
                ):
                    legacy_history.append((float(item[0]), item[1], item[2]))
            self._recent_events[episode_key] = legacy_history
            self._recent_episode_keys.setdefault(episode_key[0], {})[episode_key] = None
            restored += 1
        for raw_key, raw_history in dict(record.get("recent_events") or {}).items():
            if self._recent_events:
                break
            episode_key = _decode_episode_key(raw_key)
            if episode_key is None or not isinstance(raw_history, list):
                continue
            history: deque[tuple[float, str, str]] = deque(maxlen=self._rate_threshold * 2)
            for item in raw_history:
                if (
                    isinstance(item, list)
                    and len(item) == 3
                    and isinstance(item[0], int | float)
                    and isinstance(item[1], str)
                    and isinstance(item[2], str)
                ):
                    history.append((float(item[0]), item[1], item[2]))
            self._recent_events[episode_key] = history
            self._recent_episode_keys.setdefault(episode_key[0], {})[episode_key] = None
            restored += 1
        self._incident_episode_ids = {
            key: value
            for raw_key, value in dict(record.get("incident_episode_ids") or {}).items()
            if (key := _decode_episode_key(raw_key)) is not None and isinstance(value, str)
        }
        self._incident_episode_severities = {
            key: value
            for raw_key, value in dict(record.get("incident_episode_severities") or {}).items()
            if (key := _decode_episode_key(raw_key)) is not None and isinstance(value, str)
        }
        self._security_recent = deque(
            [item for item in list(record.get("security_recent") or []) if isinstance(item, dict)],
            maxlen=self._security_recent.maxlen,
        )
        self._alert_windows = {
            str(key): (float(value[0]), int(value[1]))
            for key, value in dict(record.get("alert_windows") or {}).items()
            if isinstance(value, list) and len(value) == 2
        }
        self._detection_readiness = _decode_readiness_map(record.get("detection_readiness"))
        readiness_rows, _readiness_total = await self._state_store.read_state_page(
            _READINESS_PREFIX,
            limit=_MAX_TRACKED_KEYS,
        )
        for readiness_record in reversed(readiness_rows):
            resource = str(readiness_record.get("resource_id") or "")
            observations = _decode_readiness_map(
                {resource: readiness_record.get("observations")}
            ).get(resource)
            pass_order = readiness_record.get("pass_order")
            if resource and observations is not None:
                self._detection_readiness[resource] = observations
                if isinstance(pass_order, list) and len(pass_order) == 2:
                    self._detection_readiness_pass_order[resource] = (
                        str(pass_order[0]),
                        datetime.fromisoformat(str(pass_order[1])),
                    )
        self._detection_readiness_pending = _decode_pending_readiness(
            record.get("detection_readiness_pending")
        )
        pending_rows, _pending_total = await self._state_store.read_state_page(
            _PENDING_READINESS_PREFIX,
            limit=_MAX_TRACKED_KEYS,
        )
        for pending_record in reversed(pending_rows):
            resource = str(pending_record.get("resource_id") or "")
            pass_id = str(pending_record.get("pass_id") or "")
            observations = _decode_pending_readiness(
                {f"{resource}\0{pass_id}": pending_record.get("observations")}
            ).get((resource, pass_id))
            if resource and pass_id and observations is not None:
                self._detection_readiness_pending[(resource, pass_id)] = observations
        self._detection_readiness_pass_order = {
            str(resource): (str(value[0]), datetime.fromisoformat(str(value[1])))
            for resource, value in dict(record.get("detection_readiness_pass_order") or {}).items()
            if isinstance(value, list) and len(value) == 2
        }
        return restored

    def register_alerter(self, hook: AlerterHook) -> None:
        self._alerter_hook = hook

    def register_incident_candidate(self, hook: IncidentCandidateHook) -> None:
        """Bind the composition-owned incident candidate validator/writer."""
        self._incident_candidate_hook = hook

    def register_read_investigation(self, hook: ReadInvestigationHook) -> None:
        """Bind a provider-neutral conversational read responder."""
        self._read_investigation_hook = hook

    def register_operational_evidence(self, hook: OperationalEvidenceHook) -> None:
        """Bind a bounded read-only Event evidence collector."""

        self._operational_evidence_hook = hook

    def record_anomaly_outcome(self, outcome: str) -> None:
        """Retain an authoritative anomaly label for KPI denominators."""
        if outcome not in {"true_positive", "false_positive", "false_negative", "missed_critical"}:
            raise ValueError("unsupported anomaly outcome label")
        self._anomaly_outcomes[outcome] += 1

    def record_forecast_absolute_percentage_error(self, error: float) -> None:
        if isinstance(error, bool) or error < 0:
            raise ValueError("forecast absolute percentage error MUST be nonnegative")
        self._forecast_absolute_percentage_errors.append(float(error))

    def health(self) -> dict[str, Any]:
        store_durability = "durable" if self._state_store is not None else "process_local"
        dependencies = {
            "action_observation_hook": (
                "bound" if self._action_observation_hook is not None else "unavailable"
            ),
            "forecast_store": "bound" if self._forecast_store is not None else "unavailable",
            "forecast_evaluator": (
                "bound" if self._forecast_evaluator is not None else "unavailable"
            ),
            "incident_candidate_hook": (
                "bound" if self._incident_candidate_hook is not None else "unavailable"
            ),
            "state_store": store_durability,
        }
        degraded = (
            self._action_observation_hook is None
            or self._forecast_store is None
            or self._state_store is None
        )
        return {
            "agent": "Heimdall",
            "status": "degraded" if degraded else "ok",
            "dependencies": dependencies,
            "backlog": {
                "recent_episode_windows": len(self._recent_events),
                "pending_detection_readiness_passes": len(self._detection_readiness_pending),
                "pending_effect_observations": self._pending_effect_observations,
            },
            "degradation": {
                "state_changes_needing_observation": (
                    "blocked" if self._action_observation_hook is None else "observable"
                ),
                "safe_effect": "rule_only_judgment_continues" if degraded else "none",
            },
            "kpis": {
                "anomaly_precision": self._anomaly_precision_kpi(),
                "anomaly_recall": self._anomaly_recall_kpi(),
                "forecast_mape": self._forecast_mape_kpi(),
                "discovery_coverage_detection_rate": _ratio_kpi(
                    self._readiness_observed_dimensions,
                    self._readiness_expected_dimensions,
                    reason="no_detection_readiness_denominator",
                ),
                "false_positive_rate": self._false_positive_rate_kpi(),
                "missed_critical_rate": _ratio_kpi(
                    self._anomaly_outcomes["missed_critical"],
                    sum(self._anomaly_outcomes.values()),
                    reason="no_critical_outcome_denominator",
                ),
                "stale_inventory_detection_delay_seconds": _mean_kpi(
                    self._stale_inventory_delays_seconds,
                    reason="no_stale_inventory_delay_samples",
                    unit="seconds",
                ),
            },
            "behavior": self.behavior_snapshot(),
        }

    def bind_rule_generation_validation_handler(
        self,
        handler: RuleGenerationValidationHandler,
    ) -> None:
        """Bind the independent staged-generation validator."""

        if self._rule_generation_validation_handler is not None:
            raise RuntimeError("Heimdall Rule generation validator is already bound")
        self._rule_generation_validation_handler = handler

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if await self._alert_noise_message(topic, payload):
            return
        if topic == "object.action-run":
            await self._observe_action_run(payload)
        elif topic == RULE_GENERATION_BUILD_RESULT_TOPIC:
            await self._validate_rule_generation(payload)
        elif topic == "object.event" and not await self._forecast_context_message(payload):
            if payload.get("event_type") == "evidence.conflict.candidate.v1":
                await self._publish_evidence_conflict(payload)
                return
            if payload.get("event_type") == RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE:
                await self._publish_recovery_effect_observation(payload)
                return
            retrieval_validation = retrieval_validation_from_event(payload)
            if retrieval_validation is not None:
                await self._publish_retrieval_validation(retrieval_validation)
                return
            if str(payload.get("event_type") or "").startswith(SPECIALIST_EVENT_PREFIX):
                self.record_behavior("specialist_signal:deferred")
                return
            if payload.get("event_type") == _DETECTION_READINESS_EVENT:
                await self._observe_detection_readiness(payload)
                return
            if payload.get("event_type") == "forecast.evaluation_due":
                await self._run_forecast_tick(payload)
                return
            if str(payload.get("event_type") or "").startswith("control_plane.t2_proposer_"):
                await self._observe_t2_proposer_health(payload)
                return
            if (
                payload.get("kind") == "document_ingestion"
                and payload.get("event_type") == "document.inspected"
            ):
                await self._emit_document_safety_signal(payload)
                return
            await self._maybe_emit_anomaly(payload)
        elif topic == "object.chaos-experiment":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="chaos_experiment:invalid_producer",
            ):
                return
            await self._observe_chaos_experiment(payload)
        elif topic == "object.security-event":
            severity = await self._maybe_classify_severity(payload)
            if severity in ("high", "critical") and self._alerter_hook is not None:
                await self._maybe_send_admin_card(payload, severity)
        else:
            self.record_behavior("typed_message:ignored")

    async def _publish_evidence_conflict(self, payload: dict[str, Any]) -> None:
        """Validate one candidate and publish the authoritative immutable revision."""

        record = evidence_conflict_record(payload)
        if record is None:
            self.record_behavior("evidence_conflict:invalid_candidate")
            return
        if self.bus is None:
            raise RuntimeError("Heimdall evidence-conflict bus is unavailable")
        await self._publish_once("object.evidence-conflict", record)
        self.record_behavior(f"evidence_conflict:{record['status']}")

    async def _publish_recovery_effect_observation(self, payload: dict[str, Any]) -> None:
        """Relay one external recovery post-effect observation onto the owned topic.

        Heimdall is the terminal effect observer, so the independent observation
        enters through Huginn and leaves on a Heimdall-owned topic that the
        privileged executor can never publish to. The relay proves provenance
        and shape only; it verifies no effect and grants no authority.
        """

        record = recovery_effect_observation_record(payload)
        if record is None:
            self.record_behavior("recovery_effect_observation:invalid_signal")
            return
        if self.bus is None:
            raise RuntimeError("Heimdall recovery effect observation bus is unavailable")
        await self._publish_once("object.recovery-effect-observation", record)
        self.record_behavior("recovery_effect_observation:relayed")

    async def _publish_retrieval_validation(self, payload: dict[str, object]) -> None:
        self.record_behavior("semantic_retrieval_validation:accepted")
        if self.bus is None:
            raise RuntimeError("Heimdall retrieval validation bus is unavailable")
        await self._publish_once("object.retrieval-validation", payload)

    async def _validate_rule_generation(self, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Mimir":
            raise ValueError("Rule generation build result MUST be published by Mimir")
        build_result = RuleGenerationBuildResultEvent.model_validate(
            {
                field: payload[field]
                for field in RuleGenerationBuildResultEvent.model_fields
                if field in payload
            }
        )
        handler = self._rule_generation_validation_handler
        if handler is None:
            raise RuntimeError("Heimdall Rule generation validator is unavailable")
        try:
            async with asyncio.timeout(_RULE_VALIDATION_TIMEOUT_SECONDS):
                result = await handler.handle(build_result)
        except TimeoutError:
            self.record_behavior("rule_generation_validation:timeout")
            return
        if self.bus is None:
            raise RuntimeError("Heimdall retrieval validation bus is unavailable")
        result_payload = result.model_dump(mode="json")
        result_payload["correlation_id"] = build_result.request.correlation_id
        result_payload.setdefault(
            "idempotency_key",
            stable_idempotency_key(
                "rule-generation-validation",
                build_result.request.correlation_id,
                result_payload,
            ),
        )
        await self._publish_once("object.retrieval-validation", result_payload)
        self.record_behavior("rule_generation_validation:published")

    async def _observe_chaos_experiment(self, proposal: dict[str, Any]) -> None:
        kind = str(proposal.get("kind") or "chaos_experiment_proposal")
        if kind != "chaos_experiment_proposal":
            self.record_behavior("chaos_experiment:ignored_non_proposal_kind")
            return
        experiment_id = str(proposal.get("experiment_id") or "")
        action_type = str(proposal.get("action_type") or "")
        raw_targets = proposal.get("targets")
        targets: tuple[str, ...] = ()
        if isinstance(raw_targets, list) and 1 <= len(raw_targets) <= 32:
            targets = tuple(
                item.strip()
                for item in raw_targets
                if isinstance(item, str)
                and item.strip()
                and len(item.strip()) <= 512
                and not any(
                    (ord(char) < 32 and char not in "\t") or ord(char) == 127
                    for char in item.strip()
                )
            )
        if (
            not experiment_id
            or action_type not in CHAOS_ACTION_TYPES
            or not targets
            or len(targets) != len(raw_targets or ())
            or len(set(targets)) != len(targets)
        ):
            self.record_behavior("chaos_experiment:invalid")
            return
        evidence_fields = (
            "causal_hypothesis_ref",
            "refutation_query_ref",
            "impact_envelope_id",
            "recovery_plan_id",
            "dry_run_receipt",
        )
        evidence_complete = all(str(proposal.get(field) or "").strip() for field in evidence_fields)
        anomaly = {
            "producer_principal": "Heimdall",
            "correlation_id": str(proposal.get("correlation_id") or experiment_id),
            "idempotency_key": stable_idempotency_key(
                "chaos-experiment-anomaly",
                str(proposal.get("correlation_id") or experiment_id),
                experiment_id,
                action_type,
                targets,
            ),
            "resource_id": targets[0],
            "target_type": "experiment",
            "event_type": "chaos_experiment_request",
            "action_type": action_type,
            "severity": "high",
            "incident_correlation": "correlate",
            "initiator_principal": "Loki",
            "human_approval_required": True,
            "evidence_complete": evidence_complete,
            "params": {
                "experiment_id": experiment_id,
                "targets": list(targets),
                **{field: str(proposal.get(field) or "") for field in evidence_fields},
            },
        }
        self.record_behavior(
            "chaos_experiment:grounded" if evidence_complete else "chaos_experiment:incomplete"
        )
        if self.bus is None:
            self.record_behavior("chaos_experiment:publication_unavailable")
            return
        await self._publish_once("object.anomaly", anomaly)

    async def _publish_once(self, topic: str, payload: dict[str, Any]) -> bool:
        idempotency_key = str(payload.get("idempotency_key") or "")
        if not idempotency_key:
            raise ValueError("Heimdall publication requires an idempotency_key")
        publication_digest = hashlib.sha256(f"{topic}:{idempotency_key}".encode()).hexdigest()
        state_key = f"{_PUBLICATION_PREFIX}{publication_digest}"
        async with self._publication_lock(publication_digest):
            if self._state_store is not None:
                existing = await self._state_store.read_state(state_key)
                if existing is not None and existing.get("state") == "published":
                    self.record_behavior("publication:duplicate")
                    return False
                await self._state_store.write_state_if_absent(
                    state_key,
                    _publication_row(
                        topic=topic,
                        idempotency_key=idempotency_key,
                        payload=payload,
                        revision=1,
                        state="pending",
                    ),
                )
            if self.bus is None:
                return False
            bus = self.bus
            claim = await self._claim_publication(state_key, topic, idempotency_key, payload)
            return await publish_claimed_outbox(
                claim,
                publish=lambda: bus.publish("Heimdall", topic, payload),
                mark_published=lambda active_claim: self._mark_publication_published(
                    state_key,
                    topic,
                    idempotency_key,
                    payload,
                    active_claim,
                ),
                release=lambda active_claim: self._release_publication_claim(
                    state_key,
                    payload,
                    active_claim,
                ),
                lease=_PUBLICATION_CLAIM_LEASE,
            )

    async def recover_publications(self, *, limit: int = _PUBLICATION_RECOVERY_LIMIT) -> int:
        """Republish durable Heimdall publication intents left pending at restart."""

        if self._state_store is None or self.bus is None:
            return 0
        bus = self.bus
        recovered = 0
        attempted = 0
        attempted_keys: set[str] = set()
        while attempted < limit:
            remaining = limit - attempted
            pending_rows, _pending_total = await self._state_store.read_state_page(
                _PUBLICATION_PREFIX,
                limit=remaining,
                field="state",
                value="pending",
            )
            publishing_rows, _publishing_total = await self._state_store.read_state_page(
                _PUBLICATION_PREFIX,
                limit=remaining,
                field="state",
                value="publishing",
            )
            rows = (*pending_rows, *publishing_rows)
            if not rows:
                break
            progress = 0
            for row in reversed(rows[:remaining]):
                topic = str(row.get("topic") or "")
                payload = row.get("payload")
                if topic not in {
                    "object.anomaly",
                    "object.drift",
                    "object.evidence-conflict",
                    "object.recovery-effect-observation",
                    "object.retrieval-validation",
                } or not isinstance(payload, dict):
                    self.record_behavior("publication:recovery_invalid_row")
                    attempted += 1
                    continue
                idempotency_key = str(row.get("idempotency_key") or "")
                publication_digest = hashlib.sha256(
                    f"{topic}:{idempotency_key}".encode()
                ).hexdigest()
                state_key = f"{_PUBLICATION_PREFIX}{publication_digest}"
                if state_key in attempted_keys:
                    continue
                attempted_keys.add(state_key)
                attempted += 1
                claim = await self._claim_publication(state_key, topic, idempotency_key, payload)
                recovered_payload = dict(payload)

                async def mark_recovered(
                    active_claim: PublicationClaim,
                    *,
                    state_key: str = state_key,
                    topic: str = topic,
                    idempotency_key: str = idempotency_key,
                    payload: dict[str, Any] = recovered_payload,
                ) -> bool:
                    return await self._mark_publication_published(
                        state_key,
                        topic,
                        idempotency_key,
                        payload,
                        active_claim,
                    )

                async def release_recovered(
                    active_claim: PublicationClaim,
                    *,
                    state_key: str = state_key,
                    payload: dict[str, Any] = recovered_payload,
                ) -> None:
                    await self._release_publication_claim(
                        state_key,
                        payload,
                        active_claim,
                    )

                async def publish_recovered(
                    *,
                    topic: str = topic,
                    payload: dict[str, Any] = recovered_payload,
                ) -> None:
                    await bus.publish("Heimdall", topic, payload)

                try:
                    if await publish_claimed_outbox(
                        claim,
                        publish=publish_recovered,
                        mark_published=mark_recovered,
                        release=release_recovered,
                        lease=_PUBLICATION_CLAIM_LEASE,
                    ):
                        recovered += 1
                        progress += 1
                except Exception:
                    self.record_behavior("publication:recovery_publish_failed")
                    continue
            if progress == 0:
                break
        return recovered

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
        try:
            await self.recover_publications(limit=_PUBLICATION_MAINTENANCE_PAGE)
        except Exception:
            self.record_behavior("publication:maintenance_recovery_failed")

    async def _claim_publication(
        self,
        state_key: str,
        topic: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
    ) -> PublicationClaim | None:
        if self._state_store is None:
            return PublicationClaim(
                owner=new_publication_claim_owner(self.spec.name),
                claimed_at=self._forecast_clock().isoformat(),
            )
        for attempt in range(_PUBLICATION_CAS_ATTEMPTS):
            stored = await self._state_store.read_state(state_key)
            if stored is None:
                raise RuntimeError("Heimdall publication row disappeared")
            if stored.get("state") == "published":
                return None
            if stored.get("topic") != topic or stored.get("idempotency_key") != idempotency_key:
                raise RuntimeError("Heimdall publication row is malformed")
            if stored.get("payload") != dict(payload):
                raise RuntimeError("Heimdall publication payload identity conflict")
            now = self._forecast_clock()
            if stored.get("state") == "publishing" and not claim_expired(
                claimed_at=stored.get("claimed_at"),
                now=now,
                lease=_PUBLICATION_CLAIM_LEASE,
            ):
                return None
            if stored.get("state") not in {"pending", "publishing"}:
                raise RuntimeError("Heimdall publication row is malformed")
            revision = int(stored.get("revision", 1))
            claimed_at = now.isoformat()
            claim_owner = new_publication_claim_owner(self.spec.name)
            advanced = await self._state_store.compare_and_set_state(
                state_key,
                {
                    **dict(stored),
                    "revision": revision + 1,
                    "state": "publishing",
                    "claim_owner": claim_owner,
                    "claimed_at": claimed_at,
                },
                expected_revision=revision,
            )
            if advanced:
                return PublicationClaim(owner=claim_owner, claimed_at=claimed_at)
            await asyncio.sleep(0 if attempt == 0 else min(0.001 * attempt, 0.01))
        raise RuntimeError("Heimdall publication claim CAS retry limit exceeded")

    async def _mark_publication_published(
        self,
        state_key: str,
        topic: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
        claim: PublicationClaim,
    ) -> bool:
        if self._state_store is None:
            return True
        for attempt in range(_PUBLICATION_CAS_ATTEMPTS):
            stored = await self._state_store.read_state(state_key)
            if stored is None or stored.get("state") == "published":
                return False
            if (
                str(stored.get("claim_owner") or "") != claim.owner
                or str(stored.get("claimed_at") or "") != claim.claimed_at
            ):
                return False
            revision = int(stored.get("revision", 1))
            advanced = await self._state_store.compare_and_set_state(
                state_key,
                _publication_row(
                    topic=topic,
                    idempotency_key=idempotency_key,
                    payload=payload,
                    revision=revision + 1,
                    state="published",
                ),
                expected_revision=revision,
            )
            if advanced:
                return True
            await asyncio.sleep(0 if attempt == 0 else min(0.001 * attempt, 0.01))
        raise RuntimeError("Heimdall publication mark CAS retry limit exceeded")

    async def _release_publication_claim(
        self,
        state_key: str,
        payload: Mapping[str, Any],
        claim: PublicationClaim,
    ) -> None:
        if self._state_store is None:
            return
        for attempt in range(_PUBLICATION_CAS_ATTEMPTS):
            stored = await self._state_store.read_state(state_key)
            if stored is None or stored.get("state") != "publishing":
                return
            if stored.get("payload") != dict(payload):
                raise RuntimeError("Heimdall publication payload identity conflict")
            if (
                str(stored.get("claim_owner") or "") != claim.owner
                or str(stored.get("claimed_at") or "") != claim.claimed_at
            ):
                return
            revision = int(stored.get("revision", 1))
            advanced = await self._state_store.compare_and_set_state(
                state_key,
                {
                    **dict(stored),
                    "revision": revision + 1,
                    "state": "pending",
                    "claim_owner": "",
                    "claimed_at": "",
                },
                expected_revision=revision,
            )
            if advanced:
                return
            await asyncio.sleep(0 if attempt == 0 else min(0.001 * attempt, 0.01))
        raise RuntimeError("Heimdall publication release CAS retry limit exceeded")

    async def _persist_state(self) -> None:
        if self._state_store is None:
            return
        compact_episode_mode = len(self._recent_events) > _FULL_SNAPSHOT_LIMIT
        compact_readiness_mode = (
            len(self._detection_readiness) + len(self._detection_readiness_pending)
            > _FULL_SNAPSHOT_LIMIT
        )
        for episode_key in tuple(self._dirty_episode_keys):
            history = self._recent_events.get(episode_key)
            if history is None:
                continue
            await self._state_store.write_state(
                f"{_EPISODE_PREFIX}{_digest(_encode_episode_key(episode_key))}",
                {
                    "schema_version": "1.0.0",
                    "revision": len(history),
                    "episode_key": _encode_episode_key(episode_key),
                    "history": [
                        [timestamp, severity, evidence_key]
                        for timestamp, severity, evidence_key in history
                    ],
                },
            )
        for resource in tuple(self._dirty_readiness_resources):
            observations = self._detection_readiness.get(resource)
            if observations is None:
                continue
            pass_order = self._detection_readiness_pass_order.get(resource)
            await self._state_store.write_state(
                f"{_READINESS_PREFIX}{_digest(resource)}",
                {
                    "schema_version": "1.0.0",
                    "revision": 1,
                    "resource_id": resource,
                    "observations": {
                        dimension: observation.model_dump(mode="json")
                        for dimension, observation in observations.items()
                    },
                    "pass_order": (
                        [pass_order[0], pass_order[1].isoformat()]
                        if pass_order is not None
                        else None
                    ),
                },
            )
        for resource, pass_id in tuple(self._dirty_pending_readiness):
            observations = self._detection_readiness_pending.get((resource, pass_id))
            if observations is None:
                continue
            pending_identity = resource + "\0" + pass_id
            await self._state_store.write_state(
                f"{_PENDING_READINESS_PREFIX}{_digest(pending_identity)}",
                {
                    "schema_version": "1.0.0",
                    "revision": len(observations),
                    "resource_id": resource,
                    "pass_id": pass_id,
                    "observations": {
                        dimension: observation.model_dump(mode="json")
                        for dimension, observation in observations.items()
                    },
                },
            )
        await self._state_store.write_state(
            _STATE_KEY,
            {
                "schema_version": "1.0.0",
                "revision": 1,
                "recent_events": {}
                if compact_episode_mode
                else {
                    _encode_episode_key(key): [
                        [timestamp, severity, evidence_key]
                        for timestamp, severity, evidence_key in history
                    ]
                    for key, history in self._recent_events.items()
                },
                "incident_episode_ids": {
                    _encode_episode_key(key): value
                    for key, value in self._incident_episode_ids.items()
                },
                "incident_episode_severities": {
                    _encode_episode_key(key): value
                    for key, value in self._incident_episode_severities.items()
                },
                "security_recent": list(self._security_recent),
                "alert_windows": {
                    key: [start, count] for key, (start, count) in self._alert_windows.items()
                },
                "detection_readiness": {}
                if compact_readiness_mode
                else {
                    resource: {
                        dimension: observation.model_dump(mode="json")
                        for dimension, observation in observations.items()
                    }
                    for resource, observations in self._detection_readiness.items()
                },
                "detection_readiness_pending": {}
                if compact_readiness_mode
                else {
                    f"{resource}\0{pass_id}": {
                        dimension: observation.model_dump(mode="json")
                        for dimension, observation in observations.items()
                    }
                    for (
                        resource,
                        pass_id,
                    ), observations in self._detection_readiness_pending.items()
                },
                "detection_readiness_pass_order": {}
                if compact_readiness_mode
                else {
                    resource: [pass_id, observed_at.isoformat()]
                    for resource, (
                        pass_id,
                        observed_at,
                    ) in self._detection_readiness_pass_order.items()
                },
            },
        )
        self._dirty_episode_keys.clear()
        self._dirty_readiness_resources.clear()
        self._dirty_pending_readiness.clear()

    async def _observe_t2_proposer_health(self, event: dict[str, Any]) -> None:
        """Reduce one sanitized proposer receipt without another model call."""

        attributes = event.get("attributes")
        if not isinstance(attributes, dict):
            self.record_behavior("t2_proposer:invalid")
            return
        recovered = (
            event.get("event_type") == "control_plane.t2_proposer_recovered"
            and attributes.get("status") == "succeeded"
            and attributes.get("recovered") is True
        )
        if recovered:
            self.record_behavior("t2_proposer:recovered")
            return
        terminal = attributes.get("terminal") is True and attributes.get("status") == "failed"
        if not terminal:
            self.record_behavior("t2_proposer:degraded")
            return
        correlation_id = str(event.get("correlation_id") or "")
        resource_id = str(event.get("resource_id") or "")
        evidence_key = str(event.get("idempotency_key") or event.get("event_id") or "")
        if not correlation_id or not resource_id or not evidence_key:
            self.record_behavior("t2_proposer:invalid")
            return
        preferred_route = str(attributes.get("preferred_route_ref") or "")
        if preferred_route == "legacy":
            preferred_route = "primary"
        if preferred_route not in {"primary", "secondary"}:
            self.record_behavior("t2_proposer:invalid_route_hint")
            return
        alternate_route = (
            "secondary"
            if preferred_route == "primary"
            else "primary"
            if preferred_route == "secondary"
            else ""
        )
        anomaly = {
            "producer_principal": "Heimdall",
            "correlation_id": correlation_id,
            "idempotency_key": stable_idempotency_key(
                "t2-proposer-anomaly",
                correlation_id,
                resource_id,
                evidence_key,
                attributes.get("failure_class"),
            ),
            "resource_id": resource_id,
            "target_type": "llm-endpoint",
            "event_type": "control_plane.t2_proposer_failure",
            "severity": "high",
            "incident_correlation": "correlate",
            "reason_code": "t2_proposer_candidates_exhausted",
            "evidence_key": evidence_key,
            "evidence_keys": [evidence_key],
            "failure_class": str(attributes.get("failure_class") or "provider_error"),
            "prior_route_ref": preferred_route,
            "alternate_route_ref": alternate_route,
        }
        self.record_behavior("t2_proposer:unavailable")
        if self.bus is not None:
            await self.bus.publish("Heimdall", "object.anomaly", anomaly)
        if self._incident_candidate_hook is None:
            self.record_behavior("incident_candidate_hook:unavailable")
            return
        try:
            accepted = await self._incident_candidate_hook(anomaly)
        except Exception:  # noqa: BLE001 - next receipt retries the durable candidate
            self.record_behavior("t2_proposer:incident_failed")
            return
        self.record_behavior(
            "t2_proposer:incident_opened" if accepted else "t2_proposer:incident_held"
        )

    async def _observe_detection_readiness(self, event: dict[str, Any]) -> None:
        """Validate one probe fact and publish the agent-owned reduction."""
        resource_id = str(event.get("resource_id") or "")
        attributes = event.get("attributes")
        pass_id = str(attributes.get("pass_id") or "") if isinstance(attributes, dict) else ""
        if not resource_id or not pass_id or not isinstance(attributes, dict):
            self.record_behavior("detection_readiness:invalid")
            return
        try:
            observation = DetectionReadinessObservation.model_validate(
                {
                    "resource_ref": resource_id,
                    "dimension": attributes.get("dimension"),
                    "status": attributes.get("status"),
                    "observed_at": attributes.get("observed_at"),
                    "expires_at": attributes.get("expires_at"),
                    "source": attributes.get("source"),
                    "evidence_digest": attributes.get("evidence_digest"),
                    "detail_code": attributes.get("detail_code") or None,
                }
            )
        except ValueError:
            self.record_behavior("detection_readiness:invalid")
            return

        pending_key = (resource_id, pass_id)
        observations = self._detection_readiness_pending.setdefault(pending_key, {})
        _evict_oldest(self._detection_readiness_pending, _MAX_TRACKED_KEYS, keep=pending_key)
        observations[observation.dimension.value] = observation
        self._readiness_observed_dimensions += 1
        self._readiness_expected_dimensions += len(DetectionReadinessDimension)
        self._dirty_pending_readiness.add(pending_key)
        if len(observations) != len(DetectionReadinessDimension):
            await self._persist_state()
            self.record_behavior("detection_readiness:collecting")
            return
        latest_pass = self._detection_readiness_pass_order.get(resource_id)
        pass_observed_at = max(item.observed_at for item in observations.values())
        now = self._forecast_clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Heimdall forecast clock MUST be timezone-aware")
        stale_delay = max(
            0.0,
            (now - min(item.observed_at for item in observations.values())).total_seconds(),
        )
        self._stale_inventory_delays_seconds.append(stale_delay)
        if latest_pass is not None and pass_observed_at <= latest_pass[1]:
            self._detection_readiness_pending.pop(pending_key, None)
            await self._persist_state()
            self.record_behavior("detection_readiness:stale_pass")
            return
        self._detection_readiness[resource_id] = dict(observations)
        self._detection_readiness_pass_order[resource_id] = (pass_id, pass_observed_at)
        self._dirty_readiness_resources.add(resource_id)
        _evict_oldest(self._detection_readiness, _MAX_TRACKED_KEYS, keep=resource_id)
        del self._detection_readiness_pending[pending_key]
        snapshot = reduce_detection_readiness(
            tuple(observations.values()),
            resource_ref=resource_id,
            generated_at=self._forecast_clock(),
            deployment_ceiling=AuthorityCeiling.SHADOW,
        )
        await self._publish_detection_readiness(event, snapshot, pass_id=pass_id)
        await self._persist_state()

    async def _publish_detection_readiness(
        self,
        event: dict[str, Any],
        snapshot: DetectionReadinessSnapshot,
        *,
        pass_id: str,
    ) -> None:
        material = {
            "resource_ref": snapshot.resource_ref,
            "decision": snapshot.decision.value,
            "authority_ceiling": snapshot.authority_ceiling.value,
            "observations": [
                {
                    "dimension": item.dimension.value,
                    "status": item.status.value,
                    "evidence_digest": item.evidence_digest,
                    "expires_at": item.expires_at.isoformat(),
                }
                for item in snapshot.observations
            ],
            "missing_dimensions": [item.value for item in snapshot.missing_dimensions],
            "stale_dimensions": [item.value for item in snapshot.stale_dimensions],
        }
        digest = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        generated_at = snapshot.generated_at.isoformat()
        idempotency_key = stable_idempotency_key(
            "detection-readiness",
            snapshot.resource_ref,
            pass_id,
            generated_at,
            digest,
        )
        payload = {
            "producer_principal": "Heimdall",
            "kind": "detection_readiness",
            "event_type": "detection.readiness",
            "correlation_id": str(event.get("correlation_id") or idempotency_key),
            "idempotency_key": idempotency_key,
            "resource_id": snapshot.resource_ref,
            "target_type": "kubernetes-cluster",
            "pass_id": pass_id,
            "content_digest": digest,
            "decision": snapshot.decision.value,
            "readiness_status": "stale" if snapshot.stale_dimensions else snapshot.decision.value,
            "authority_ceiling": snapshot.authority_ceiling.value,
            "generated_at": generated_at,
            "observations": [item.model_dump(mode="json") for item in snapshot.observations],
            "missing_dimensions": [item.value for item in snapshot.missing_dimensions],
            "stale_dimensions": [item.value for item in snapshot.stale_dimensions],
        }
        self.record_behavior(f"detection_readiness:{snapshot.decision.value}")
        if self.bus is not None:
            await self._publish_once("object.drift", payload)

    async def _emit_document_safety_signal(self, event: dict[str, Any]) -> None:
        """Normalize scanner/protection facts without making the verdict."""
        record = event.get("record")
        if not isinstance(record, dict):
            record = {}
        malware_verdict = str(record.get("malware_verdict") or "unavailable")
        protection_state = str(record.get("protection_state") or "unknown")
        failure_code = str(record.get("failure_code") or "")
        safety_status = (
            "clear"
            if malware_verdict == "clean"
            and not failure_code
            and protection_state in {"none", "labeled_unencrypted", "rights_managed_accessible"}
            else "blocked"
        )
        signal = {
            "producer_principal": "Heimdall",
            "kind": "document_ingestion",
            "stage": "protection_check",
            "correlation_id": str(event.get("correlation_id") or ""),
            "idempotency_key": str(event.get("idempotency_key") or ""),
            "resource_id": str(event.get("resource_id") or ""),
            "document_id": str(event.get("document_id") or ""),
            "upload_id": str(record.get("upload_id") or ""),
            "malware_verdict": malware_verdict,
            "protection_state": protection_state,
            "sensitivity_label": str(record.get("sensitivity_label") or ""),
            "purposes": list(record.get("purposes") or []),
            "initiator_principal": str(record.get("uploader_id") or ""),
            "failure_code": failure_code,
            "safety_status": safety_status,
        }
        self.record_behavior(f"document_safety:{safety_status}")
        if self.bus is not None:
            await self.bus.publish("Heimdall", "object.anomaly", signal)

    async def _maybe_emit_anomaly(self, event: dict[str, Any]) -> None:
        resource_id = str(event.get("resource_id") or "")
        if not resource_id:
            self.record_behavior("anomaly_event:missing_resource")
            return
        event_type = str(event.get("event_type", "generic"))
        correlation_id = str(event.get("correlation_id") or "").strip()
        incident_correlation = (
            str(event.get("incident_correlation") or "correlate").strip().casefold()
        )
        time_basis, observed_at = _event_window_time(event, fallback=self._clock())
        episode_key = (
            resource_id,
            event_type,
            correlation_id,
            incident_correlation,
            time_basis,
        )
        history = self._episode_history(episode_key)
        self._dirty_episode_keys.add(episode_key)
        watermark = max(observed_at, history[-1][0] if history else observed_at)
        while history and watermark - history[0][0] > self._rate_window:
            history.popleft()
        if not history:
            self._incident_episode_ids.pop(episode_key, None)
            self._incident_episode_severities.pop(episode_key, None)
        if observed_at < watermark - self._rate_window:
            self.record_behavior("repeated_event_out_of_window")
            await self._persist_state()
            return
        evidence_key = str(event.get("idempotency_key") or event.get("event_id") or "").strip()
        if evidence_key and any(item[2] == evidence_key for item in history):
            self.record_behavior("repeated_event_duplicate")
            if len(history) < self._rate_threshold:
                await self._persist_state()
                return
        else:
            history.append(
                (
                    observed_at,
                    _event_severity(event),
                    evidence_key,
                )
            )
            history = deque(
                sorted(history, key=lambda item: (item[0], item[2])),
                maxlen=self._rate_threshold * 2,
            )
            self._recent_events[episode_key] = history
        if len(history) < self._rate_threshold:
            await self._persist_state()
            self.record_behavior("anomaly_window:collecting")
            return
        window_tail = list(history)[-self._rate_threshold :]
        if len(window_tail) == self._rate_threshold:
            severity = min(
                (event_severity for _, event_severity, _ in window_tail),
                key=_SEVERITY_RANK.__getitem__,
            )
            emitted_severity = self._incident_episode_severities.get(episode_key)
            if (
                emitted_severity is not None
                and _SEVERITY_RANK[severity] >= _SEVERITY_RANK[emitted_severity]
            ):
                self.record_behavior("anomaly_episode:suppressed_duplicate_severity")
                await self._persist_state()
                return
            if not correlation_id:
                self.record_behavior("incident_candidate_missing_correlation")
                self._drop_episode(episode_key)
                return
            incident_episode_id = self._incident_episode_ids.setdefault(
                episode_key,
                _incident_episode_id(episode_key, window_tail[0][2]),
            )
            anomaly = {
                "producer_principal": "Heimdall",
                "correlation_id": correlation_id,
                "idempotency_key": _anomaly_idempotency_key(
                    incident_episode_id,
                    severity,
                ),
                "resource_id": resource_id,
                "target_type": str(event.get("resource_type") or "unknown"),
                "event_type": event_type,
                "count_in_window": self._rate_threshold,
                "severity": severity,
                "incident_correlation": incident_correlation,
            }
            operational_evidence = await self._collect_operational_evidence(event)
            if operational_evidence:
                anomaly["operational_evidence"] = operational_evidence
            trace_continuity = _trace_continuity_evidence(event)
            if trace_continuity:
                anomaly["trace_continuity"] = trace_continuity
            if self.bus is not None:
                await self._publish_once("object.anomaly", anomaly)
            if self._incident_candidate_hook is None:
                self._drop_episode(episode_key)
                return
            if incident_correlation in _INCIDENT_CORRELATION_DISABLED:
                self.record_behavior("incident_candidate_correlation_disabled")
                self._drop_episode(episode_key)
                return
            if not correlation_id:
                self.record_behavior("incident_candidate_missing_correlation")
                self._drop_episode(episode_key)
                return
            if any(not evidence_key for _, _, evidence_key in window_tail):
                self.record_behavior("incident_candidate_missing_evidence")
                self._drop_episode(episode_key)
                return
            evidence_keys = tuple(dict.fromkeys(evidence_key for _, _, evidence_key in window_tail))
            reason_code = "repeated_event_threshold"
            trace_reason = trace_continuity.get("reason_code")
            if isinstance(trace_reason, str) and trace_reason in _TRACE_CONTINUITY_REASONS:
                reason_code = trace_reason
            candidate = {
                **anomaly,
                "reason_code": reason_code,
                "evidence_key": evidence_keys[-1],
                "evidence_keys": evidence_keys,
                "incident_episode_id": incident_episode_id,
            }
            try:
                accepted = await self._incident_candidate_hook(candidate)
            except Exception:  # noqa: BLE001 - retry on the next matching event
                self.record_behavior("incident_candidate_failed")
                _LOG.exception(
                    "incident_candidate_hook_failed",
                    extra={"correlation_id": anomaly["correlation_id"]},
                )
                return
            if accepted:
                self._incident_episode_severities[episode_key] = severity
                await self._persist_state()
            else:
                self._drop_episode(episode_key)
                await self._persist_state()
            self.record_behavior("incident_candidate" if accepted else "incident_candidate_held")

    async def _collect_operational_evidence(
        self,
        event: dict[str, Any],
    ) -> Mapping[str, Any]:
        if self._operational_evidence_hook is None:
            return {}
        try:
            evidence = await self._operational_evidence_hook(event)
        except Exception:  # noqa: BLE001 - evidence loss cannot suppress the anomaly
            self.record_behavior("operational_evidence:provider_error")
            return {
                "observe.kubernetes.capacity": {
                    "status": "unavailable",
                    "reason": "provider_error",
                }
            }
        self.record_behavior(
            "operational_evidence:available" if evidence else "operational_evidence:not_applicable"
        )
        return evidence

    def _anomaly_precision_kpi(self) -> dict[str, Any]:
        true_positive = self._anomaly_outcomes["true_positive"]
        false_positive = self._anomaly_outcomes["false_positive"]
        return _ratio_kpi(
            true_positive,
            true_positive + false_positive,
            reason="no_precision_outcome_denominator",
        )

    def _anomaly_recall_kpi(self) -> dict[str, Any]:
        true_positive = self._anomaly_outcomes["true_positive"]
        false_negative = self._anomaly_outcomes["false_negative"]
        return _ratio_kpi(
            true_positive,
            true_positive + false_negative,
            reason="no_recall_outcome_denominator",
        )

    def _false_positive_rate_kpi(self) -> dict[str, Any]:
        true_positive = self._anomaly_outcomes["true_positive"]
        false_positive = self._anomaly_outcomes["false_positive"]
        return _ratio_kpi(
            false_positive,
            true_positive + false_positive,
            reason="no_false_positive_denominator",
        )

    def _forecast_mape_kpi(self) -> dict[str, Any]:
        return _mean_kpi(
            self._forecast_absolute_percentage_errors,
            reason="no_forecast_error_samples",
            unit="percent",
        )

    async def _maybe_classify_severity(self, event: dict[str, Any]) -> str:
        self._security_recent.append(event)
        initiator = str(event.get("initiator_principal", ""))
        action = str(event.get("attempted_action", ""))
        hint = str(event.get("severity_hint", "medium"))

        matches = sum(
            1
            for e in self._security_recent
            if e.get("initiator_principal") == initiator and e.get("attempted_action") == action
        )
        severity: str
        if hint == "critical" or is_irreversible(action, self._action_semantics):
            severity = "high"
        elif matches >= self._security_high_threshold:
            severity = "high"
        elif matches >= 3:
            severity = "medium"
        else:
            severity = "low"
        distinct_actions = len(
            {
                e.get("attempted_action")
                for e in self._security_recent
                if e.get("initiator_principal") == initiator
            }
        )
        if distinct_actions >= 3:
            severity = "critical"
        self._alert_counters[(initiator, action)] += 1
        _evict_oldest(self._alert_counters, _MAX_TRACKED_KEYS, keep=(initiator, action))
        await self._persist_state()
        return severity

    async def _maybe_send_admin_card(self, event: dict[str, Any], severity: str) -> None:
        """Send an admin card, deduped by (initiator, action) within window."""
        initiator = str(event.get("initiator_principal", ""))
        action = str(event.get("attempted_action", ""))
        # Rate limit per user, per rolling hour (recovers when the window
        # rolls over - a monotonic counter would silence the user forever).
        if not self._reserve_alert_slot(initiator):
            await self._persist_state()
            return
        await self._persist_state()
        # Dedup: send one card per (initiator, action); repeat becomes
        # counter increment on the last card (handled by Var adapter).
        payload = {
            "producer_principal": "Var",
            "correlation_id": event.get("correlation_id", ""),
            "severity": severity,
            "initiator_principal": initiator,
            "attempted_action": action,
            "counter": self._alert_counters[(initiator, action)],
        }
        if self._alerter_hook is None:
            return
        await self._alerter_hook(payload)

    @asynccontextmanager
    async def _publication_lock(self, publication_digest: str) -> AsyncIterator[None]:
        lock = self._lock_for_publication(publication_digest)
        self._publication_lock_refs[publication_digest] = (
            self._publication_lock_refs.get(publication_digest, 0) + 1
        )
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            remaining = self._publication_lock_refs.get(publication_digest, 1) - 1
            if remaining > 0:
                self._publication_lock_refs[publication_digest] = remaining
            else:
                self._publication_lock_refs.pop(publication_digest, None)
                self._publication_locks.pop(publication_digest, None)

    def _lock_for_publication(self, publication_digest: str) -> asyncio.Lock:
        lock = self._publication_locks.get(publication_digest)
        if lock is None:
            lock = asyncio.Lock()
            self._publication_locks[publication_digest] = lock
        return lock

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Observation answers rest on a populated window of signals.

        A bound read-investigation hook is its own evidence source, so it
        keeps the turn grounded even before the local window fills.
        """
        return bool(self._recent_events or self._security_recent or self._read_investigation_hook)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        if self._read_investigation_hook is not None:
            investigation = await self._read_investigation_hook(question, context)
            if investigation is not None:
                answer = investigation.get("answer")
                facts = investigation.get("facts")
                if not isinstance(answer, str) or not isinstance(facts, dict):
                    raise ValueError("read investigation hook returned an invalid response")
                return IntrospectionResult(answer=answer, facts=facts)
        facts = {
            **capability_facts(self.spec),
            "watched_resources": capped_list(
                sorted({episode_key[0] for episode_key in self._recent_events})
            ),
            "watched_resources_count": len({episode_key[0] for episode_key in self._recent_events}),
            "security_events_window": len(self._security_recent),
            "rate_threshold": self._rate_threshold,
            "rate_window_seconds": self._rate_window,
            "forecast_evidence_available": False,
            "drift_evidence_available": False,
            "resource_id": None,
            "recent_event_count": None,
            "recent_event_types": [],
        }
        intents = semantic_intents(context)
        if "forecast" in intents:
            return evidence_backed_result(
                self.spec.name,
                facts,
                "No retained forecast episode is bound to this conversational projection",
            )
        if "drift" in intents:
            return evidence_backed_result(
                self.spec.name,
                facts,
                "No retained drift finding is bound to this conversational projection",
            )
        resources = mentioned(
            question,
            {episode_key[0] for episode_key in self._recent_events},
        )
        if resources:
            rid = resources[0]
            history = [
                item
                for episode_key, episode_history in self._recent_events.items()
                if episode_key[0] == rid
                for item in episode_history
            ]
            event_types = sorted(
                {episode_key[1] for episode_key in self._recent_events if episode_key[0] == rid}
            )
            facts.update(
                {
                    "resource_id": rid,
                    "recent_event_count": len(history),
                    "recent_event_types": event_types,
                }
            )
            evidence_ref = attach_agent_state_evidence(self.spec.name, facts)
            answer = (
                f"Resource {rid!r}: {len(history)} recent event(s), "
                f"type(s): {', '.join(event_types) or 'none'}. Evidence: {evidence_ref}."
            )
            return IntrospectionResult(answer=answer, facts=facts)
        evidence_ref = attach_agent_state_evidence(self.spec.name, facts)
        answer = heimdall_role_answer(str(context.get("locale")), facts, evidence_ref)
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = [
    "Heimdall",
    "ActionObservationHook",
    "AlerterHook",
    "IncidentCandidateHook",
    "ReadInvestigationHook",
]


def _encode_episode_key(key: _EpisodeKey) -> str:
    return json.dumps(key, ensure_ascii=True, separators=(",", ":"))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _payload_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _publication_row(
    *,
    topic: str,
    idempotency_key: str,
    payload: Mapping[str, Any],
    revision: int,
    state: str,
) -> dict[str, Any]:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    row: dict[str, Any] = {
        "schema_version": "1.0.0",
        "revision": revision,
        "state": state,
        "topic": topic,
        "idempotency_key": idempotency_key,
        "payload_digest": "sha256:" + hashlib.sha256(encoded).hexdigest(),
    }
    if len(encoded) <= _PUBLICATION_REPLAY_PAYLOAD_MAX_BYTES:
        row["payload"] = dict(payload)
    return row


def _decode_episode_key(value: object) -> _EpisodeKey | None:
    if not isinstance(value, str):
        return None
    try:
        decoded = json.loads(value)
    except ValueError:
        return None
    if (
        isinstance(decoded, list)
        and len(decoded) == 5
        and all(isinstance(item, str) for item in decoded)
    ):
        return (decoded[0], decoded[1], decoded[2], decoded[3], decoded[4])
    return None


def _decode_readiness_map(value: object) -> dict[str, dict[str, DetectionReadinessObservation]]:
    if not isinstance(value, Mapping):
        return {}
    restored: dict[str, dict[str, DetectionReadinessObservation]] = {}
    for resource, raw_observations in value.items():
        if not isinstance(resource, str) or not isinstance(raw_observations, Mapping):
            continue
        observations: dict[str, DetectionReadinessObservation] = {}
        for dimension, raw_observation in raw_observations.items():
            if not isinstance(dimension, str) or not isinstance(raw_observation, Mapping):
                continue
            try:
                observations[dimension] = DetectionReadinessObservation.model_validate(
                    raw_observation
                )
            except ValueError:
                continue
        if observations:
            restored[resource] = observations
    return restored


def _decode_pending_readiness(
    value: object,
) -> dict[tuple[str, str], dict[str, DetectionReadinessObservation]]:
    if not isinstance(value, Mapping):
        return {}
    restored: dict[tuple[str, str], dict[str, DetectionReadinessObservation]] = {}
    for raw_key, raw_observations in value.items():
        if not isinstance(raw_key, str) or "\0" not in raw_key:
            continue
        resource, pass_id = raw_key.split("\0", 1)
        decoded = _decode_readiness_map({resource: raw_observations}).get(resource)
        if decoded:
            restored[(resource, pass_id)] = decoded
    return restored
