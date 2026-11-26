"""Runtime binding for durable live-blast probe failure escalation."""

from __future__ import annotations

from dataclasses import dataclass, replace

from fdai.composition import Container
from fdai.delivery.live_blast_probe import LiveBlastProbeAdapter
from fdai.delivery.probe_failure_streak import StateStoreProbeFailureStreakSource
from fdai.shared.providers.blast_probe import LiveBlastProbe, ProbeQuery, ProbeResult
from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class _BoundBlastSignalSource:
    probe: LiveBlastProbe

    async def read(self, query: ProbeQuery) -> ProbeResult:
        return await self.probe.measure(query)


def bind_live_blast_probe_failure_streak(
    container: Container,
    *,
    state_store: StateStore,
) -> Container:
    """Wrap a configured provider probe with durable audited failure escalation."""

    probe = container.live_blast_probe
    if probe is None or isinstance(probe, LiveBlastProbeAdapter):
        return container
    return replace(
        container,
        live_blast_probe=LiveBlastProbeAdapter(
            signal_source=_BoundBlastSignalSource(probe),
            failure_streak_source=StateStoreProbeFailureStreakSource(state_store),
        ),
    )


__all__ = ["bind_live_blast_probe_failure_streak"]
