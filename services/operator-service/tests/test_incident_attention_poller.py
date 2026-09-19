from __future__ import annotations

import asyncio

from fdai_operator_service.incident_attention_poller import IncidentAttentionPoller
from fdai_service_contracts import (
    IncidentAttentionProjection,
    IncidentAttentionQuery,
)


class _ReadModel:
    def __init__(self) -> None:
        self.calls: list[IncidentAttentionQuery] = []
        self.sequence = 7

    async def incident_attention(
        self, query: IncidentAttentionQuery
    ) -> IncidentAttentionProjection:
        self.calls.append(query)
        return IncidentAttentionProjection(
            sequence=self.sequence,
            payload={"event": "incident_attention.snapshot", "ts": "", "incidents": []},
        )


async def test_poller_coalesces_subscribers_and_preserves_each_cursor() -> None:
    read_model = _ReadModel()
    now = 10.0
    poller = IncidentAttentionPoller(
        read_model,
        poll_seconds=2.0,
        clock=lambda: now,
    )

    first = await poller.read(after_seq=None)
    replay = await poller.read(after_seq=6)
    current = await poller.read(after_seq=7)

    assert first is not None and first.sequence == 7
    assert replay is first
    assert current is None
    assert read_model.calls == [IncidentAttentionQuery(after_seq=None, limit=50)]

    now = 12.0
    read_model.sequence = 8
    refreshed = await poller.read(after_seq=7)

    assert refreshed is not None and refreshed.sequence == 8
    assert read_model.calls == [
        IncidentAttentionQuery(after_seq=None, limit=50),
        IncidentAttentionQuery(after_seq=None, limit=50),
    ]


async def test_poller_coalesces_concurrent_subscribers() -> None:
    class SlowReadModel(_ReadModel):
        async def incident_attention(
            self, query: IncidentAttentionQuery
        ) -> IncidentAttentionProjection:
            await asyncio.sleep(0)
            return await super().incident_attention(query)

    read_model = SlowReadModel()
    poller = IncidentAttentionPoller(read_model, poll_seconds=2.0, clock=lambda: 10.0)

    results = await asyncio.gather(*(poller.read(after_seq=None) for _ in range(20)))

    assert all(result is not None and result.sequence == 7 for result in results)
    assert read_model.calls == [IncidentAttentionQuery(after_seq=None, limit=50)]
