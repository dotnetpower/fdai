"""Scripted HTTP observations prove refresh policy without external network access."""

from datetime import UTC, datetime, timedelta

import pytest
from fdai_ingestion_api_service.cloud_knowledge.collector import (
    CloudDocumentCollector,
    SourceResponse,
    SourceState,
    source_due,
)
from fdai_ingestion_api_service.cloud_knowledge.normalization import normalize_source
from fdai_service_contracts.cloud_knowledge import Applicability, CloudKnowledgeSource, Freshness

NOW = datetime(2026, 9, 14, tzinfo=UTC)
SOURCE = CloudKnowledgeSource(
    source_id="apim",
    collection_id="cloud",
    url="https://example.com/docs/apim",
    title="APIM",
    applicability=Applicability(
        resource_type="Microsoft.ApiManagement/service", service_generation="classic"
    ),
    mode="online",
    enabled=True,
    storage_allowed=True,
    license_ref="fixture",
)


class RecordingTransport:
    def __init__(self, *responses: SourceResponse) -> None:
        self.responses = list(responses)
        self.etags: list[str | None] = []

    async def fetch(self, source: CloudKnowledgeSource, *, etag: str | None) -> SourceResponse:
        self.etags.append(etag)
        return self.responses.pop(0)


async def test_unchanged_check_keeps_collection_date_and_body() -> None:
    transport = RecordingTransport(
        SourceResponse(200, b"# APIM\nRequirements", etag='"one"'),
        SourceResponse(304, etag='"one"'),
    )
    collector = CloudDocumentCollector(transport, collector_id="test")
    first = await collector.collect(SOURCE, SourceState(), now=NOW)
    second = await collector.collect(SOURCE, first, now=NOW + timedelta(days=7))
    assert transport.etags == [None, '"one"']
    assert first.document is not None and second.document is not None
    assert first.document.evidence.collected_at == second.document.evidence.collected_at
    assert first.document.text == second.document.text
    assert second.document.evidence.freshness(NOW + timedelta(days=7)) is Freshness.FRESH
    assert first.document.evidence.check.checked_at == NOW


async def test_change_and_failure_never_refresh_prior_body() -> None:
    transport = RecordingTransport(
        SourceResponse(200, b"original"), SourceResponse(200, b"new version"), SourceResponse(503)
    )
    collector = CloudDocumentCollector(transport, collector_id="test")
    first = await collector.collect(SOURCE, SourceState(), now=NOW)
    second = await collector.collect(SOURCE, first, now=NOW + timedelta(days=7))
    failed = await collector.collect(SOURCE, second, now=NOW + timedelta(days=14))
    assert second.last_attempt is not None and second.last_attempt.outcome == "changed"
    assert first.document is not None and first.document.evidence.check.checked_at == NOW
    assert failed.document == second.document
    assert failed.last_attempt is not None and failed.last_attempt.outcome == "failed"
    assert not source_due(SOURCE, failed, NOW + timedelta(days=14))


@pytest.mark.parametrize("status", [401, 403, 404, 410, 429, 503])
async def test_failure_preserves_source_and_bounds_attempt(status: int) -> None:
    transport = RecordingTransport(SourceResponse(status))
    result = await CloudDocumentCollector(transport, collector_id="test").collect(
        SOURCE,
        SourceState(),
        now=NOW,
    )
    assert len(transport.etags) == 1
    assert result.last_attempt is not None
    assert result.last_attempt.content_sha256 is None
    assert result.document is None and result.consecutive_failures == 1
    assert result.retry_after is not None and result.retry_after > NOW


async def test_offline_and_disabled_never_touch_transport() -> None:
    transport = RecordingTransport()
    collector = CloudDocumentCollector(transport, collector_id="test")
    for update in ({"mode": "offline"}, {"enabled": False}, {"storage_allowed": False}):
        previous = SourceState()
        assert (
            await collector.collect(SOURCE.model_copy(update=update), previous, now=NOW) is previous
        )
    assert not transport.etags


async def test_bad_304_requires_bounded_full_fetch() -> None:
    transport = RecordingTransport(SourceResponse(304), SourceResponse(200, b"full body"))
    result = await CloudDocumentCollector(transport, collector_id="test").collect(
        SOURCE,
        SourceState(),
        now=NOW,
    )
    assert transport.etags == [None, None]
    assert result.document is not None and result.document.text == "full body"


async def test_monthly_full_body_verification() -> None:
    transport = RecordingTransport(
        SourceResponse(200, b"body", etag='"one"'), SourceResponse(200, b"body", etag='"one"')
    )
    collector = CloudDocumentCollector(transport, collector_id="test")
    first = await collector.collect(SOURCE, SourceState(), now=NOW)
    await collector.collect(SOURCE, first, now=NOW + timedelta(days=30))
    assert transport.etags == [None, None]


async def test_structured_upgrade_is_checkpointed_without_refetching_or_redating() -> None:
    transport = RecordingTransport(
        SourceResponse(200, b"<main><h1>Guide</h1><p>Retained evidence.</p></main>", "text/html")
    )
    legacy = await CloudDocumentCollector(transport, collector_id="test").collect(
        SOURCE, SourceState(), now=NOW
    )
    upgraded = await CloudDocumentCollector(
        transport, collector_id="test", structured=True
    ).collect(SOURCE, legacy, now=NOW + timedelta(hours=1))
    assert upgraded.structured_document is not None
    assert upgraded.document == legacy.document
    assert upgraded.last_attempt == legacy.last_attempt
    assert upgraded.structured_document.evidence.collected_at == NOW
    assert upgraded.structured_document.evidence.check.checked_at == NOW
    assert transport.etags == [None]


async def test_repeated_304_after_fallback_cannot_renew_source() -> None:
    transport = RecordingTransport(
        SourceResponse(200, b"body", etag='"one"'),
        SourceResponse(304, etag='"other"'),
        SourceResponse(304, etag='"one"'),
    )
    collector = CloudDocumentCollector(transport, collector_id="test")
    prior = await collector.collect(SOURCE, SourceState(), now=NOW)
    failed = await collector.collect(SOURCE, prior, now=NOW + timedelta(days=7))
    assert failed.document == prior.document
    assert failed.last_attempt is not None and failed.last_attempt.outcome == "failed"


def test_html_preserves_requirements_and_tables_without_active_content() -> None:
    raw = (
        b"<html><nav>Ignore</nav><main><h1>APIM</h1><p>Premium only.</p>"
        b"<script>fetch('https://example.com')</script>"
        b"<table><tr><th>SKU</th><th>IPs</th></tr><tr><td>Premium</td><td>2</td></tr>"
        b"</table><p>Exception: v2 differs.</p></main></html>"
    )
    original, text = normalize_source(raw, "text/html", max_bytes=4096)
    assert original == raw.decode()
    assert "# APIM" in text and "Premium only." in text and "SKU | IPs" in text
    assert "Exception: v2 differs." in text
    assert "fetch" not in text and "Ignore" not in text
    with pytest.raises(ValueError, match="article"):
        normalize_source(b"<html>Please log in</html>", "text/html", max_bytes=4096)
