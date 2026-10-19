import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from fdai.delivery import document_intent_ingress
from fdai.delivery.document_intent_ingress import DocumentIntentIngress
from fdai.shared.providers.event_bus import EventEnvelope


async def test_run_consumes_the_ready_topic_until_stop(monkeypatch):
    stop = asyncio.Event()
    event = EventEnvelope(topic="object.event", key="example", payload={}, offset=1)

    async def stream():
        yield event
        stop.set()

    @asynccontextmanager
    async def subscribe(*_args, **_kwargs):
        yield stream()

    handled = AsyncMock(return_value=True)
    monkeypatch.setattr(document_intent_ingress, "subscription", subscribe)
    monkeypatch.setattr(DocumentIntentIngress, "handle", handled)
    binding = DocumentIntentIngress(intent=object(), pantheon_bus=object())  # type: ignore[arg-type]

    await binding.run(bus=object(), stop=stop)  # type: ignore[arg-type]

    handled.assert_awaited_once()
