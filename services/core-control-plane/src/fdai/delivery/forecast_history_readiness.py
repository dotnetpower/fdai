"""Settings projection row for forecast history source production.

The row validates configuration with the same parser runtime composition uses, so a mapping the
runtime would reject never appears bound. `ready` and `available` stay false until every source
can attest positive coverage and independent operational proofs exist; the Console therefore
never shows this capability as ready. `enabled` reports only the deployment opt-in because no
durable Settings preference exists yet. Configuration never grants scoring or execution authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from fdai.delivery.forecast_history_configuration import (
    ForecastHistoryConfiguration,
    parse_forecast_history_configuration,
)

_SOURCE_CORE = "core-control-plane"
_SOURCE_READERS = {
    "actions": None,
    "changes": "inventory-journal-witness",
    "excluded_windows": None,
    "resource_lifecycle": "inventory-incarnation-ledger",
}
_SOURCE_LIMITATIONS = {
    "actions": "no bounded target-scoped action audit reader can attest event-time completeness",
    "changes": "the journal witness cannot attest a start-of-window checkpoint",
    "excluded_windows": "no attested reviewed change-window history source exists",
    "resource_lifecycle": "the incarnation ledger cannot attest reconciliation after the window",
}
_UNAVAILABLE = (
    "positive source checkpoints and independent operational proof issuance are unavailable"
)


def _targets_configured(raw: str) -> bool:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(value, list) and bool(value) and all(isinstance(item, dict) for item in value)


def forecast_history_projection(env: Mapping[str, str]) -> dict[str, object]:
    """Project observable prerequisites; secrets and mapping values are never echoed."""
    dsn = bool(env.get("FDAI_STATE_STORE_DSN", "").strip())
    targets = _targets_configured(env.get("FDAI_FORECAST_TARGETS_JSON", "").strip())
    sources_raw = env.get("FDAI_FORECAST_HISTORY_SOURCES_JSON", "").strip()
    producers_raw = env.get("FDAI_FORECAST_HISTORY_PRODUCERS_JSON", "").strip()
    configured = bool(sources_raw or producers_raw)
    configuration: ForecastHistoryConfiguration | None = None
    invalid = bool(producers_raw and not sources_raw)
    if sources_raw:
        try:
            configuration = parse_forecast_history_configuration(
                bindings_json=sources_raw, producers_json=producers_raw or None
            )
        except ValueError:
            invalid = True
    bound = frozenset(
        binding.kind for binding, _history in (configuration.producers if configuration else ())
    )
    opted_in = bool(configuration is not None and bound and dsn and targets)
    return {
        "key": "forecast-history",
        "source": _SOURCE_CORE,
        "observed": True,
        "configured": configured,
        "ready": False,
        "mode": "shadow" if opted_in else "disabled",
        "reason": (
            "configuration is invalid"
            if invalid
            else _UNAVAILABLE
            if opted_in
            else "configuration is incomplete"
            if configured
            else "not configured"
        ),
        "available": False,
        "enabled": opted_in,
        "enabled_source": "deployment_configuration",
        "authority_mode": "shadow",
        "scoring_authority": False,
        "execution_authority": False,
        "unavailable_reason": _UNAVAILABLE,
        "prerequisites": [
            {"name": "FDAI_STATE_STORE_DSN", "satisfied": dsn},
            {"name": "FDAI_FORECAST_TARGETS_JSON", "satisfied": targets},
            {"name": "FDAI_FORECAST_HISTORY_SOURCES_JSON", "satisfied": configuration is not None},
            {"name": "FDAI_FORECAST_HISTORY_PRODUCERS_JSON", "satisfied": bool(bound)},
            {"name": "positive_source_checkpoints", "satisfied": False},
            {"name": "independent_operational_proof_issuance", "satisfied": False},
        ],
        "sources": [
            {
                "kind": kind,
                "reader": reader,
                "bound": kind in bound,
                "positive_checkpoint": False,
                "limitation": _SOURCE_LIMITATIONS[kind],
            }
            for kind, reader in sorted(_SOURCE_READERS.items())
        ],
    }


__all__ = ["forecast_history_projection"]
