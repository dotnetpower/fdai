"""Batch orchestrator + scenario runner on top of :mod:`.prompt_probe`.

The evaluators in :mod:`.prompt_probe` are pure. This module glues
them to real inputs:

- :class:`RecognitionSample` bundles a composed prompt, a model
  response, and the caller's :class:`ExpectedResponse` so a batch of
  offline samples can be scored in one shot,
- :func:`score_batch` is the pure aggregate that turns a sample list
  into a :class:`RecognitionRunReport` (per-sample results + KPI
  summary),
- :class:`RecognitionScenario` names a live scenario (capability +
  optional scope + expected contract) that the composer can compose
  and a :class:`ScenarioResponder` implementation can answer,
- :func:`run_scenarios` composes each scenario, delegates to the
  injected responder, then reuses :func:`score_batch` for the
  aggregate.

Wave 3 step D-2b-ii-alpha ships the runtime API without any I/O
providers or YAML fixture format; step D-2b-ii-beta adds the on-disk
scenario catalog + CLI, step D-2b-ii-gamma emits KPI dashboard rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fdai.core.measurement.prompt_probe import (
    ExpectedResponse,
    RecognitionKpiSummary,
    RecognitionResult,
    score_recognition,
    summarize_recognition,
)
from fdai.core.operator_memory import OperatorScope
from fdai.core.prompts.composer import PromptComposer
from fdai.core.prompts.types import ComposedPrompt

# ---------------------------------------------------------------------------
# Batch scoring surface (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecognitionSample:
    """One end-to-end sample ready to score.

    ``composed_prompt`` is the exact :class:`ComposedPrompt` the model
    was invoked with (so canary tokens the composer stamped are
    available for echo scoring). ``response_json`` is ``None`` when
    the raw response failed to parse as JSON; ``response_text`` is
    the untouched string the canary probe scans.

    ``expected`` carries the caller's ground truth
    (:class:`RequiredField` list + optional expected rule ids +
    optional canary tokens). When the composer stamped its own
    canaries and the caller did not supply any in ``expected``,
    :func:`score_batch` uses the composer's tokens automatically -
    the intended path when the runner is scoring a live composer.
    """

    composed_prompt: ComposedPrompt
    response_json: Mapping[str, Any] | None
    response_text: str
    expected: ExpectedResponse


@dataclass(frozen=True, slots=True)
class RecognitionRunReport:
    """Everything one batch produces: per-sample results + KPI summary.

    Callers that want to publish dashboard rows look at
    :attr:`summary`; callers that need to attribute failures to a
    specific scenario iterate :attr:`samples`. The two are always
    kept in lockstep so a KPI never diverges from the rows that
    produced it.
    """

    samples: tuple[RecognitionResult, ...]
    summary: RecognitionKpiSummary


def score_batch(samples: Sequence[RecognitionSample]) -> RecognitionRunReport:
    """Score every sample and return the aggregate report.

    When the caller left ``sample.expected.canary_tokens`` unset AND
    the composer stamped tokens onto ``sample.composed_prompt``, the
    scorer promotes the composer tokens into the expected contract.
    That way a scenario author does not have to duplicate the canary
    mapping the composer already knows about - the runner keeps the
    single source of truth on :class:`ComposedPrompt`.
    """

    results = tuple(_score_sample(sample) for sample in samples)
    summary = summarize_recognition(results)
    return RecognitionRunReport(samples=results, summary=summary)


def _score_sample(sample: RecognitionSample) -> RecognitionResult:
    canaries = sample.expected.canary_tokens
    if not canaries and sample.composed_prompt.canary_tokens:
        canaries = sample.composed_prompt.canary_tokens
    expected = ExpectedResponse(
        required_fields=sample.expected.required_fields,
        expected_cited_rule_ids=sample.expected.expected_cited_rule_ids,
        canary_tokens=canaries,
    )
    return score_recognition(
        expected=expected,
        response_json=sample.response_json,
        response_text=sample.response_text,
    )


# ---------------------------------------------------------------------------
# Live scenario runner
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecognitionScenario:
    """The composable+scorable half of a scenario fixture.

    ``id`` uniquely identifies the scenario for reporting rows;
    ``capability_id`` selects which composer capability to compose
    (e.g. ``t2.reasoner.primary``); ``scope`` is optional and threads
    through to the operator-memory layer resolver; ``expected`` is
    the ground truth to score the model response against.

    The scenario intentionally does NOT carry the raw response - a
    scenario is a specification, and the responder is what runs live
    inference.
    """

    id: str
    capability_id: str
    scope: OperatorScope | None
    expected: ExpectedResponse


class ScenarioResponder(Protocol):
    """The seam :func:`run_scenarios` uses to obtain a live response.

    A fork wires a real model here; tests provide a canned responder
    (see :class:`fdai.core.measurement.prompt_probe_runner_testing`).
    The responder receives the composed prompt so it does NOT need to
    know about the composer; keeping the boundary here makes
    upstream ship a real end-to-end runner without a fork's model.
    """

    async def respond(
        self, *, composed_prompt: ComposedPrompt, capability_id: str
    ) -> tuple[Mapping[str, Any] | None, str]:
        """Return ``(parsed_json_or_None, raw_response_text)`` for the prompt.

        The tuple mirrors the two-input contract of
        :func:`score_recognition`. Returning ``None`` for the JSON
        part signals "response could not be parsed" - the scorer
        counts that as an aggregate ``not-a-json-object`` violation.
        """


async def run_scenarios(
    *,
    composer: PromptComposer,
    responder: ScenarioResponder,
    scenarios: Sequence[RecognitionScenario],
) -> RecognitionRunReport:
    """Compose every scenario, delegate to the responder, and aggregate.

    The runner uses each scenario's ``capability_id`` + ``scope`` to
    call ``composer.compose(...)``; the composer's returned canary
    tokens flow through :func:`_score_sample` so the caller does not
    need to duplicate them in the scenario definition.
    """

    samples: list[RecognitionSample] = []
    for scenario in scenarios:
        composed = await composer.compose(
            capability_id=scenario.capability_id, scope=scenario.scope
        )
        response_json, response_text = await responder.respond(
            composed_prompt=composed, capability_id=scenario.capability_id
        )
        samples.append(
            RecognitionSample(
                composed_prompt=composed,
                response_json=response_json,
                response_text=response_text,
                expected=scenario.expected,
            )
        )
    return score_batch(samples)


__all__ = [
    "RecognitionRunReport",
    "RecognitionSample",
    "RecognitionScenario",
    "ScenarioResponder",
    "run_scenarios",
    "score_batch",
]
