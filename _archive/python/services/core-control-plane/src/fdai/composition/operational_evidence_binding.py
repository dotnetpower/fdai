"""Bind operational evidence issuance and admission at the Core composition root.

Binding is explicit deployment opt-in. Without every prerequisite the container is unchanged,
so the eleven operational purposes keep their generic fail-closed holds. Binding never grants
execution or promotion authority and changes no agent ownership or topic.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace

import httpx

from fdai.core.operational_context.test_context_commands import TestContextCommandHandler
from fdai.core.operational_context.test_context_lifecycle import GovernedTestContextStore
from fdai.core.operational_evidence.owner_outcome import OperationalEvidenceRequester
from fdai.core.operational_evidence.registry_json import RegistryUnavailableError
from fdai.delivery.operational_evidence_admission import (
    OperationalEvidenceAdmissionProvider,
    PurposeRoutedAdmissionProvider,
)
from fdai.delivery.operational_evidence_configuration import (
    PRODUCER_ID,
    PRODUCER_VERSION,
    VERIFIER_ID,
    OperationalEvidenceSettings,
    load_anchors,
    load_registry_history,
)
from fdai.delivery.operational_evidence_transport import (
    BoundedOperationalEvidenceIssuer,
    HttpOperationalEvidenceTransport,
)
from fdai.delivery.persistence.postgres_operational_evidence import (
    PostgresOperationalEvidenceConfig,
    PostgresOperationalProofReader,
)
from fdai.delivery.repo_assets import repo_asset_root
from fdai.shared.providers.state_store import StateStore

from ._helpers import Container

_LOGGER = logging.getLogger(__name__)


def bind_operational_evidence(
    container: Container,
    environment: Mapping[str, str],
    http_client: httpx.AsyncClient | None,
) -> Container:
    """Route operational purposes to the proof store and bind the issuance requester."""

    settings = OperationalEvidenceSettings.from_environment(environment)
    if not settings.enabled:
        return container
    if http_client is None or not settings.verifier_url or not settings.reader_dsn.strip():
        _LOGGER.warning(
            "operational_evidence_unavailable", extra={"reason": "prerequisite_missing"}
        )
        return container
    try:
        history = load_registry_history(settings, root=repo_asset_root())
        anchors = load_anchors(settings)
        transport = HttpOperationalEvidenceTransport(http_client, base_url=settings.verifier_url)
        reader = PostgresOperationalProofReader(
            PostgresOperationalEvidenceConfig(
                dsn=settings.reader_dsn, expected_role=settings.reader_role
            )
        )
    except (OSError, RegistryUnavailableError, ValueError) as exc:
        _LOGGER.warning("operational_evidence_unavailable", extra={"reason": type(exc).__name__})
        return container
    admission = OperationalEvidenceAdmissionProvider(
        reader=reader, history=lambda: history, anchors=anchors, verifier_id=VERIFIER_ID
    )
    requester = OperationalEvidenceRequester(
        issuer=BoundedOperationalEvidenceIssuer(transport),
        outcomes=admission,
        producer_id=PRODUCER_ID,
        producer_version=PRODUCER_VERSION,
    )
    return replace(
        container,
        decision_evidence_admission_provider=PurposeRoutedAdmissionProvider(
            operational=admission, fallback=container.decision_evidence_admission_provider
        ),
        operational_evidence_requester=requester,
    )


def build_test_context_command_handler(
    *, store: StateStore, container: Container
) -> TestContextCommandHandler | None:
    """Build the Var and Mimir command handler with the bound issuance requester, if any."""

    admission = container.decision_evidence_admission_provider
    if admission is None:
        return None
    requester = container.operational_evidence_requester
    return TestContextCommandHandler(
        contexts=GovernedTestContextStore(store=store, admission=admission, evidence=requester),
        admission=admission,
        evidence=requester,
    )


__all__ = ["bind_operational_evidence", "build_test_context_command_handler"]
