from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from fdai.core.metering import InMemoryMeteringSink, PricingTable, TokenUsage
from fdai.delivery.operator_api.adapters.conversation.factory import (
    _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS,
    _chat_metering,
    _narrator_turn_timeout_seconds,
    _resolve_disk_azure_backend,
    _resolved_model_keys,
)
from fdai.delivery.operator_api.application.conversation.backend import (
    LatencyRoutedChatBackend,
    describe_backend,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        (None, _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS),
        ("invalid", _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS),
        ("0", _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS),
        ("301", _DEFAULT_NARRATOR_TURN_TIMEOUT_SECONDS),
        ("45", 45.0),
        ("1.5", 1.5),
    ),
)
def test_narrator_turn_timeout_is_bounded(raw: str | None, expected: float) -> None:
    env = {} if raw is None else {"FDAI_NARRATOR_TURN_TIMEOUT_SECONDS": raw}

    assert _narrator_turn_timeout_seconds(env) == expected


async def test_chat_metering_prices_explicit_resolved_family() -> None:
    sink = InMemoryMeteringSink()
    pricing = PricingTable.from_mapping(
        {
            "gpt-4o-mini": {
                "input_per_1k": "0.15",
                "output_per_1k": "0.60",
                "currency": "USD",
            }
        }
    )
    model_keys = _resolved_model_keys(
        {
            "capabilities": [
                {"name": "narrator-gpt-4o-mini", "family": "gpt-4o-mini"},
            ]
        }
    )

    emitter = _chat_metering(
        sink,
        "narrator-gpt-4o-mini",
        pricing=pricing,
        resolved_model_keys=model_keys,
    )
    assert emitter is not None
    await emitter.emit_safe(TokenUsage(prompt_tokens=1_000, completion_tokens=500))

    (record,) = await sink.invocations()
    assert record.capability_id == "t1.judge"
    assert record.model_key == "gpt-4o-mini"
    assert record.cost == Decimal("0.45")
    assert record.currency == "USD"


async def test_chat_metering_does_not_guess_missing_family() -> None:
    sink = InMemoryMeteringSink()
    pricing = PricingTable.from_mapping(
        {
            "gpt-4o-mini": {
                "input_per_1k": "0.15",
                "output_per_1k": "0.60",
            }
        }
    )

    emitter = _chat_metering(
        sink,
        "narrator-gpt-4o-mini",
        pricing=pricing,
        resolved_model_keys={},
    )
    assert emitter is not None
    await emitter.emit_safe(TokenUsage(prompt_tokens=1_000, completion_tokens=500))

    (record,) = await sink.invocations()
    assert record.model_key == "narrator-gpt-4o-mini"
    assert record.cost is None
    assert record.currency is None


def test_resolved_model_keys_reject_conflicting_families() -> None:
    model_keys = _resolved_model_keys(
        {
            "capabilities": [
                {"name": "narrator-shared", "family": "gpt-4o-mini"},
                {"name": "narrator-shared", "family": "gpt-5-mini"},
            ]
        }
    )

    assert model_keys == {}


async def test_chat_metering_can_attribute_vision_capability() -> None:
    sink = InMemoryMeteringSink()
    emitter = _chat_metering(
        sink,
        "vision-gpt",
        capability_id="t1.vision",
    )
    assert emitter is not None

    await emitter.emit_safe(TokenUsage(prompt_tokens=10, completion_tokens=5))

    (record,) = await sink.invocations()
    assert record.capability_id == "t1.vision"


def test_resolved_artifact_binds_a_separate_vision_pool(tmp_path: Path) -> None:
    endpoint = "https://example.openai.azure.com/"

    def candidate(deployment: str) -> dict[str, str]:
        return {
            "endpoint": endpoint,
            "deployment": deployment,
            "api_version": "2024-08-01-preview",
        }

    path = tmp_path / "resolved-models.json"
    path.write_text(
        json.dumps(
            {
                "narrator_candidates": [candidate("text-a"), candidate("text-b")],
                "vision_candidates": [candidate("text-a"), candidate("text-b")],
            }
        ),
        encoding="utf-8",
    )

    backend = _resolve_disk_azure_backend({"LLM_RESOLVED_MODELS_PATH": str(path)})

    assert isinstance(backend, LatencyRoutedChatBackend)
    vision = backend.vision_backend()
    assert isinstance(vision, LatencyRoutedChatBackend)
    assert vision.candidate_names() == ("text-a", "text-b")
    descriptor = describe_backend(backend)
    assert descriptor["router"]["vision"] == {
        "available": True,
        "chose": "text-a",
        "candidates": vision.stats(),
    }


def test_single_narrator_binds_a_separate_vision_backend(tmp_path: Path) -> None:
    endpoint = "https://example.openai.azure.com/"
    candidate = {
        "endpoint": endpoint,
        "deployment": "shared-mini",
        "api_version": "2024-08-01-preview",
    }
    path = tmp_path / "resolved-models.json"
    path.write_text(
        json.dumps(
            {
                "narrator": candidate,
                "narrator_candidates": [candidate],
                "vision_candidates": [candidate],
            }
        ),
        encoding="utf-8",
    )

    backend = _resolve_disk_azure_backend({"LLM_RESOLVED_MODELS_PATH": str(path)})

    assert isinstance(backend, LatencyRoutedChatBackend)
    assert backend.candidate_names() == ("shared-mini",)
    vision = backend.vision_backend()
    assert isinstance(vision, LatencyRoutedChatBackend)
    assert vision.candidate_names() == ("shared-mini",)


def test_runtime_rejects_vision_route_that_does_not_reuse_narrator(tmp_path: Path) -> None:
    endpoint = "https://example.openai.azure.com/"
    narrator = {
        "endpoint": endpoint,
        "deployment": "shared-mini",
        "api_version": "2024-08-01-preview",
    }
    conflicting = {**narrator, "endpoint": "https://other.example.com/"}
    path = tmp_path / "resolved-models.json"
    path.write_text(
        json.dumps(
            {
                "narrator_candidates": [narrator, {**narrator, "deployment": "text-b"}],
                "vision_candidates": [conflicting],
            }
        ),
        encoding="utf-8",
    )

    backend = _resolve_disk_azure_backend({"LLM_RESOLVED_MODELS_PATH": str(path)})

    assert isinstance(backend, LatencyRoutedChatBackend)
    assert backend.vision_backend() is None
