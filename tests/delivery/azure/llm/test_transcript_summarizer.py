"""httpx-mocked tests for AzureOpenAITranscriptSummarizer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.core.working_context.types import EntryKind, EntryRole, TranscriptEntry
from fdai.delivery.azure.llm.transcript_summarizer import (
    AzureOpenAITranscriptSummarizer,
    AzureOpenAITranscriptSummarizerConfig,
)
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity


class _StaticIdentity(WorkloadIdentity):
    def __init__(self, token: str = "test-token") -> None:  # noqa: S107 - fake token
        self._token = token

    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token=self._token,
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


def _entry(entry_id: str, *, sequence: int, trusted: bool = False) -> TranscriptEntry:
    return TranscriptEntry(
        entry_id=entry_id,
        role=EntryRole.OPERATOR,
        kind=EntryKind.VERBATIM,
        text=f"turn {entry_id}",
        tokens=10,
        sequence=sequence,
        trusted=trusted,
    )


def _config() -> AzureOpenAITranscriptSummarizerConfig:
    return AzureOpenAITranscriptSummarizerConfig(
        endpoint="https://oai-test.openai.azure.com",
        deployment="t1-judge",
    )


def _transport(content: str, *, completion_tokens: int | None = None) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = {"choices": [{"message": {"content": content}}]}
        if completion_tokens is not None:
            body["usage"] = {"completion_tokens": completion_tokens}
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


async def test_summarize_folds_span_into_summary_entry() -> None:
    transport = _transport("decision X; tool call Y ran ok", completion_tokens=7)
    async with httpx.AsyncClient(transport=transport) as http:
        summarizer = AzureOpenAITranscriptSummarizer(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        span = [
            _entry("a", sequence=1, trusted=True),
            _entry("b", sequence=2, trusted=True),
        ]
        summary = await summarizer.summarize(entries=span, level=1)
    assert summary.kind is EntryKind.SUMMARY
    assert summary.level == 1
    assert summary.text == "decision X; tool call Y ran ok"
    assert summary.tokens == 7
    assert summary.source_ids == ("a", "b")
    assert summary.sequence == 2
    assert summary.trusted is True


async def test_summary_untrusted_when_any_source_untrusted() -> None:
    async with httpx.AsyncClient(transport=_transport("s")) as http:
        summarizer = AzureOpenAITranscriptSummarizer(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        span = [
            _entry("a", sequence=1, trusted=True),
            _entry("b", sequence=2, trusted=False),
        ]
        summary = await summarizer.summarize(entries=span, level=1)
    assert summary.trusted is False


async def test_empty_span_rejected() -> None:
    async with httpx.AsyncClient(transport=_transport("s")) as http:
        summarizer = AzureOpenAITranscriptSummarizer(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(ValueError, match="empty span"):
            await summarizer.summarize(entries=[], level=1)


async def test_missing_content_raises() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        summarizer = AzureOpenAITranscriptSummarizer(
            identity=_StaticIdentity(), http_client=http, config=_config()
        )
        with pytest.raises(RuntimeError, match="missing content"):
            await summarizer.summarize(entries=[_entry("a", sequence=1)], level=1)


def test_config_rejects_relative_endpoint() -> None:
    with pytest.raises(ValueError, match="absolute https URL"):
        AzureOpenAITranscriptSummarizerConfig(endpoint="oai", deployment="d")
