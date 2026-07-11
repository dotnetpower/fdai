"""httpx-mocked tests for :class:`AzureOpenAIRubricEvaluator`."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.quality_gate.rubric import RubricCriterion, RubricOutput
from fdai.delivery.azure.llm.rubric import (
    AzureOpenAIRubricEvaluator,
    AzureOpenAIRubricEvaluatorConfig,
)
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity

_TEST_SYSTEM_PROMPT = "unit-test rubric system prompt"


class _StaticIdentity(WorkloadIdentity):
    def __init__(self, token: str = "test-token") -> None:  # noqa: S107 - fake token, not a secret
        self._token = token

    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token=self._token,
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


def _mock_transport(content: str, *, captured: list[httpx.Request]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": content}}]},
        )

    return httpx.MockTransport(handler)


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/x",
        params={"tag_name": "owner", "tag_value": "team-a"},
        cited_rule_ids=("object-storage.owner-tag.required",),
        reasoning_trace="The bucket lacks the owner tag; the cited rule requires it.",
    )


def _config(**kw: object) -> AzureOpenAIRubricEvaluatorConfig:
    base: dict[str, object] = {
        "endpoint": "https://oai-test.openai.azure.com",
        "deployment": "t2-rubric",
        "system_prompt": _TEST_SYSTEM_PROMPT,
    }
    base.update(kw)
    return AzureOpenAIRubricEvaluatorConfig(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_config_rejects_non_https_endpoint() -> None:
    with pytest.raises(ValueError, match="https"):
        AzureOpenAIRubricEvaluator(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=_config(endpoint="ftp://x"),
        )


def test_config_rejects_empty_system_prompt() -> None:
    with pytest.raises(ValueError, match="system_prompt"):
        AzureOpenAIRubricEvaluator(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=_config(system_prompt=""),
        )


def test_config_rejects_out_of_range_default_threshold() -> None:
    with pytest.raises(ValueError, match="default_threshold"):
        AzureOpenAIRubricEvaluator(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=_config(default_threshold=1.5),
        )


def test_config_rejects_out_of_range_per_criterion_threshold() -> None:
    with pytest.raises(ValueError, match="threshold for"):
        AzureOpenAIRubricEvaluator(
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            config=_config(thresholds={"faithfulness": 2.0}),
        )


# ---------------------------------------------------------------------------
# Successful parsing + threshold injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_parses_and_injects_thresholds() -> None:
    captured: list[httpx.Request] = []
    payload = {
        "scores": [
            {
                "criterion": RubricCriterion.FAITHFULNESS.value,
                "score": 0.9,
                "rationale": "all claims supported",
                "supporting_rule_ids": ["object-storage.owner-tag.required"],
            },
            {
                "criterion": RubricCriterion.COMPLETENESS.value,
                "score": 0.6,
                "rationale": "rollback mentioned, blast radius not",
                "supporting_rule_ids": [],
            },
        ]
    }
    transport = _mock_transport(json.dumps(payload), captured=captured)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIRubricEvaluator(
            identity=_StaticIdentity(),
            http_client=http,
            config=_config(default_threshold=0.7, thresholds={"completeness": 0.5}),
        )
        out = await adapter.score(_candidate())
    assert isinstance(out, RubricOutput)
    assert len(out.scores) == 2
    by_crit = {s.criterion: s for s in out.scores}
    # Threshold is injected from config, NOT from the model.
    assert by_crit["faithfulness"].threshold == pytest.approx(0.7)
    assert by_crit["completeness"].threshold == pytest.approx(0.5)
    assert by_crit["completeness"].passed is True  # 0.6 >= 0.5
    # The reasoning_trace is forwarded to the model.
    sent = json.loads(captured[0].content)
    assert "reasoning_trace" in sent["messages"][1]["content"]


# ---------------------------------------------------------------------------
# Fail-closed parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_raises_on_non_json() -> None:
    transport = _mock_transport("not json", captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIRubricEvaluator(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="non-JSON"):
            await adapter.score(_candidate())


@pytest.mark.asyncio
async def test_score_raises_on_missing_scores_array() -> None:
    transport = _mock_transport(json.dumps({"verdict": "pass"}), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIRubricEvaluator(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="'scores' array"):
            await adapter.score(_candidate())


@pytest.mark.asyncio
async def test_score_raises_on_non_numeric_score() -> None:
    payload = {
        "scores": [
            {"criterion": "faithfulness", "score": "high", "rationale": "x"},
        ]
    }
    transport = _mock_transport(json.dumps(payload), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIRubricEvaluator(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="'score' MUST be a number"):
            await adapter.score(_candidate())


@pytest.mark.asyncio
async def test_score_raises_on_blank_rationale() -> None:
    payload = {
        "scores": [
            {"criterion": "faithfulness", "score": 0.9, "rationale": "  "},
        ]
    }
    transport = _mock_transport(json.dumps(payload), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIRubricEvaluator(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="rationale"):
            await adapter.score(_candidate())


@pytest.mark.asyncio
async def test_score_raises_on_bad_supporting_ids() -> None:
    payload = {
        "scores": [
            {
                "criterion": "faithfulness",
                "score": 0.9,
                "rationale": "ok",
                "supporting_rule_ids": [123],
            },
        ]
    }
    transport = _mock_transport(json.dumps(payload), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIRubricEvaluator(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="supporting_rule_ids"):
            await adapter.score(_candidate())


@pytest.mark.asyncio
async def test_score_out_of_range_raises_at_type_boundary() -> None:
    # A score > 1.0 is caught by RubricScore.__post_init__.
    payload = {
        "scores": [
            {"criterion": "faithfulness", "score": 1.4, "rationale": "ok"},
        ]
    }
    transport = _mock_transport(json.dumps(payload), captured=[])
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = AzureOpenAIRubricEvaluator(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(ValueError, match="score MUST be in"):
            await adapter.score(_candidate())
