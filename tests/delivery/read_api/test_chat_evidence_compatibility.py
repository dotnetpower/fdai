from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

import pytest

from fdai.agents import PantheonRuntime
from fdai.delivery.read_api.routes.chat_agent_delegate import PantheonChatDelegate
from fdai.delivery.read_api.routes.chat_evidence_enrichment import (
    _with_agent_evidence,
    _with_operational_evidence,
    _with_screen_scope,
    _with_web_evidence,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

CONTEXT = {
    "kind": "incident",
    "incident_id": "INC-1",
    "correlation_id": "corr-1",
}


class _LegacyResolver:
    async def resolve(self, prompt: str) -> dict[str, Any]:
        return {"status": "matched", "prompt": prompt}


class _ContextResolver:
    def __init__(self) -> None:
        self.context: dict[str, str] | None = None

    async def resolve(
        self,
        prompt: str,
        *,
        conversation_context: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        self.context = dict(conversation_context) if conversation_context is not None else None
        return {"status": "matched", "prompt": prompt}


class _KeywordResolver:
    def __init__(self) -> None:
        self.keywords: dict[str, object] = {}

    async def resolve(self, prompt: str, **kwargs: object) -> dict[str, Any]:
        self.keywords = kwargs
        return {"status": "matched", "prompt": prompt}


async def test_legacy_resolver_remains_compatible_with_bound_conversation() -> None:
    enriched = await _with_operational_evidence(
        "continue",
        {},
        _LegacyResolver(),  # type: ignore[arg-type]
        conversation_context=CONTEXT,
    )

    assert enriched["_operational_evidence"]["status"] == "matched"


async def test_context_aware_resolver_receives_exact_binding() -> None:
    resolver = _ContextResolver()

    await _with_operational_evidence(
        "continue",
        {},
        resolver,
        conversation_context=CONTEXT,
    )

    assert resolver.context == CONTEXT


async def test_trace_screen_correlation_becomes_exact_selection_hint() -> None:
    resolver = _ContextResolver()

    await _with_operational_evidence(
        "what caused the error?",
        {
            "routeId": "trace",
            "facts": [
                {"key": "load_status", "value": "error"},
                {"key": "correlation_id", "value": "corr-screen"},
            ],
        },
        resolver,
    )

    assert resolver.context == {
        "kind": "incident",
        "incident_id": "INC-corr-screen",
        "correlation_id": "corr-screen",
    }


async def test_selected_incident_title_becomes_exact_selection_hint() -> None:
    resolver = _ContextResolver()

    await _with_operational_evidence(
        "Resource inventory change - Storage account storage-example 이거는 어떤 상태인거야?",
        {
            "routeId": "incidents",
            "records": {
                "selected_incident": [
                    {
                        "incident_id": "incident-1",
                        "correlation_id": "corr-selected",
                        "title": "Resource inventory change - Storage account storage-example",
                    }
                ]
            },
        },
        resolver,
    )

    assert resolver.context == {
        "kind": "incident",
        "incident_id": "incident-1",
        "correlation_id": "corr-selected",
    }


async def test_selected_incident_without_lifecycle_id_uses_correlation_hint() -> None:
    resolver = _ContextResolver()

    await _with_operational_evidence(
        "이거는 어떤 상태인거야?",
        {
            "routeId": "incidents",
            "records": {
                "selected_incident": [
                    {
                        "incident_id": None,
                        "ticket_id": None,
                        "correlation_id": "corr-selected",
                        "title": "Selected incident",
                    }
                ]
            },
        },
        resolver,
    )

    assert resolver.context == {
        "kind": "incident",
        "incident_id": "INC-corr-selected",
        "correlation_id": "corr-selected",
    }


@pytest.mark.parametrize(
    "prompt",
    ("what was the terminal stage?", "who approved this trace?"),
)
async def test_trace_screen_fact_question_does_not_force_incident_lookup(prompt: str) -> None:
    resolver = _ContextResolver()

    enriched = await _with_operational_evidence(
        prompt,
        {
            "routeId": "trace",
            "facts": [
                {"key": "terminal_stage", "value": "audit"},
                {"key": "correlation_id", "value": "corr-screen"},
            ],
        },
        resolver,
    )

    assert resolver.context is None
    assert "_operational_evidence" not in enriched


async def test_explicit_binding_wins_over_trace_screen_hint() -> None:
    resolver = _ContextResolver()

    await _with_operational_evidence(
        "continue",
        {
            "routeId": "trace",
            "facts": [{"key": "correlation_id", "value": "corr-screen"}],
        },
        resolver,
        conversation_context=CONTEXT,
    )

    assert resolver.context == CONTEXT


async def test_variadic_keyword_resolver_receives_binding() -> None:
    resolver = _KeywordResolver()

    await _with_operational_evidence(
        "continue",
        {},
        resolver,
        conversation_context=CONTEXT,
    )

    assert resolver.keywords == {"conversation_context": CONTEXT}


async def test_resolver_internal_type_error_is_not_misclassified_as_legacy() -> None:
    class _FailingResolver(_ContextResolver):
        async def resolve(
            self,
            prompt: str,
            *,
            conversation_context: Mapping[str, str] | None = None,
        ) -> dict[str, Any]:
            raise TypeError("resolver defect")

    with pytest.raises(TypeError, match="resolver defect"):
        await _with_operational_evidence(
            "continue",
            {},
            _FailingResolver(),
            conversation_context=CONTEXT,
        )


async def test_uninspectable_resolver_uses_current_context_contract() -> None:
    resolver = _ContextResolver()

    with patch(
        "fdai.delivery.read_api.routes.chat_evidence_enrichment.signature",
        side_effect=ValueError("signature unavailable"),
    ):
        await _with_operational_evidence(
            "continue",
            {},
            resolver,
            conversation_context=CONTEXT,
        )

    assert resolver.context == CONTEXT


async def test_bragi_screen_scope_suppresses_agent_and_web_enrichment() -> None:
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
    )
    delegate = PantheonChatDelegate(runtime)
    context = {
        "routeId": "live",
        "facts": [{"key": "tier.t2", "value": "5%"}],
    }

    enriched = _with_screen_scope(
        "what is the T2 tier share?",
        context,
        delegate,
    )
    enriched = await _with_agent_evidence(
        "what is the T2 tier share?",
        enriched,
        delegate,
        user_id="operator-1",
        session_id="session-1",
    )

    class _WebResolver:
        calls = 0

        async def resolve(
            self,
            prompt: str,
            view_context: Mapping[str, Any],
        ) -> dict[str, Any]:
            del prompt, view_context
            self.calls += 1
            return {"status": "matched"}

    web = _WebResolver()
    enriched = await _with_web_evidence("what is the T2 tier share?", enriched, web)

    assert enriched["_screen_scope"]["authority"] == "current_screen"
    assert "_agent_evidence" not in enriched
    assert "_web_evidence" not in enriched
    assert web.calls == 0


def test_bragi_screen_scope_treats_empty_facts_as_authoritative_absence() -> None:
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
    )
    context = _with_screen_scope(
        "what is the eps?",
        {"routeId": "live", "facts": []},
        PantheonChatDelegate(runtime),
    )

    assert context["_screen_scope"]["authority"] == "current_screen"
