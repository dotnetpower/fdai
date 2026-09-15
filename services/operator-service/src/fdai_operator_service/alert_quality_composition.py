"""Assemble alert request dependencies and their one durable transport lifecycle.

Construction performs no I/O, creates no identity or storage fallback, and never
grants execution authority. The parent composition still supervises the returned
bridge together with the other Operator-owned outbox workers.
"""

from __future__ import annotations

from collections.abc import Mapping

from fdai_operator_service.alert_quality_config import (
    AlertQualityDependencies,
    alert_quality_dependencies_from_environment,
    parse_alert_quality_principal_scopes,
)
from fdai_operator_service.alert_quality_runtime import AlertQualityBridge, AlertQualityTransport
from fdai_operator_service.alert_quality_settings import StateKvAlertQualityPreferenceStore
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.families.operations.contracts import EventProposalWriter
from fdai_operator_service.postgres_family_store import PostgresFamilyStore


def build_alert_quality_bindings(
    *,
    authenticator: OperatorAuthenticator,
    environ: Mapping[str, str],
    store: PostgresFamilyStore | None,
    transport: AlertQualityTransport | None,
    event_topic: str | None,
    proposal_writer: EventProposalWriter | None,
) -> tuple[AlertQualityDependencies, AlertQualityBridge | None]:
    """Bind existing store, transport, Settings, history and the same readiness probe.

    A configured signing key requires all durable transport dependencies. Without
    a key the bridge remains absent, while available retained projections and
    preferences remain readable under their existing authentication/scope checks.
    """
    scopes = parse_alert_quality_principal_scopes(environ)
    key = environ.get("FDAI_ALERT_NOISE_TRANSPORT_KEY", "").encode()
    bridge = None
    if key:
        if store is None or transport is None or event_topic is None:
            raise RuntimeError("alert quality requires durable store and event transport")
        bridge = AlertQualityBridge(
            store=store,
            transport=transport,
            event_topic=event_topic,
            transport_key=key,
            scopes=frozenset(scope for allowed in scopes.values() for scope in allowed),
        )
    dependencies = alert_quality_dependencies_from_environment(
        authenticator=authenticator,
        environ=environ,
        store=store,
        proposal_writer=proposal_writer,
        producer_ready=bridge.producer_ready if bridge else None,
        request_source=bridge.requests if bridge else None,
        preference_store=StateKvAlertQualityPreferenceStore(store) if store is not None else None,
    )
    return dependencies, bridge
