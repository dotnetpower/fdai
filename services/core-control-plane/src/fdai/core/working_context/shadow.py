"""Bounded off-request shadow evaluation for candidate selection policies."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from fdai.core.working_context.evidence import (
    ContextSelectionEvaluation,
    ContextSelectionEvaluationStore,
)
from fdai.core.working_context.governance import ContextSelectionPolicyAuthority
from fdai.core.working_context.selection import ContextSelectionInput, ContextSelectionPolicy
from fdai.core.working_context.types import WorkingContext
from fdai.core.working_context.validation import execute_context_selection_policy

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ContextShadowConfig:
    max_candidates: int = 3
    timeout_seconds: float = 0.25
    max_pending_runs: int = 16

    def __post_init__(self) -> None:
        if self.max_candidates < 1:
            raise ValueError("max_candidates MUST be >= 1")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be > 0")
        if self.max_pending_runs < 1:
            raise ValueError("max_pending_runs MUST be >= 1")


class ContextSelectionShadowRunner:
    """Run candidate policies asynchronously without touching active output."""

    def __init__(
        self,
        *,
        authority: ContextSelectionPolicyAuthority,
        store: ContextSelectionEvaluationStore,
        config: ContextShadowConfig | None = None,
    ) -> None:
        self._authority = authority
        self._store = store
        self._config = config or ContextShadowConfig()
        self._pending: set[asyncio.Task[tuple[ContextSelectionEvaluation, ...]]] = set()

    def schedule(
        self,
        *,
        selection_input: ContextSelectionInput,
        baseline: WorkingContext,
        answer_quality_ref: str | None = None,
        answer_quality_score: float | None = None,
    ) -> bool:
        """Schedule evaluation and return immediately; never changes ``baseline``."""

        if len(self._pending) >= self._config.max_pending_runs:
            return False
        task = asyncio.create_task(
            self.evaluate(
                selection_input=selection_input,
                baseline=baseline,
                answer_quality_ref=answer_quality_ref,
                answer_quality_score=answer_quality_score,
            )
        )
        self._pending.add(task)
        task.add_done_callback(self._finish_scheduled)
        return True

    async def evaluate(
        self,
        *,
        selection_input: ContextSelectionInput,
        baseline: WorkingContext,
        answer_quality_ref: str | None = None,
        answer_quality_score: float | None = None,
    ) -> tuple[ContextSelectionEvaluation, ...]:
        policies = self._authority.shadow_policies(limit=self._config.max_candidates)
        if not policies:
            return ()
        active = self._authority.snapshot().active
        baseline_ref = active.ref if active is not None else "unavailable"
        records = await asyncio.gather(
            *(
                self._evaluate_one(
                    policy=policy,
                    selection_input=selection_input,
                    baseline=baseline,
                    baseline_ref=baseline_ref,
                    answer_quality_ref=answer_quality_ref,
                    answer_quality_score=answer_quality_score,
                )
                for policy in policies
            )
        )
        for record in records:
            await self._store.append(record)
        return tuple(records)

    async def drain(self) -> None:
        """Wait for scheduled runs; intended for shutdown and tests only."""

        pending = tuple(self._pending)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def _finish_scheduled(
        self,
        task: asyncio.Task[tuple[ContextSelectionEvaluation, ...]],
    ) -> None:
        self._pending.discard(task)
        try:
            task.result()
        except Exception:
            _LOGGER.exception("context_selection_shadow_run_failed")

    async def _evaluate_one(
        self,
        *,
        policy: ContextSelectionPolicy,
        selection_input: ContextSelectionInput,
        baseline: WorkingContext,
        baseline_ref: str,
        answer_quality_ref: str | None,
        answer_quality_score: float | None,
    ) -> ContextSelectionEvaluation:
        started = time.perf_counter()
        candidate: WorkingContext | None = None
        failure_reason: str | None = None
        try:
            candidate = await asyncio.wait_for(
                asyncio.to_thread(
                    execute_context_selection_policy,
                    policy=policy,
                    selection_input=selection_input,
                ),
                timeout=self._config.timeout_seconds,
            )
        except TimeoutError:
            failure_reason = f"timeout>{self._config.timeout_seconds:.3f}s"
        except Exception as exc:
            failure_reason = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - started) * 1000.0
        return _comparison(
            policy=policy,
            selection_input=selection_input,
            baseline=baseline,
            candidate=candidate,
            baseline_ref=baseline_ref,
            answer_quality_ref=answer_quality_ref,
            answer_quality_score=answer_quality_score,
            latency_ms=latency_ms,
            failure_reason=failure_reason,
        )


def fingerprint_context_selection_input(selection_input: ContextSelectionInput) -> str:
    payload = {
        "entries": [
            {
                **asdict(entry),
                "role": entry.role.value,
                "kind": entry.kind.value,
                "metadata": dict(sorted(entry.metadata.items())),
            }
            for entry in selection_input.entries
        ],
        "trust_classes": {
            key: value.value for key, value in sorted(selection_input.trust_classes.items())
        },
        "budget": asdict(selection_input.budget),
        "model": {
            "model_id": selection_input.model.model_id,
            "context_window": selection_input.model.context_window,
            "supports_tools": selection_input.model.supports_tools,
            "metadata": dict(sorted(selection_input.model.metadata.items())),
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _comparison(
    *,
    policy: ContextSelectionPolicy,
    selection_input: ContextSelectionInput,
    baseline: WorkingContext,
    candidate: WorkingContext | None,
    baseline_ref: str,
    answer_quality_ref: str | None,
    answer_quality_score: float | None,
    latency_ms: float,
    failure_reason: str | None,
) -> ContextSelectionEvaluation:
    baseline_ids = {entry.entry_id for entry in baseline.entries}
    candidate_ids = {entry.entry_id for entry in candidate.entries} if candidate else set()
    union = baseline_ids | candidate_ids
    overlap = len(baseline_ids & candidate_ids) / len(union) if union and candidate else None
    pinned_ids = {entry.entry_id for entry in selection_input.entries if entry.pinned}
    relevance_values = (
        [entry.relevance for entry in candidate.entries if entry.relevance is not None]
        if candidate
        else []
    )
    return ContextSelectionEvaluation(
        evaluation_id=str(uuid.uuid4()),
        input_fingerprint=fingerprint_context_selection_input(selection_input),
        baseline_policy_ref=baseline_ref,
        candidate_policy_ref=f"{policy.policy_id}@{policy.policy_version}",
        baseline_manifest=baseline.manifest,
        candidate_manifest=candidate.manifest if candidate else None,
        baseline_tokens=baseline.total_tokens,
        candidate_tokens=candidate.total_tokens if candidate else None,
        evidence_overlap=overlap,
        omissions=tuple(sorted(baseline_ids - candidate_ids)),
        pinned_preserved=pinned_ids.issubset(candidate_ids) if candidate else False,
        relevance=(
            sum(value for value in relevance_values if value is not None) / len(relevance_values)
            if relevance_values
            else None
        ),
        answer_quality_ref=answer_quality_ref,
        answer_quality_score=answer_quality_score,
        latency_ms=latency_ms,
        failure_reason=failure_reason,
        created_at=datetime.now(tz=UTC),
    )


__all__ = [
    "ContextSelectionShadowRunner",
    "ContextShadowConfig",
    "fingerprint_context_selection_input",
]
