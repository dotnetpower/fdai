"""Prior-turn context yields, newest first, so a request fits its declared budget."""

from __future__ import annotations

import json

from fdai.delivery.azure.llm.request_context_fit import fit_context_to_budget

_FORMAT = {"type": "json_schema", "json_schema": {"name": "x", "schema": {"type": "object"}}}


def _encode(context: tuple[str, ...]) -> str:
    return json.dumps(
        {"untrusted_input": {"utterance": "그 중에 컨테이너 앱만", "context": context}}
    )


def _fit(context: tuple[str, ...], budget: int | None) -> tuple[str, ...]:
    return fit_context_to_budget(
        context,
        encode=_encode,
        system_prompt="system",
        response_format=_FORMAT,
        reserved_output_tokens=100,
        budget=budget,
        call_kind="semantic-judgment",
    )


def test_context_that_fits_is_unchanged() -> None:
    context = ("inbound:a", "outbound:b")

    assert _fit(context, budget=100_000) == context
    assert _fit(context, budget=None) == context


def test_oldest_context_yields_first_and_the_newest_is_kept() -> None:
    context = ("inbound:" + "가" * 4000, "outbound:" + "나" * 4000, "inbound:recent question")
    whole = _fit(context, budget=None)
    budget = len(_encode(context[-1:]).encode()) + 2_000

    fitted = _fit(context, budget=budget)

    assert whole == context
    assert fitted[-1] == "inbound:recent question"
    assert len(fitted) <= len(context)
    assert all(item in context or context[1].startswith(item) for item in fitted)


def test_a_single_oversized_newest_item_is_shortened_not_lost() -> None:
    context = ("outbound:" + "나" * 20_000,)
    budget = 12_000

    fitted = _fit(context, budget=budget)

    assert len(fitted) == 1
    assert context[0].startswith(fitted[0])
    assert 64 <= len(fitted[0]) < len(context[0])
