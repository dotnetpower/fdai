"""Content-free production shadow records for the carried question form."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    SemanticProblemFrame,
    content_digest,
)
from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentProposal,
    SemanticJudgmentReceipt,
)

from fdai.core.ontology_platform import QueryManifest
from fdai.shared.providers.state_store import StateStore

from .semantic_planning_models import SemanticPlanningOutcome

_LOGGER = logging.getLogger(__name__)

PRODUCTION_SHADOW_ABSENT = "form_absent"
PRODUCTION_SHADOW_LINKED = "linked"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ProductionShadowSettings:
    """Typed default-off switch and stable sampling namespace."""

    enabled: bool = False
    sample_key: str = "semantic-production-shadow"
    sample_percent: int = 100
    ttl_seconds: int = 86400

    def __post_init__(self) -> None:
        if not self.sample_key.strip() or len(self.sample_key) > 128:
            raise ValueError("production shadow sample key MUST be non-empty and bounded")
        if type(self.sample_percent) is not int or not 0 <= self.sample_percent <= 100:
            raise ValueError("production shadow sample percent MUST be between 0 and 100")
        if type(self.ttl_seconds) is not int or not 0 < self.ttl_seconds <= 30 * 86400:
            raise ValueError("production shadow TTL MUST be between 1 second and 30 days")


@dataclass(frozen=True, slots=True)
class ProductionShadowRecord:
    """One linked disposition with only digests and closed status codes."""

    disposition: str
    sample_id_digest: str
    judgment_request_digest: str
    carried_form_digest: str | None
    prompt_digest: str | None
    model_config_digest: str | None
    manifest_digest: str
    cutoff_digest: str
    frame_digest: str
    compiled_plan_digest: str
    answer_output_digest: str
    expires_at: datetime
    execution_authority: bool = False

    def as_state(self) -> dict[str, object]:
        return {
            "disposition": self.disposition,
            "sample_id_digest": self.sample_id_digest,
            "judgment_request_digest": self.judgment_request_digest,
            "carried_form_digest": self.carried_form_digest,
            "prompt_digest": self.prompt_digest,
            "model_config_digest": self.model_config_digest,
            "manifest_digest": self.manifest_digest,
            "cutoff_digest": self.cutoff_digest,
            "frame_digest": self.frame_digest,
            "compiled_plan_digest": self.compiled_plan_digest,
            "answer_output_digest": self.answer_output_digest,
            "expires_at": self.expires_at.isoformat(),
            "execution_authority": False,
        }


class ProductionShadowSink(Protocol):
    def write(self, record: ProductionShadowRecord) -> None:
        """Persist or retain one content-free shadow record."""


class InMemoryProductionShadowSink:
    """Deterministic test sink for content-free production shadow records."""

    def __init__(self) -> None:
        self.records: list[ProductionShadowRecord] = []

    def write(self, record: ProductionShadowRecord) -> None:
        self.records.append(record)


class StateStoreProductionShadowSink:
    """Hand each record to the service's own event loop, never blocking the planner.

    The shared state store belongs to one loop, so a write is scheduled there and not
    awaited; a failed write is logged without content and never reaches the answer.
    """

    def __init__(self, store: StateStore, owner_loop: asyncio.AbstractEventLoop) -> None:
        self._store = store
        self._owner_loop = owner_loop

    def write(self, record: ProductionShadowRecord) -> None:
        # One key per turn, so two turns with equal text never overwrite each other.
        key = f"semantic-production-shadow.{record.sample_id_digest}.{uuid.uuid4().hex}"
        future = asyncio.run_coroutine_threadsafe(
            self._store.write_state(key, record.as_state()), self._owner_loop
        )
        future.add_done_callback(_log_failed_write)


def _log_failed_write(future: concurrent.futures.Future[None]) -> None:
    if not future.cancelled() and future.exception() is not None:
        _LOGGER.warning(
            "semantic_production_shadow_unrecorded",
            extra={"failure_type": type(future.exception()).__name__},
        )


@dataclass(frozen=True, slots=True)
class ProductionShadowRecorder:
    """Default-off recorder that cannot influence answer composition."""

    settings: ProductionShadowSettings
    sink: ProductionShadowSink
    clock: Callable[[], datetime] = _utc_now

    def record(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        proposal: SemanticJudgmentProposal,
        receipt: SemanticJudgmentReceipt,
        manifest: QueryManifest,
        frame: SemanticProblemFrame,
        plan: OntologyQueryPlan,
        outcome: SemanticPlanningOutcome,
    ) -> ProductionShadowRecord | None:
        if not self.settings.enabled:
            return None
        sample_id_digest = _sample_digest(self.settings.sample_key, utterance, context)
        if int(sample_id_digest.removeprefix("sha256:"), 16) % 100 >= self.settings.sample_percent:
            return None
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("production shadow clock MUST be timezone-aware")
        record = production_shadow_record(
            sample_id_digest=sample_id_digest,
            expires_at=now + timedelta(seconds=self.settings.ttl_seconds),
            utterance=utterance,
            context=context,
            proposal=proposal,
            receipt=receipt,
            manifest=manifest,
            frame=frame,
            plan=plan,
            outcome=outcome,
        )
        self.sink.write(record)
        return record


def record_planned_shadow(
    recorder: ProductionShadowRecorder | None,
    judgment_decision: object,
    *,
    utterance: str,
    context: tuple[str, ...],
    manifest: QueryManifest,
    frame: SemanticProblemFrame,
    plan: OntologyQueryPlan,
    outcome: SemanticPlanningOutcome,
) -> None:
    proposal = getattr(judgment_decision, "proposal", None)
    receipt = getattr(judgment_decision, "receipt", None)
    if recorder is None or proposal is None or receipt is None:
        return
    try:
        recorder.record(
            utterance=utterance,
            context=context,
            proposal=proposal,
            receipt=receipt,
            manifest=manifest,
            frame=frame,
            plan=plan,
            outcome=outcome,
        )
    except Exception as exc:  # noqa: BLE001 - the shadow must never change the answer
        _LOGGER.warning(
            "semantic_production_shadow_unrecorded", extra={"failure_type": type(exc).__name__}
        )


def production_shadow_record(
    *,
    sample_id_digest: str,
    expires_at: datetime,
    utterance: str,
    context: tuple[str, ...],
    proposal: SemanticJudgmentProposal,
    receipt: SemanticJudgmentReceipt,
    manifest: QueryManifest,
    frame: SemanticProblemFrame,
    plan: OntologyQueryPlan,
    outcome: SemanticPlanningOutcome,
) -> ProductionShadowRecord:
    carried = proposal.question_form
    return ProductionShadowRecord(
        disposition=PRODUCTION_SHADOW_LINKED if carried is not None else PRODUCTION_SHADOW_ABSENT,
        sample_id_digest=sample_id_digest,
        judgment_request_digest=content_digest(
            {
                "input_digest": receipt.input_digest,
                "context_digest": receipt.context_digest,
                "capability_digest": receipt.capability_digest,
                "proposal_digest": receipt.proposal_digest,
            }
        ),
        carried_form_digest=carried.digest if carried is not None else None,
        prompt_digest=receipt.prompt_digest,
        model_config_digest=receipt.model_config_digest,
        manifest_digest=manifest.manifest_digest,
        cutoff_digest=content_digest(
            {
                "ontology_release_digest": manifest.release_digest,
                "manifest_digest": manifest.manifest_digest,
            }
        ),
        frame_digest=frame.frame_digest,
        compiled_plan_digest=plan.plan_digest,
        answer_output_digest=content_digest(_outcome_digest_payload(outcome)),
        expires_at=expires_at,
    )


def _sample_digest(sample_key: str, utterance: str, context: tuple[str, ...]) -> str:
    return content_digest({"sample_key": sample_key, "utterance": utterance, "context": context})


def _outcome_digest_payload(outcome: SemanticPlanningOutcome) -> Mapping[str, object]:
    return {
        "disposition": outcome.disposition.value,
        "reason": outcome.reason,
        "manifest_digest": outcome.manifest_digest,
        "frame_digest": outcome.frame.frame_digest if outcome.frame is not None else None,
        "plan_digest": outcome.plan.plan_digest if outcome.plan is not None else None,
    }


__all__ = [
    "PRODUCTION_SHADOW_ABSENT",
    "PRODUCTION_SHADOW_LINKED",
    "InMemoryProductionShadowSink",
    "ProductionShadowRecord",
    "ProductionShadowRecorder",
    "ProductionShadowSettings",
    "ProductionShadowSink",
    "StateStoreProductionShadowSink",
    "production_shadow_record",
    "record_planned_shadow",
]
