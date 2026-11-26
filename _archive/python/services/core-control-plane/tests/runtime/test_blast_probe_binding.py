from __future__ import annotations

from dataclasses import replace

from fdai.composition import default_container
from fdai.delivery.live_blast_probe import LiveBlastProbeAdapter
from fdai.runtime.blast_probe import bind_live_blast_probe_failure_streak
from fdai.shared.config import AppConfig
from fdai.shared.providers.blast_probe import ProbeQuery, ProbeResult, ProbeVerdict
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _Probe:
    async def measure(self, query: ProbeQuery) -> ProbeResult:
        del query
        return ProbeResult(ProbeVerdict.QUIET)


def test_runtime_wraps_configured_probe_once(app_config: AppConfig) -> None:
    container = replace(default_container(app_config), live_blast_probe=_Probe())
    store = InMemoryStateStore()

    bound = bind_live_blast_probe_failure_streak(container, state_store=store)
    rebound = bind_live_blast_probe_failure_streak(bound, state_store=store)

    assert isinstance(bound.live_blast_probe, LiveBlastProbeAdapter)
    assert rebound is bound
