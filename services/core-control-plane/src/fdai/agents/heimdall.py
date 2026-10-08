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
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fdai.agents._framework import heimdall_alert_window as _heimdall_alert_window
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
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
from fdai.agents._framework.heimdall_anomaly_runtime import HeimdallAnomalyRuntimeMixin
from fdai.agents._framework.heimdall_code_security import (
    DRIFT_TOOL_ID,
    HeimdallCodeSecurityMixin,
    code_security_statement,
)
from fdai.agents._framework.heimdall_constants import (
    _DETECTION_READINESS_EVENT as _DETECTION_READINESS_EVENT,
)
from fdai.agents._framework.heimdall_constants import (
    _EPISODE_PREFIX as _EPISODE_PREFIX,
)
from fdai.agents._framework.heimdall_constants import (
    _FULL_SNAPSHOT_LIMIT as _FULL_SNAPSHOT_LIMIT,
)
from fdai.agents._framework.heimdall_constants import (
    _INCIDENT_CORRELATION_DISABLED as _INCIDENT_CORRELATION_DISABLED,
)
from fdai.agents._framework.heimdall_constants import (
    _MAX_KPI_SAMPLES as _MAX_KPI_SAMPLES,
)
from fdai.agents._framework.heimdall_constants import (
    _PENDING_READINESS_PREFIX as _PENDING_READINESS_PREFIX,
)
from fdai.agents._framework.heimdall_constants import (
    _PUBLICATION_CAS_ATTEMPTS as _PUBLICATION_CAS_ATTEMPTS,
)
from fdai.agents._framework.heimdall_constants import (
    _PUBLICATION_CLAIM_LEASE as _PUBLICATION_CLAIM_LEASE,
)
from fdai.agents._framework.heimdall_constants import (
    _PUBLICATION_MAINTENANCE_PAGE as _PUBLICATION_MAINTENANCE_PAGE,
)
from fdai.agents._framework.heimdall_constants import (
    _PUBLICATION_PREFIX as _PUBLICATION_PREFIX,
)
from fdai.agents._framework.heimdall_constants import (
    _PUBLICATION_RECOVERY_LIMIT as _PUBLICATION_RECOVERY_LIMIT,
)
from fdai.agents._framework.heimdall_constants import (
    _PUBLICATION_REPLAY_PAYLOAD_MAX_BYTES as _PUBLICATION_REPLAY_PAYLOAD_MAX_BYTES,
)
from fdai.agents._framework.heimdall_constants import (
    _READINESS_PREFIX as _READINESS_PREFIX,
)
from fdai.agents._framework.heimdall_constants import (
    _RULE_VALIDATION_TIMEOUT_SECONDS as _RULE_VALIDATION_TIMEOUT_SECONDS,
)
from fdai.agents._framework.heimdall_constants import (
    _SEVERITY_RANK as _SEVERITY_RANK,
)
from fdai.agents._framework.heimdall_constants import (
    _STATE_KEY as _STATE_KEY,
)
from fdai.agents._framework.heimdall_forecast import HeimdallForecastMixin
from fdai.agents._framework.heimdall_provider_schema import HeimdallProviderSchemaMixin
from fdai.agents._framework.heimdall_publication_runtime import HeimdallPublicationRuntimeMixin
from fdai.agents._framework.heimdall_readiness_runtime import HeimdallReadinessRuntimeMixin
from fdai.agents._framework.heimdall_state_recovery import HeimdallStateRecoveryMixin
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    attach_agent_state_evidence,
    capability_facts,
    capped_list,
    evidence_backed_result,
    mentioned,
    semantic_intents,
)
from fdai.agents._framework.pantheon import _HEIMDALL
from fdai.agents._framework.role_answers import heimdall_role_answer
from fdai.core.detection.forecast_closure import ForecastClosureCoordinator
from fdai.core.detection.forecast_episode import ForecastEpisodeStore
from fdai.core.detection.forecast_evaluation import ForecastEpisodeEvaluator
from fdai.core.readiness import (
    DetectionReadinessObservation,
)
from fdai.core.rule_semantic_generation import RuleGenerationValidationHandler
from fdai.shared.providers.code_security import CodeSecurityDriftProjector
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
    HeimdallCodeSecurityMixin,
    HeimdallForecastMixin,
    HeimdallStateRecoveryMixin,
    HeimdallPublicationRuntimeMixin,
    HeimdallReadinessRuntimeMixin,
    HeimdallAnomalyRuntimeMixin,
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
        code_security_drift_projector: CodeSecurityDriftProjector | None = None,
        state_store: StateStore | None = None,
    ) -> None:
        if rate_threshold < 1:
            raise ValueError("rate_threshold MUST be >= 1")
        if rate_window < 1:
            raise ValueError("rate_window MUST be >= 1")
        super().__init__(spec=_HEIMDALL)
        self.bus = bus
        self._provider_schema_drift_projector = provider_schema_drift_projector
        self._code_security_drift_projector = code_security_drift_projector
        self._state_store = state_store
        self._rate_threshold = rate_threshold
        self._rate_window = rate_window
        self._max_tracked_keys = _heimdall_alert_window.MAX_TRACKED_KEYS
        self._max_episodes_per_resource = _heimdall_alert_window.MAX_EPISODES_PER_RESOURCE
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
        if "drift" in intents or context.get("conversation_tool") == DRIFT_TOOL_ID:
            # Code-security scan reviews are Heimdall-owned Drift recorded by the scan worker.
            code_facts = await self.code_security_facts()
            if code_facts is None:
                return evidence_backed_result(
                    self.spec.name,
                    facts,
                    "No retained drift finding is bound to this conversational projection",
                )
            facts.update(code_facts)
            return evidence_backed_result(
                self.spec.name,
                facts,
                "No retained configuration drift finding is bound to this conversational "
                f"projection. {code_security_statement(code_facts)}",
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
    "_MAX_EPISODES_PER_RESOURCE",
    "_MAX_TRACKED_KEYS",
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
