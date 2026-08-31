"""Fail-closed projection of shadow WARA assessment events for Operator reads."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Protocol, runtime_checkable

from fdai_service_contracts.wara_assessment import (
    WARA_ASSESSMENT_CONSUMER_GROUP,
    WARA_ASSESSMENT_TOPIC,
)

_LOGGER = logging.getLogger(__name__)


class WaraProjectionError(ValueError):
    """A WARA event cannot be admitted to the Operator projection."""


def project_wara_assessment(
    catalog_projection: Mapping[str, object],
    assessment: Mapping[str, object],
) -> dict[str, object]:
    """Merge one complete no-authority shadow result into the catalog lifecycle."""

    if assessment.get("mode") != "shadow" or assessment.get("execution_authority") is not False:
        raise WaraProjectionError("WARA projection requires a no-authority shadow assessment")
    controls_value = catalog_projection.get("controls")
    results_value = assessment.get("controls")
    if not isinstance(controls_value, list) or not all(
        isinstance(item, dict) for item in controls_value
    ):
        raise WaraProjectionError("WARA catalog projection is malformed")
    if not isinstance(results_value, list) or not all(
        isinstance(item, dict) for item in results_value
    ):
        raise WaraProjectionError("WARA assessment controls are malformed")
    controls = {str(item.get("id")): dict(item) for item in controls_value}
    active_ids = {
        control_id for control_id, item in controls.items() if item.get("lifecycle") == "active"
    }
    results = {str(item.get("recommendation_id")): item for item in results_value}
    if len(results) != len(results_value) or set(results) != active_ids:
        raise WaraProjectionError("WARA assessment MUST exactly cover active recommendations")
    if assessment.get("framework_revision") != catalog_projection.get("source_revision"):
        raise WaraProjectionError("WARA assessment source revision mismatch")
    if assessment.get("crosswalk_digest") != catalog_projection.get("crosswalk_digest"):
        raise WaraProjectionError("WARA assessment crosswalk digest mismatch")
    scope_digest = _text(assessment.get("scope_digest"), "scope_digest")
    evaluated_at = _text(assessment.get("evaluated_at"), "evaluated_at")
    for recommendation_id, result in results.items():
        applicability = _member(
            result.get("applicability"),
            {"applicable", "not_applicable", "unknown"},
            "applicability",
        )
        evaluation = _member(
            result.get("evaluation"),
            {"evaluated", "not_evaluated", "blocked"},
            "evaluation",
        )
        satisfaction = _member(
            result.get("satisfaction"),
            {"satisfied", "failed", "not_applicable", "unknown"},
            "satisfaction",
        )
        evidence_refs = _strings(result.get("evidence_refs"), "evidence_refs")
        evidence_digests = _strings(result.get("evidence_digests"), "evidence_digests")
        limitations = _strings(result.get("limitations"), "limitations")
        evidence_complete = result.get("evidence_complete")
        if not isinstance(evidence_complete, bool):
            raise WaraProjectionError("WARA evidence_complete MUST be boolean")
        if evaluation != "evaluated" and (
            evidence_complete or satisfaction in {"satisfied", "failed", "not_applicable"}
        ):
            raise WaraProjectionError("unevaluated WARA result cannot claim complete satisfaction")
        controls[recommendation_id].update(
            {
                "mapping_state": _member(
                    result.get("mapping_state"),
                    {"full", "partial", "unmapped"},
                    "mapping_state",
                ),
                "applicability": applicability,
                "evaluation_status": evaluation,
                "satisfaction": satisfaction,
                "evaluation_scope": scope_digest,
                "evaluated_at": evaluated_at,
                "evidence_complete": evidence_complete,
                "evidence_refs": evidence_refs,
                "evidence_digests": evidence_digests,
                "limitations": limitations,
                "execution_authority": False,
            }
        )
    return {
        **dict(catalog_projection),
        "_revision": _text(assessment.get("result_digest"), "result_digest"),
        "controls": [controls[key] for key in sorted(controls)],
        "evaluation_source": "wara-shadow-assessment",
        "last_assessment_id": _text(assessment.get("assessment_id"), "assessment_id"),
        "last_assessment_scope": scope_digest,
        "last_evaluated_at": evaluated_at,
    }


@runtime_checkable
class WaraProjectionStore(Protocol):
    async def read_wara_catalog(self) -> Mapping[str, object]: ...

    async def write_wara_projection(self, value: Mapping[str, object]) -> None: ...


class WaraAssessmentProjectionConsumer:
    """Consume one typed shadow event without gaining assessment authority."""

    def __init__(self, store: WaraProjectionStore) -> None:
        self._store = store

    async def handle(self, assessment: Mapping[str, object]) -> None:
        current = await self._store.read_wara_catalog()
        projected = project_wara_assessment(current, assessment)
        await self._store.write_wara_projection(projected)


class WaraProjectionSource(Protocol):
    async def probe_readiness(self) -> bool: ...

    def subscribe(
        self,
        topic: str,
        group_id: str,
    ) -> AsyncIterator[Mapping[str, object]]: ...


class WaraProjectionPublisher(Protocol):
    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


class WaraAssessmentProjectionBridge:
    """Own the supervised WARA event-to-projection consumer lifecycle."""

    def __init__(
        self,
        *,
        store: WaraProjectionStore,
        source: WaraProjectionSource,
        publisher: WaraProjectionPublisher,
        topic: str = WARA_ASSESSMENT_TOPIC,
        group_id: str = WARA_ASSESSMENT_CONSUMER_GROUP,
        retry_seconds: float = 1.0,
    ) -> None:
        if not topic.strip() or not group_id.strip() or retry_seconds <= 0:
            raise ValueError("WARA projection bridge configuration is invalid")
        self._consumer = WaraAssessmentProjectionConsumer(store)
        self._source = source
        self._publisher = publisher
        self._topic = topic
        self._group_id = group_id
        self._retry_seconds = retry_seconds
        self._task: asyncio.Task[None] | None = None
        self._healthy = False

    def workers_ready(self) -> bool:
        return self._task is not None and not self._task.done() and self._healthy

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(
                self._run(),
                name="operator-wara-assessment-projection-consumer",
            )

    async def aclose(self) -> None:
        task, self._task = self._task, None
        self._healthy = False
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                if not await self._source.probe_readiness():
                    raise RuntimeError("WARA projection source is unavailable")
                self._healthy = True
                async for payload in self._source.subscribe(self._topic, self._group_id):
                    try:
                        await self._consumer.handle(payload)
                    except WaraProjectionError:
                        await self._quarantine(payload)
                    self._healthy = True
            except Exception:  # noqa: BLE001 - retain source offset and retry
                self._healthy = False
                _LOGGER.warning("wara_assessment_projection_consumer_retrying", exc_info=True)
            await asyncio.sleep(self._retry_seconds)

    async def _quarantine(self, payload: Mapping[str, object]) -> None:
        key_value = payload.get("assessment_id")
        key = key_value if isinstance(key_value, str) and key_value else "invalid-wara-assessment"
        await self._publisher.publish(
            f"{self._topic}.dlq",
            key,
            {
                "original_topic": self._topic,
                "assessment_ref": key,
                "reason": "invalid_wara_assessment_projection",
            },
        )


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WaraProjectionError(f"WARA {field} MUST be a non-empty string")
    return value


def _member(value: object, allowed: set[str], field: str) -> str:
    text = _text(value, field)
    if text not in allowed:
        raise WaraProjectionError(f"WARA {field} has an unknown value")
    return text


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise WaraProjectionError(f"WARA {field} MUST contain strings")
    return list(value)


__all__ = [
    "WaraAssessmentProjectionBridge",
    "WaraAssessmentProjectionConsumer",
    "WaraProjectionError",
    "WaraProjectionPublisher",
    "WaraProjectionSource",
    "WaraProjectionStore",
    "project_wara_assessment",
]
