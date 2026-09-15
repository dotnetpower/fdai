"""Read and revalidate injected alert-quality evidence, preferences and readiness."""

from __future__ import annotations

import logging
from datetime import datetime

from fdai_service_contracts.alert_noise import NoiseAssessment

from fdai_operator_service.alert_quality_config import AlertQualityDependencies
from fdai_operator_service.alert_quality_records import (
    AlertQualitySnapshot,
    AlertQualityUnavailableError,
    verify_alert_quality_snapshot,
)
from fdai_operator_service.alert_quality_settings import (
    AlertQualityPreference,
    verify_alert_quality_preference,
)

_LOGGER = logging.getLogger("fdai_operator_service.alert_quality")


async def _producer_is_ready(dependencies: AlertQualityDependencies) -> bool:
    """Require literal producer readiness; failure does not discard retained evidence."""
    if dependencies.producer_ready is None:
        return False
    try:
        return await dependencies.producer_ready() is True
    except Exception as exc:  # noqa: BLE001 - read evidence survives producer unavailability
        _LOGGER.warning(
            "alert quality producer unavailable",
            extra={
                "event": "alert_quality.producer_unavailable",
                "failure_type": type(exc).__name__,
            },
        )
        return False


async def _read_preference(
    dependencies: AlertQualityDependencies, scope: str
) -> tuple[AlertQualityPreference | None, bool]:
    """Distinguish an unsaved default from an unavailable or invalid bound preference."""
    if dependencies.preference_store is None:
        return None, False
    try:
        preference = await dependencies.preference_store.read(scope_ref=scope)
        if preference is not None:
            preference = verify_alert_quality_preference(
                preference, scope_ref=scope, now=dependencies.clock()
            )
        return preference, True
    except Exception as exc:  # noqa: BLE001 - an unavailable preference vetoes new work
        _LOGGER.warning(
            "alert quality preference unavailable",
            extra={
                "event": "alert_quality.preference_unavailable",
                "failure_type": type(exc).__name__,
            },
        )
        return None, False


def _effective_enabled(
    dependencies: AlertQualityDependencies,
    preference: AlertQualityPreference | None,
    readable: bool,
) -> bool:
    """Veto new work when a bound preference store cannot establish its current value."""
    if dependencies.preference_store is not None and not readable:
        return False
    return dependencies.enabled if preference is None else preference.enabled


async def _read_snapshot(
    dependencies: AlertQualityDependencies, principal_id: str, scope_ref: str
) -> AlertQualitySnapshot | None:
    """Read exact principal/scope evidence without manufacturing an unbound source."""
    if dependencies.source is None:
        raise AlertQualityUnavailableError("alert quality source is unavailable")
    snapshot = await dependencies.source.read(principal_id=principal_id, scope_ref=scope_ref)
    if snapshot is None:
        return None
    return verify_alert_quality_snapshot(snapshot, principal_id=principal_id, scope_ref=scope_ref)


def _current(assessment: NoiseAssessment, now: datetime) -> bool:
    """Require an aware clock and a half-open observed validity interval."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise AlertQualityUnavailableError("alert quality clock is unavailable")
    return assessment.observed_at <= now < assessment.valid_until
