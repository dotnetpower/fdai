"""Bind and invoke one reviewed immutable Bragi intent-training batch."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fdai.agents import Bragi, IntentTrainingRun, PantheonRuntime
from fdai.delivery.bragi_intent_training_evidence import ImmutableBragiIntentTrainingBatch

_PATH_ENV = "FDAI_BRAGI_INTENT_TRAINING_EVIDENCE_PATH"
_DIGEST_ENV = "FDAI_BRAGI_INTENT_TRAINING_EVIDENCE_SHA256"
_SOURCE_REVISION_ENV = "FDAI_SOURCE_REVISION"


def build_bragi_intent_training_batch(
    environment: Mapping[str, str],
) -> ImmutableBragiIntentTrainingBatch | None:
    """Load one complete reviewed batch or keep off-path training unbound."""

    path_value = environment.get(_PATH_ENV, "").strip()
    digest = environment.get(_DIGEST_ENV, "").strip()
    if not path_value and not digest:
        return None
    if not path_value or not digest:
        raise RuntimeError("Bragi intent-training evidence configuration is incomplete")
    source_revision = environment.get(_SOURCE_REVISION_ENV, "").strip()
    if not source_revision:
        raise RuntimeError("Bragi intent-training evidence requires FDAI_SOURCE_REVISION")
    path = Path(path_value)
    if not path.is_absolute():
        raise RuntimeError("Bragi intent-training evidence path MUST be absolute")
    try:
        batch = ImmutableBragiIntentTrainingBatch.load(path, expected_digest=digest)
    except ValueError as exc:
        raise RuntimeError("Bragi intent-training evidence is invalid") from exc
    if batch.source_revision != source_revision:
        raise RuntimeError("Bragi intent-training evidence source revision differs")
    return batch


async def run_bragi_intent_training_batch(
    runtime: PantheonRuntime,
    batch: ImmutableBragiIntentTrainingBatch,
) -> IntentTrainingRun:
    """Run the reviewed batch through Bragi's existing inert evidence path."""

    bragi = runtime.agents.get("Bragi")
    if not isinstance(bragi, Bragi):
        raise RuntimeError("Bragi intent-training requires the Bragi agent")
    return await bragi.run_intent_training(
        batch.corpus,
        reviewed_promotion=batch.reviewed_promotion,
    )


__all__ = ["build_bragi_intent_training_batch", "run_bragi_intent_training_batch"]
