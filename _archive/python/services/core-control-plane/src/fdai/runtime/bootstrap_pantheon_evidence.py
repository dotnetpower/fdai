"""Compose optional reviewed evidence inputs for Pantheon startup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from fdai.agents import (
    ChaosScenarioGenerator,
    ChaosScheduleConfig,
    ForsetiHistoricalReplaySource,
    IntentTrainingEvaluator,
    MimirCatalogPromotionOutcomeReader,
    MimirRegressionRunner,
    MimirRuleDeprecationReader,
    PantheonRuntime,
)
from fdai.delivery.bragi_intent_training_evidence import ImmutableBragiIntentTrainingBatch
from fdai.runtime.bootstrap_bragi_intent_training import (
    build_bragi_intent_training_batch,
    run_bragi_intent_training_batch,
)
from fdai.runtime.bootstrap_forseti_replay import build_forseti_historical_replay_source
from fdai.runtime.bootstrap_loki_scenarios import build_loki_scenario_bindings
from fdai.runtime.bootstrap_mimir_maintenance import build_mimir_maintenance_source
from fdai.runtime.bootstrap_pantheon_models import PantheonInitialization


class PantheonEvidenceRuntimeKwargs(TypedDict):
    forseti_historical_replay_source: ForsetiHistoricalReplaySource | None
    loki_scenario_generator: ChaosScenarioGenerator | None
    loki_scenario_corpus: tuple[ChaosScheduleConfig, ...]
    mimir_promotion_outcome_reader: MimirCatalogPromotionOutcomeReader | None
    mimir_regression_runner: MimirRegressionRunner | None
    mimir_rule_deprecation_reader: MimirRuleDeprecationReader | None
    conversation_intent_training_evaluator: IntentTrainingEvaluator | None


@dataclass(frozen=True, slots=True)
class ReviewedPantheonEvidence:
    runtime_kwargs: PantheonEvidenceRuntimeKwargs
    bragi_batch: ImmutableBragiIntentTrainingBatch | None

    async def run_configured_training(self, runtime: PantheonRuntime) -> None:
        if self.bragi_batch is not None:
            await run_bragi_intent_training_batch(runtime, self.bragi_batch)


def build_reviewed_pantheon_evidence(
    config: PantheonInitialization,
) -> ReviewedPantheonEvidence:
    action_type_names = frozenset(action.name for action in config.control_loop.action_types)
    mimir = build_mimir_maintenance_source(config.environment)
    loki = build_loki_scenario_bindings(
        environment=config.environment,
        action_type_names=action_type_names,
    )
    forseti = build_forseti_historical_replay_source(config.environment)
    bragi = build_bragi_intent_training_batch(config.environment)
    return ReviewedPantheonEvidence(
        runtime_kwargs={
            "forseti_historical_replay_source": forseti,
            "loki_scenario_generator": loki.generator if loki is not None else None,
            "loki_scenario_corpus": loki.corpus if loki is not None else (),
            "mimir_promotion_outcome_reader": mimir,
            "mimir_regression_runner": mimir,
            "mimir_rule_deprecation_reader": mimir,
            "conversation_intent_training_evaluator": bragi,
        },
        bragi_batch=bragi,
    )


__all__ = ["ReviewedPantheonEvidence", "build_reviewed_pantheon_evidence"]
