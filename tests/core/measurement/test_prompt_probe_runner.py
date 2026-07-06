"""Unit tests for :mod:`aiopspilot.core.measurement.prompt_probe_runner`.

Two suites: :class:`TestScoreBatch` covers the pure aggregate that
turns pre-composed samples into a run report; :class:`TestRunScenarios`
covers the live runner that couples a composer to a responder.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from aiopspilot.core.measurement.prompt_probe import (
    ExpectedResponse,
    RequiredField,
)
from aiopspilot.core.measurement.prompt_probe_runner import (
    RecognitionSample,
    RecognitionScenario,
    run_scenarios,
    score_batch,
)
from aiopspilot.core.operator_memory import OperatorScope
from aiopspilot.core.prompts.testing import StaticPromptComposer
from aiopspilot.core.prompts.types import ComposedPrompt, LayerRef, PromptLayer


def _composed(
    *,
    system_text: str = "sys",
    canary_tokens: Mapping[str, str] | None = None,
    layers: tuple[str, ...] = ("base",),
) -> ComposedPrompt:
    manifest = tuple(
        LayerRef(id=layer_id, version=1, layer=PromptLayer.BASE, token_estimate=1)
        for layer_id in layers
    )
    return ComposedPrompt(
        system_text=system_text,
        layer_manifest=manifest,
        token_estimate=len(system_text) // 4 or 1,
        canary_tokens=canary_tokens or {},
    )


def _sample(
    *,
    composed: ComposedPrompt,
    response_json: Mapping[str, Any] | None,
    response_text: str,
    expected: ExpectedResponse,
) -> RecognitionSample:
    return RecognitionSample(
        composed_prompt=composed,
        response_json=response_json,
        response_text=response_text,
        expected=expected,
    )


class TestScoreBatch:
    """Pure aggregation tests - no composer, no responder."""

    def test_empty_batch_returns_neutral_report(self) -> None:
        report = score_batch([])
        assert report.samples == ()
        assert report.summary.sample_count == 0
        assert report.summary.mean_citation_f1 is None

    def test_batch_scores_every_sample(self) -> None:
        expected = ExpectedResponse(
            required_fields=(RequiredField("action_type", "string"),),
        )
        samples = [
            _sample(
                composed=_composed(),
                response_json={"action_type": "noop", "params": {}},
                response_text="ok",
                expected=expected,
            ),
            _sample(
                composed=_composed(),
                response_json={"params": {}},  # missing action_type
                response_text="",
                expected=expected,
            ),
        ]
        report = score_batch(samples)
        assert len(report.samples) == 2
        assert report.summary.adherence_pass_rate == pytest.approx(0.5)
        assert report.summary.adherence_violation_counts == {"missing-field:action_type": 1}

    def test_composer_canaries_promoted_when_expected_omits_them(self) -> None:
        """When the caller left ``expected.canary_tokens`` unset AND the
        composer stamped tokens, the batch scorer MUST use the
        composer tokens - scenario authors would otherwise have to
        duplicate the canary map, and drift between the two would
        silently break echo scoring."""

        composed = _composed(canary_tokens={"base": "CN_ABC"})
        expected_no_canaries = ExpectedResponse(
            required_fields=(RequiredField("action_type", "string"),),
        )
        report = score_batch(
            [
                _sample(
                    composed=composed,
                    response_json={"action_type": "noop", "params": {}},
                    response_text="response body carrying CN_ABC token",
                    expected=expected_no_canaries,
                ),
            ]
        )
        # The composer's canary was echoed and scored.
        assert report.summary.per_layer_canary_echo_rate == {"base": 1.0}

    def test_explicit_canaries_on_expected_override_composer_tokens(self) -> None:
        """A scenario author that pins canary tokens on ``expected``
        SHOULD get scored against those, not the composer's - useful
        for regression fixtures where the composer might change but
        the expected canary stays pinned to the original run."""

        composed = _composed(canary_tokens={"base": "CN_COMPOSER"})
        pinned = ExpectedResponse(
            required_fields=(RequiredField("action_type", "string"),),
            canary_tokens={"base": "CN_PINNED"},
        )
        report = score_batch(
            [
                _sample(
                    composed=composed,
                    response_json={"action_type": "noop", "params": {}},
                    response_text="response carrying CN_PINNED but not CN_COMPOSER",
                    expected=pinned,
                ),
            ]
        )
        # Pinned token was found; the composer token was NOT scored.
        assert report.summary.per_layer_canary_echo_rate == {"base": 1.0}

    def test_batch_summary_uses_measured_canary_denominator(self) -> None:
        """A layer measured on only some samples MUST use that
        denominator - the aggregate MUST NOT falsely dilute an echo
        rate for a layer that half the batch never carried."""

        exp = ExpectedResponse(
            required_fields=(RequiredField("action_type", "string"),),
        )
        one = _sample(
            composed=_composed(canary_tokens={"base": "CN_A", "tool-manifest": "CN_T"}),
            response_json={"action_type": "noop", "params": {}},
            response_text="carries CN_A only",
            expected=exp,
        )
        two = _sample(
            composed=_composed(canary_tokens={"base": "CN_B"}),
            response_json={"action_type": "noop", "params": {}},
            response_text="carries CN_B",
            expected=exp,
        )
        report = score_batch([one, two])
        # base measured in both, echoed in both -> 1.0
        assert report.summary.per_layer_canary_echo_rate["base"] == pytest.approx(1.0)
        # tool-manifest measured in one, echoed in zero -> 0.0 (not 0.5)
        assert report.summary.per_layer_canary_echo_rate["tool-manifest"] == pytest.approx(0.0)


class _CannedResponder:
    """Test responder that returns pre-registered responses per capability."""

    def __init__(
        self,
        responses: Mapping[str, tuple[Mapping[str, Any] | None, str]],
    ) -> None:
        self._responses = dict(responses)
        self.calls: list[tuple[str, str]] = []

    async def respond(
        self,
        *,
        composed_prompt: ComposedPrompt,
        capability_id: str,
    ) -> tuple[Mapping[str, Any] | None, str]:
        self.calls.append((capability_id, composed_prompt.system_text))
        if capability_id not in self._responses:
            raise KeyError(f"no canned response for capability {capability_id!r}")
        return self._responses[capability_id]


class TestRunScenarios:
    """Live-runner tests - composer + responder are both fakes."""

    @pytest.mark.asyncio
    async def test_runs_every_scenario_and_returns_aggregate(self) -> None:
        composer = StaticPromptComposer("canned prompt text")
        responder = _CannedResponder(
            {
                "t2.reasoner.primary": (
                    {"action_type": "ok", "params": {}},
                    "response text",
                ),
                "t2.reasoner.secondary": (
                    {"action_type": "ok", "params": {}},
                    "response text 2",
                ),
            }
        )
        expected = ExpectedResponse(
            required_fields=(RequiredField("action_type", "string"),),
        )
        scenarios = [
            RecognitionScenario(
                id="s1",
                capability_id="t2.reasoner.primary",
                scope=None,
                expected=expected,
            ),
            RecognitionScenario(
                id="s2",
                capability_id="t2.reasoner.secondary",
                scope=None,
                expected=expected,
            ),
        ]

        report = await run_scenarios(composer=composer, responder=responder, scenarios=scenarios)

        assert report.summary.sample_count == 2
        assert report.summary.adherence_pass_rate == pytest.approx(1.0)
        # Both capability ids were routed through the composer + responder.
        assert [c[0] for c in responder.calls] == [
            "t2.reasoner.primary",
            "t2.reasoner.secondary",
        ]
        # StaticPromptComposer recorded a call per scenario, preserving scope.
        assert composer.calls == [
            ("t2.reasoner.primary", None),
            ("t2.reasoner.secondary", None),
        ]

    @pytest.mark.asyncio
    async def test_scope_is_threaded_to_composer(self) -> None:
        """The runner MUST pass each scenario's ``scope`` through to the
        composer verbatim so a scope-bound operator-memory layer is
        actually reachable by the recognition run."""

        composer = StaticPromptComposer("canned")
        responder = _CannedResponder(
            {"t2.reasoner.primary": ({"action_type": "ok", "params": {}}, "ok")}
        )
        scope = OperatorScope(resource_group_ref="rg-prod", resource_ref="res-1")
        scenarios = [
            RecognitionScenario(
                id="scoped",
                capability_id="t2.reasoner.primary",
                scope=scope,
                expected=ExpectedResponse(
                    required_fields=(RequiredField("action_type", "string"),),
                ),
            ),
        ]

        await run_scenarios(composer=composer, responder=responder, scenarios=scenarios)

        assert composer.calls == [("t2.reasoner.primary", scope)]

    @pytest.mark.asyncio
    async def test_empty_scenarios_returns_neutral_report(self) -> None:
        composer = StaticPromptComposer("unused")
        responder = _CannedResponder({})

        report = await run_scenarios(composer=composer, responder=responder, scenarios=[])

        assert report.samples == ()
        assert report.summary.sample_count == 0
        assert composer.calls == []
        assert responder.calls == []

    @pytest.mark.asyncio
    async def test_non_json_response_scores_as_adherence_failure(self) -> None:
        composer = StaticPromptComposer("canned")
        responder = _CannedResponder({"t2.reasoner.primary": (None, "raw unparseable text")})
        scenarios = [
            RecognitionScenario(
                id="bad-response",
                capability_id="t2.reasoner.primary",
                scope=None,
                expected=ExpectedResponse(
                    required_fields=(RequiredField("action_type", "string"),),
                ),
            ),
        ]

        report = await run_scenarios(composer=composer, responder=responder, scenarios=scenarios)

        assert report.summary.adherence_pass_rate == pytest.approx(0.0)
        assert report.summary.adherence_violation_counts == {"not-a-json-object": 1}
