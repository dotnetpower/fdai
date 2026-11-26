"""Azure VM power-state adapter for independent effect observation.

Reuses the already-shipped :class:`AzureVmPowerStateSource`, which reads the
ARM instance view through an identity that never calls the mutation
gateway.  This adapter only translates that reading into the provider-neutral
shape the observer consumes; it adds no authority and performs no write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.core.executor.effect_observation import (
    IndependentEffectObservationBinding,
)
from fdai.core.executor.effect_observation_source import ObservedEffectState
from fdai.delivery.azure.vm_power_state import (
    AzureVmPowerStateReading,
    AzureVmPowerStateSource,
)

#: Power state that proves ``ops.start-vm`` took hold.
RUNNING_POWER_STATE = "running"

#: Power state that proves the VM is still transitioning, so the reading is
#: provisional rather than a failure.
STARTING_POWER_STATE = "starting"


@dataclass(frozen=True, slots=True)
class AzureVmPowerStateEffectSourceConfig:
    """Pin one observation source to one resource and semantic revision."""

    resource_ref: str
    target_revision: int
    source_instance_id: str

    def __post_init__(self) -> None:
        if not self.resource_ref.strip():
            raise ValueError("VM power-state effect source requires a resource reference")
        if isinstance(self.target_revision, bool) or self.target_revision < 1:
            raise ValueError("VM power-state effect source revision MUST be positive")
        if not self.source_instance_id.strip():
            raise ValueError("VM power-state effect source requires a source identity")


class AzureVmPowerStateEffectSource:
    """Read one pinned VM and describe it in observation-quality terms."""

    def __init__(
        self,
        *,
        source: AzureVmPowerStateSource,
        config: AzureVmPowerStateEffectSourceConfig,
    ) -> None:
        self._source = source
        self._config = config

    @property
    def source_instance_id(self) -> str:
        """Stable identity of the authoritative Azure read path."""

        return self._config.source_instance_id

    async def read(
        self,
        *,
        binding: IndependentEffectObservationBinding,
    ) -> ObservedEffectState:
        """Return the pinned VM's power state as a provider-neutral reading."""

        del binding
        reading = await self._source.observe(
            resource_ref=self._config.resource_ref,
            target_revision=self._config.target_revision,
        )
        return _state_from(reading, source_instance_id=self._config.source_instance_id)


def _state_from(
    reading: AzureVmPowerStateReading,
    *,
    source_instance_id: str,
) -> ObservedEffectState:
    """Translate one bounded ARM reading without widening what it proved."""

    observed_at = reading.observed_at.astimezone(UTC)
    recorded_at = reading.recorded_at.astimezone(UTC)
    present: bool | None
    final = True
    if reading.state is None:
        present = None
    elif reading.state == RUNNING_POWER_STATE:
        present = True
    elif reading.state == STARTING_POWER_STATE:
        # A transitioning VM has neither started nor failed to start.
        present = None
        final = False
    else:
        present = False
    return ObservedEffectState(
        source_instance_id=source_instance_id,
        observed_at=observed_at,
        source_recorded_at=recorded_at,
        evidence_window_start=min(observed_at, recorded_at) - timedelta(seconds=1),
        evidence_window_end=max(observed_at, recorded_at, _fresh_until(reading)),
        expected_state_present=present,
        complete=reading.complete,
        final=final,
        contained=True,
        synthetic=False,
        conflicts=reading.conflicts,
        censoring_refs=reading.censoring_refs,
        detail=f"power state {reading.state or 'unreported'}",
    )


def _fresh_until(reading: AzureVmPowerStateReading) -> datetime:
    return reading.fresh_until.astimezone(UTC)


__all__ = [
    "RUNNING_POWER_STATE",
    "STARTING_POWER_STATE",
    "AzureVmPowerStateEffectSource",
    "AzureVmPowerStateEffectSourceConfig",
]
