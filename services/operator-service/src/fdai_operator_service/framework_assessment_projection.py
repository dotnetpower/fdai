"""Fail-closed WAF and CAF shadow assessment projection for Operator reads."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai_service_contracts.framework_assessment import (
    FRAMEWORK_ASSESSMENT_CONSUMER_GROUP,
    FRAMEWORK_ASSESSMENT_TOPIC,
)

_LOGGER = logging.getLogger(__name__)
_FRAMEWORKS = frozenset({"azure-waf", "azure-caf", "azure-mcsb"})
_MAPPING = frozenset({"full", "partial", "unmapped"})
_APPLICABILITY = frozenset({"applicable", "not_applicable"})
_EVALUATION = frozenset({"evaluated", "not_evaluated", "blocked"})
_SATISFACTION = frozenset({"satisfied", "failed", "not_applicable", "unknown"})


class FrameworkAssessmentProjectionError(ValueError):
    """A framework event cannot enter the Operator projection."""


def project_framework_assessment(
    catalog_projection: Mapping[str, object],
    assessment: Mapping[str, object],
) -> dict[str, object]:
    """Merge one complete no-authority shadow snapshot into its catalog projection."""

    if assessment.get("mode") != "shadow" or assessment.get("execution_authority") is not False:
        raise FrameworkAssessmentProjectionError(
            "framework projection requires a no-authority shadow assessment"
        )
    framework_id = _member(assessment.get("framework_id"), _FRAMEWORKS, "framework_id")
    if catalog_projection.get("framework_id") != framework_id:
        raise FrameworkAssessmentProjectionError("framework projection identity mismatch")
    if assessment.get("framework_version") != catalog_projection.get("framework_version"):
        raise FrameworkAssessmentProjectionError("framework projection version mismatch")
    if assessment.get("catalog_digest") != catalog_projection.get("catalog_digest"):
        raise FrameworkAssessmentProjectionError("framework projection catalog digest mismatch")
    controls_value = catalog_projection.get("controls")
    results_value = assessment.get("controls")
    profile_value = assessment.get("applicability_profile")
    if not isinstance(controls_value, list) or not all(
        isinstance(item, dict) for item in controls_value
    ):
        raise FrameworkAssessmentProjectionError("framework catalog controls are malformed")
    if not isinstance(results_value, list) or not all(
        isinstance(item, dict) for item in results_value
    ):
        raise FrameworkAssessmentProjectionError("framework assessment controls are malformed")
    if not isinstance(profile_value, list) or not all(
        isinstance(item, dict) for item in profile_value
    ):
        raise FrameworkAssessmentProjectionError("framework applicability profile is malformed")
    controls = {str(item.get("control_id")): dict(item) for item in controls_value}
    results = {str(item.get("control_id")): item for item in results_value}
    decisions = {str(item.get("control_id")): item for item in profile_value}
    expected_ids = set(controls)
    if (
        len(controls) != len(controls_value)
        or len(results) != len(results_value)
        or len(decisions) != len(profile_value)
        or set(results) != expected_ids
        or set(decisions) != expected_ids
    ):
        raise FrameworkAssessmentProjectionError(
            "framework assessment MUST exactly cover catalog controls"
        )

    evaluated_at = _timestamp(assessment.get("evaluated_at"), "evaluated_at")
    recorded_at = _timestamp(assessment.get("recorded_at"), "recorded_at")
    current_evaluated_at = catalog_projection.get("last_evaluated_at")
    if isinstance(current_evaluated_at, str):
        current = _timestamp(current_evaluated_at, "last_evaluated_at")
        if current > evaluated_at:
            raise FrameworkAssessmentProjectionError(
                "framework assessment is older than the current projection"
            )
    result_digest = _digest(assessment.get("result_digest"), "result_digest")
    if catalog_projection.get("_revision") == result_digest:
        return dict(catalog_projection)
    if isinstance(current_evaluated_at, str):
        current = _timestamp(current_evaluated_at, "last_evaluated_at")
        current_recorded_value = catalog_projection.get("last_recorded_at")
        if isinstance(current_recorded_value, str):
            current_recorded = _timestamp(
                current_recorded_value,
                "last_recorded_at",
            )
            if (current, current_recorded) >= (evaluated_at, recorded_at):
                raise FrameworkAssessmentProjectionError(
                    "framework assessment conflicts with the current projection cutoff"
                )

    scope_digest = _digest(assessment.get("scope_digest"), "scope_digest")
    profile_id = _text(assessment.get("profile_id"), "profile_id")
    profile_digest = _digest(assessment.get("profile_digest"), "profile_digest")
    for control_id in sorted(controls):
        result = results[control_id]
        decision = decisions[control_id]
        reference_state = _member(
            result.get("reference_state"),
            frozenset({"present"}),
            "reference_state",
        )
        mapping_state = _member(result.get("mapping_state"), _MAPPING, "mapping_state")
        applicability = _member(
            result.get("applicability"),
            _APPLICABILITY,
            "applicability",
        )
        evaluation = _member(result.get("evaluation"), _EVALUATION, "evaluation")
        satisfaction = _member(
            result.get("satisfaction"),
            _SATISFACTION,
            "satisfaction",
        )
        evidence_complete = result.get("evidence_complete")
        if not isinstance(evidence_complete, bool):
            raise FrameworkAssessmentProjectionError("framework evidence_complete MUST be boolean")
        if evaluation != "evaluated" and (
            evidence_complete or satisfaction in {"satisfied", "failed", "not_applicable"}
        ):
            raise FrameworkAssessmentProjectionError(
                "unevaluated framework control cannot claim a terminal satisfaction"
            )
        if decision.get("status") != applicability:
            raise FrameworkAssessmentProjectionError(
                "framework applicability result does not match the profile"
            )
        approved_exception = (
            {
                "justification": _text(decision.get("justification"), "justification"),
                "approved_by": _text(decision.get("approved_by"), "approved_by"),
                "approved_at": _text(decision.get("approved_at"), "approved_at"),
                "expires_at": _text(decision.get("expires_at"), "expires_at"),
            }
            if applicability == "not_applicable"
            else None
        )
        common = {
            "reference_state": reference_state,
            "mapping_state": mapping_state,
            "applicability": applicability,
            "evaluation_status": evaluation,
            "satisfaction": satisfaction,
            "owner_slot": _text(result.get("owner_slot"), "owner_slot"),
            "cadence_days": _positive_int(result.get("cadence_days"), "cadence_days"),
            "evaluation_scope": scope_digest,
            "evaluated_at": evaluated_at.isoformat(),
            "profile_id": profile_id,
            "profile_digest": profile_digest,
            "approved_exception": approved_exception,
            "evidence_complete": evidence_complete,
            "evidence_refs": _strings(result.get("evidence_refs"), "evidence_refs"),
            "evidence_digests": tuple(
                _digest(item, "evidence_digest")
                for item in _strings(result.get("evidence_digests"), "evidence_digests")
            ),
            "limitations": _strings(result.get("limitations"), "limitations"),
            "execution_authority": False,
        }
        if framework_id == "azure-waf":
            common.update(
                {
                    "mapping_status": {
                        "full": "mapped",
                        "partial": "partially_mapped",
                        "unmapped": "unmapped",
                    }[mapping_state],
                    "status": satisfaction,
                    "requirements": _waf_requirements(controls[control_id], result),
                }
            )
            requirements = common["requirements"]
            if not isinstance(requirements, list):
                raise FrameworkAssessmentProjectionError("WAF projected requirements are malformed")
            common["satisfied_requirement_count"] = sum(
                item.get("status") == "satisfied" for item in requirements if isinstance(item, dict)
            )
        if framework_id == "azure-mcsb":
            requirements = _waf_requirements(controls[control_id], result)
            roles = {
                _text(item.get("requirement_id"), "requirement_id"): item.get("evidence_role")
                for item in _records(
                    controls[control_id].get("evidence_specifications"),
                    "evidence_specifications",
                )
            }
            for requirement, role in zip(requirements, roles.values(), strict=True):
                requirement["evidence_role"] = _member(
                    role, frozenset({"decisive", "supporting_only"}), "evidence_role"
                )
            common["requirements"] = requirements
        controls[control_id].update(common)

    return {
        **dict(catalog_projection),
        "_revision": result_digest,
        "controls": [controls[key] for key in sorted(controls)],
        "evaluation_source": "framework-shadow-assessment",
        "last_assessment_id": _text(assessment.get("assessment_id"), "assessment_id"),
        "last_assessment_scope": scope_digest,
        "last_evaluated_at": evaluated_at.isoformat(),
        "last_recorded_at": recorded_at.isoformat(),
        "last_profile_id": profile_id,
        "last_profile_digest": profile_digest,
        "last_tradeoffs": _records(assessment.get("tradeoffs"), "tradeoffs"),
    }


def _waf_requirements(
    catalog_control: Mapping[str, object],
    result: Mapping[str, object],
) -> list[dict[str, object]]:
    specifications = _records(
        catalog_control.get("evidence_specifications"),
        "evidence_specifications",
    )
    result_requirements = _records(result.get("requirements"), "requirements")
    by_id = {
        _text(item.get("requirement_id"), "requirement_id"): item for item in result_requirements
    }
    if len(by_id) != len(result_requirements):
        raise FrameworkAssessmentProjectionError(
            "framework requirement results contain duplicate ids"
        )
    projected: list[dict[str, object]] = []
    for specification in specifications:
        requirement_id = _text(specification.get("requirement_id"), "requirement_id")
        item = by_id.get(requirement_id)
        if item is None:
            raise FrameworkAssessmentProjectionError(
                "framework result does not cover every WAF requirement"
            )
        freshness = _positive_int(
            specification.get("freshness_ceiling_seconds"),
            "freshness_ceiling_seconds",
        )
        projected.append(
            {
                "kind": _text(specification.get("kind"), "kind"),
                "ref": _text(specification.get("source_ref"), "source_ref"),
                "freshness_days": max(1, freshness // 86_400),
                "status": _member(item.get("status"), _SATISFACTION, "requirement status"),
                "evidence_refs": list(_strings(item.get("evidence_refs"), "evidence_refs")),
                "limitations": list(_strings(item.get("limitations", []), "limitations")),
            }
        )
    if set(by_id) != {
        _text(item.get("requirement_id"), "requirement_id") for item in specifications
    }:
        raise FrameworkAssessmentProjectionError(
            "framework result contains unknown WAF requirements"
        )
    return projected


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FrameworkAssessmentProjectionError(f"framework {label} MUST be non-empty")
    return value


def _digest(value: object, label: str) -> str:
    text = _text(value, label)
    if not text.startswith("sha256:") or len(text) != 71:
        raise FrameworkAssessmentProjectionError(f"framework {label} MUST be lowercase SHA-256")
    try:
        int(text.removeprefix("sha256:"), 16)
    except ValueError as error:
        raise FrameworkAssessmentProjectionError(
            f"framework {label} MUST be lowercase SHA-256"
        ) from error
    if text != text.lower():
        raise FrameworkAssessmentProjectionError(f"framework {label} MUST be lowercase SHA-256")
    return text


def _member(value: object, allowed: frozenset[str], label: str) -> str:
    text = _text(value, label)
    if text not in allowed:
        raise FrameworkAssessmentProjectionError(
            f"framework {label} has unsupported value {text!r}"
        )
    return text


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise FrameworkAssessmentProjectionError(f"framework {label} MUST be positive")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise FrameworkAssessmentProjectionError(f"framework {label} MUST be strings")
    result = tuple(value)
    if result != tuple(sorted(set(result))):
        raise FrameworkAssessmentProjectionError(f"framework {label} MUST be unique and ordered")
    return result


def _records(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise FrameworkAssessmentProjectionError(f"framework {label} MUST be records")
    return [dict(item) for item in value]


def _timestamp(value: object, label: str) -> datetime:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise FrameworkAssessmentProjectionError(f"framework {label} MUST be RFC 3339") from error
    if parsed.tzinfo is None:
        raise FrameworkAssessmentProjectionError(f"framework {label} MUST be timezone-aware")
    return parsed


@runtime_checkable
class FrameworkAssessmentProjectionStore(Protocol):
    async def read_framework_catalog(self, framework_id: str) -> Mapping[str, object]: ...

    async def write_framework_projection(
        self,
        framework_id: str,
        value: Mapping[str, object],
    ) -> None: ...


class FrameworkAssessmentProjectionConsumer:
    """Consume one typed framework event without gaining assessment authority."""

    def __init__(self, store: FrameworkAssessmentProjectionStore) -> None:
        self._store = store

    async def handle(self, assessment: Mapping[str, object]) -> None:
        framework_id = _member(
            assessment.get("framework_id"),
            _FRAMEWORKS,
            "framework_id",
        )
        current = await self._store.read_framework_catalog(framework_id)
        projected = project_framework_assessment(current, assessment)
        await self._store.write_framework_projection(framework_id, projected)


class FrameworkProjectionSource(Protocol):
    async def probe_readiness(self) -> bool: ...

    def subscribe(
        self,
        topic: str,
        group_id: str,
    ) -> AsyncIterator[Mapping[str, object]]: ...


class FrameworkProjectionPublisher(Protocol):
    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


class FrameworkAssessmentProjectionBridge:
    """Own the supervised framework event-to-projection consumer lifecycle."""

    def __init__(
        self,
        *,
        store: FrameworkAssessmentProjectionStore,
        source: FrameworkProjectionSource,
        publisher: FrameworkProjectionPublisher,
        topic: str = FRAMEWORK_ASSESSMENT_TOPIC,
        group_id: str = FRAMEWORK_ASSESSMENT_CONSUMER_GROUP,
        retry_seconds: float = 1.0,
    ) -> None:
        if not topic.strip() or not group_id.strip() or retry_seconds <= 0:
            raise ValueError("framework projection bridge configuration is invalid")
        self._consumer = FrameworkAssessmentProjectionConsumer(store)
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
                name="operator-framework-assessment-projection-consumer",
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
                    raise RuntimeError("framework projection source is unavailable")
                self._healthy = True
                async for payload in self._source.subscribe(self._topic, self._group_id):
                    try:
                        await self._consumer.handle(payload)
                    except FrameworkAssessmentProjectionError:
                        await self._quarantine(payload)
                    self._healthy = True
            except Exception:  # noqa: BLE001 - retain source offset and retry
                self._healthy = False
                _LOGGER.warning(
                    "framework_assessment_projection_consumer_retrying",
                    exc_info=True,
                )
            await asyncio.sleep(self._retry_seconds)

    async def _quarantine(self, payload: Mapping[str, object]) -> None:
        assessment_id = payload.get("assessment_id")
        key = assessment_id if isinstance(assessment_id, str) else "invalid-framework"
        await self._publisher.publish(
            f"{self._topic}.dlq",
            key,
            {
                "reason": "invalid_framework_assessment_projection",
                "assessment_id": assessment_id,
            },
        )


__all__ = [
    "FrameworkAssessmentProjectionBridge",
    "FrameworkAssessmentProjectionConsumer",
    "FrameworkAssessmentProjectionError",
    "FrameworkAssessmentProjectionStore",
    "project_framework_assessment",
]
