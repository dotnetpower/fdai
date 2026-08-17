"""Focused catalog and provider tests for deterministic subscription identity reads."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fdai_operator_service.adapters.subscription_scope import (
    ARM_AUDIENCE,
    ARM_RESOURCE,
    AzureSubscriptionScopeProvider,
    SubscriptionScopeEvidence,
    SubscriptionScopeProviderError,
    load_subscription_scope_intent_catalog,
)
from fdai_operator_service.families.conversation.contracts import (
    ConversationProposal,
    PrincipalScope,
)
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_operator_service.families.conversation.subscription_scope import (
    SubscriptionScopeResponder,
)

_SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000001"
_NOW = datetime(2026, 8, 17, 6, 0, tzinfo=UTC)
_CATALOG = (
    Path(__file__).parents[3] / "rule-catalog" / "vocabulary" / "inventory-query-language.yaml"
)


def test_arm_identity_uses_distinct_cli_resource_and_managed_identity_scope() -> None:
    assert ARM_RESOURCE == "https://management.azure.com/"
    assert ARM_AUDIENCE == f"{ARM_RESOURCE}.default"


@pytest.mark.parametrize(
    "utterance",
    (
        "What is the current Azure subscription information?",
        "Show the active subscription.",
        "현재 구독 정보 알려줘",
        "사용 중인 Azure 구독 보여줘",
        "현재 구독은?",
        "현재 구독 정보가 뭐야?",
        "What is the current subscription?",
    ),
)
def test_catalog_matches_subscription_identity_reads(utterance: str) -> None:
    catalog = load_subscription_scope_intent_catalog(_CATALOG)

    assert catalog.matches(utterance)


@pytest.mark.parametrize(
    "utterance",
    (
        "현재 구독 상태 점검해줘",
        "Check the active subscription health.",
        "Delete the current subscription.",
        "List resources in the subscription.",
        "What is T2?",
    ),
)
def test_catalog_rejects_health_mutation_and_other_reads(utterance: str) -> None:
    catalog = load_subscription_scope_intent_catalog(_CATALOG)

    assert not catalog.matches(utterance)


async def test_provider_returns_masked_verified_subscription_evidence() -> None:
    audiences: list[str] = []

    async def token_provider(audience: str) -> str:
        audiences.append(audience)
        return "token"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        assert request.url.params["api-version"] == "2022-12-01"
        return httpx.Response(
            200,
            json={
                "subscriptionId": _SUBSCRIPTION_ID,
                "displayName": "Example subscription",
                "state": "Enabled",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AzureSubscriptionScopeProvider(
            subscription_id=_SUBSCRIPTION_ID,
            token_provider=token_provider,
            http_client=client,
            now=lambda: _NOW,
        ).read()

    assert audiences == [ARM_AUDIENCE]
    assert result.display_name == "Example subscription"
    assert result.state == "Enabled"
    assert result.masked_subscription_id == "0000...0001"
    assert result.observed_at == _NOW
    assert result.evidence_ref.startswith("azure-subscription:")
    assert _SUBSCRIPTION_ID not in result.evidence_ref
    assert result.execution_authority is False


async def test_provider_hides_mismatched_scope_and_provider_details() -> None:
    async def token_provider(_audience: str) -> str:
        return "token"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "subscriptionId": "00000000-0000-0000-0000-000000000002",
                "displayName": "Wrong subscription",
                "state": "Enabled",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionScopeProvider(
            subscription_id=_SUBSCRIPTION_ID,
            token_provider=token_provider,
            http_client=client,
        )
        with pytest.raises(
            SubscriptionScopeProviderError,
            match="subscription scope evidence is unavailable",
        ) as raised:
            await provider.read()

    assert "Wrong subscription" not in str(raised.value)


async def test_provider_coalesces_concurrent_reads_and_caches_verified_evidence() -> None:
    calls = 0

    async def token_provider(_audience: str) -> str:
        return "token"

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "subscriptionId": _SUBSCRIPTION_ID,
                "displayName": "Example subscription",
                "state": "Enabled",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AzureSubscriptionScopeProvider(
            subscription_id=_SUBSCRIPTION_ID,
            token_provider=token_provider,
            http_client=client,
            now=lambda: _NOW,
        )
        first, second = await asyncio.gather(provider.read(), provider.read())
        third = await provider.read()

    assert calls == 1
    assert first == second == third


async def test_provider_converts_token_failures_to_typed_unavailability() -> None:
    async def token_provider(_audience: str) -> str:
        raise RuntimeError("credential detail")

    async with httpx.AsyncClient() as client:
        provider = AzureSubscriptionScopeProvider(
            subscription_id=_SUBSCRIPTION_ID,
            token_provider=token_provider,
            http_client=client,
        )
        with pytest.raises(SubscriptionScopeProviderError) as raised:
            await provider.read()

    assert "credential detail" not in str(raised.value)


class _EvidenceProvider:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.calls = 0
        self.unavailable = unavailable

    async def read(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.unavailable:
            raise SubscriptionScopeProviderError("hidden provider detail")
        return type(
            "Evidence",
            (),
            {
                "display_name": "Example subscription",
                "state": "Enabled",
                "masked_subscription_id": "0000...0001",
                "observed_at": _NOW,
                "evidence_ref": "azure-subscription:sha256-example",
                "receipt_digest": f"sha256:{'a' * 64}",
            },
        )()


def _envelope(prompt: str, *, locale: str = "en") -> dict[str, object]:
    return SemanticTurnEnvelopeBuilder(clock=lambda: datetime.now(UTC)).build(
        ConversationProposal(
            operation="chat.stream",
            scope=PrincipalScope("operator-1", frozenset({"Reader"})),
            idempotency_key=f"scope-{locale}",
            body={"prompt": prompt, "locale": locale},
        )
    )


async def test_responder_projects_verified_korean_answer_without_model_route() -> None:
    provider = _EvidenceProvider()
    responder = SubscriptionScopeResponder(
        catalog=load_subscription_scope_intent_catalog(_CATALOG),
        provider=provider,
    )
    envelope = _envelope("현재 구독 정보 알려줘", locale="ko")

    projection = await responder.respond(envelope)
    result = projection["semantic_result"]

    assert provider.calls == 1
    assert projection["schema_version"] == "operator-deterministic-1.0.0"
    assert projection["status"] == "answered"
    assert result["semantic_route"] == "deterministic_read"
    assert result["checks_completed"] == 1
    assert result["checks_total"] == 1
    assert result["deterministic_receipt_digest"] == f"sha256:{'a' * 64}"
    assert "현재 Azure 구독" in result["answer"]
    assert "0000...0001" in result["answer"]


async def test_responder_holds_provider_failure_without_semantic_fallback() -> None:
    provider = _EvidenceProvider(unavailable=True)
    responder = SubscriptionScopeResponder(
        catalog=load_subscription_scope_intent_catalog(_CATALOG),
        provider=provider,
    )

    projection = await responder.respond(_envelope("Show the active subscription."))
    result = projection["semantic_result"]

    assert provider.calls == 1
    assert projection["status"] == "held"
    assert result["reason_code"] == "subscription_scope_unavailable"
    assert result["unavailable_reason"] == "authoritative_evidence_unavailable"
    assert "hidden provider detail" not in result["answer"]


async def test_responder_holds_an_expired_turn_without_calling_provider() -> None:
    provider = _EvidenceProvider()
    envelope = _envelope("Show the active subscription.")
    semantic = envelope["semantic_turn"]
    semantic["deadline_at"] = "2026-08-17T05:59:59Z"

    projection = await SubscriptionScopeResponder(
        catalog=load_subscription_scope_intent_catalog(_CATALOG),
        provider=provider,
    ).respond(envelope)

    assert provider.calls == 0
    assert projection["status"] == "held"


async def test_responder_escapes_provider_markdown() -> None:
    provider = _EvidenceProvider()
    evidence = await provider.read()
    malicious = SubscriptionScopeEvidence(
        display_name="[click](https://example.invalid) **admin**",
        state="Enabled | injected",
        masked_subscription_id=evidence.masked_subscription_id,
        observed_at=evidence.observed_at,
        evidence_ref=evidence.evidence_ref,
        receipt_digest=evidence.receipt_digest,
    )

    class MaliciousProvider:
        async def read(self):  # type: ignore[no-untyped-def]
            return malicious

    projection = await SubscriptionScopeResponder(
        catalog=load_subscription_scope_intent_catalog(_CATALOG),
        provider=MaliciousProvider(),
    ).respond(_envelope("Show the active subscription."))
    answer = projection["semantic_result"]["answer"]

    assert "\\[click\\]\\(https://example\\.invalid\\)" in answer
    assert "\\*\\*admin\\*\\*" in answer
    assert "Enabled \\| injected" in answer
