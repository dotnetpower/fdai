"""Compose the second reader and the local compiled-answer path from the reviewed catalog."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fdai.composition import semantic_query_type_grounding as grounding
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    NarratorCandidate,
    ResolvedCapability,
    ResolvedModels,
)

_ROOT = Path(__file__).resolve().parents[4]
_ENDPOINT = "https://models.example.com"


def _resolved() -> ResolvedModels:
    return ResolvedModels(
        schema_version="1.0.0",
        region="example-region",
        subscription_id="00000000-0000-0000-0000-000000000000",
        deployer_object_id="00000000-0000-0000-0000-000000000000",
        mixed_model_mode="hil-only",
        capabilities=(
            ResolvedCapability(
                name="t1.judge",
                status=CapabilityStatus.RESOLVED,
                publisher="OpenAI",
                family="gpt-5.4-mini",
                sku="Standard",
                capacity_tpm=1000,
                invocation="always",
            ),
        ),
        narrator_candidates=tuple(
            NarratorCandidate(endpoint=_ENDPOINT, deployment=deployment)
            for deployment in (
                "narrator-gpt-5-4-mini",
                "narrator-gpt-4-1-mini",
                "narrator-gpt-5-mini",
            )
        ),
    )


@pytest.fixture
def owner_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _build(owner_loop: asyncio.AbstractEventLoop) -> Any:
    return grounding.build_second_reader(
        resolved=_resolved(),
        identity=SimpleNamespace(),  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(),
        endpoint=_ENDPOINT,
        endpoint_resolver=None,
        catalog_root=_ROOT / "rule-catalog",
        owner_loop=owner_loop,
    )


def test_the_local_profile_composes_the_compiled_path_with_a_reasoning_direction_reader(
    monkeypatch: pytest.MonkeyPatch, owner_loop: asyncio.AbstractEventLoop
) -> None:
    monkeypatch.setenv("FDAI_SEMANTIC_SECOND_READER", "1")
    monkeypatch.setenv("FDAI_SEMANTIC_COMPILED_ANSWERS", "1")
    monkeypatch.setenv("FDAI_EXECUTION_VENUE", "local")

    reader = _build(owner_loop)

    assert reader is not None and reader.compiled_answers is not None
    config = reader.type_grounding._chooser._config  # noqa: SLF001
    assert [target.deployment for target in config.direction_candidates] == ["narrator-gpt-5-mini"]
    assert config.direction_system_prompt
    assert config.direction_max_tokens == 2_048
    # The reasoning reader is a third family, so it also answers the closed ambiguity check.
    assert [target.deployment for target in config.ambiguity_candidates] == ["narrator-gpt-5-mini"]
    assert config.ambiguity_system_prompt and config.ambiguity_max_tokens == 2_048
    path = reader.compiled_answers(SimpleNamespace(), "operations-review", lambda: None)
    assert path._ambiguity_reader is reader.type_grounding._chooser  # noqa: SLF001


def test_without_a_third_family_no_ambiguity_reader_is_configured() -> None:
    targets = tuple(
        SimpleNamespace(deployment=name)
        for name in ("narrator-gpt-5-4-mini", "narrator-gpt-4-1-mini")
    )
    reasoning = SimpleNamespace(deployment="narrator-gpt-5-mini")

    # Two families only: the judgment's and the blind reviewer's.
    assert grounding.ambiguity_reader_target(targets, targets[1]) is None  # type: ignore[arg-type]
    # The reasoning reader is the reviewer itself, so it is no third family.
    assert (
        grounding.ambiguity_reader_target((targets[0], reasoning), reasoning)  # type: ignore[arg-type]
        is None
    )
    assert (
        grounding.ambiguity_reader_target((*targets, reasoning), targets[1])  # type: ignore[arg-type]
        is reasoning
    )


def test_a_deployed_venue_or_an_invalid_path_keeps_only_the_second_reader(
    monkeypatch: pytest.MonkeyPatch, owner_loop: asyncio.AbstractEventLoop
) -> None:
    monkeypatch.setenv("FDAI_SEMANTIC_SECOND_READER", "1")
    monkeypatch.setenv("FDAI_SEMANTIC_COMPILED_ANSWERS", "1")
    monkeypatch.setenv("FDAI_EXECUTION_VENUE", "deployed")
    deployed = _build(owner_loop)
    assert deployed is not None and deployed.compiled_answers is None

    monkeypatch.setenv("FDAI_EXECUTION_VENUE", "local")
    original = grounding.AzureOpenAIQuestionFormConfig

    def strict(**values: Any) -> Any:
        if values.get("direction_system_prompt") is not None:
            raise ValueError("question form output tokens exceed the prompt reserve")
        return original(**values)

    monkeypatch.setattr(grounding, "AzureOpenAIQuestionFormConfig", strict)
    fallback = _build(owner_loop)
    assert fallback is not None
    assert fallback.compiled_answers is None
    assert fallback.type_grounding is not None and fallback.coverage_review is not None
