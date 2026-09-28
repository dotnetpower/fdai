"""Core composition binding for operational evidence is opt-in and never adds authority."""

from __future__ import annotations

from pathlib import Path

import httpx
from fdai.composition import Container
from fdai.composition.operational_evidence_binding import (
    bind_operational_evidence,
    build_test_context_command_handler,
)
from fdai.delivery.operational_evidence_admission import PurposeRoutedAdmissionProvider
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.delivery.test_operational_evidence_readiness import _environment


async def test_disabled_or_incomplete_configuration_leaves_the_container_unchanged(
    tmp_path: Path, container: Container
) -> None:
    async with httpx.AsyncClient() as client:
        assert bind_operational_evidence(container, {}, client) is container
        incomplete = {**_environment(tmp_path), "FDAI_OPERATIONAL_EVIDENCE_VERIFIER_URL": ""}
        assert bind_operational_evidence(container, incomplete, client) is container
        assert bind_operational_evidence(container, _environment(tmp_path), None) is container
        wrong_pin = {
            **_environment(tmp_path),
            "FDAI_OPERATIONAL_EVIDENCE_TRUST_REGISTRY_PIN": "sha256:" + "0" * 64,
        }
        assert bind_operational_evidence(container, wrong_pin, client) is container


async def test_enabled_binding_routes_operational_purposes_and_binds_the_requester(
    tmp_path: Path, container: Container
) -> None:
    async with httpx.AsyncClient() as client:
        bound = bind_operational_evidence(container, _environment(tmp_path), client)
    assert isinstance(bound.decision_evidence_admission_provider, PurposeRoutedAdmissionProvider)
    requester = bound.operational_evidence_requester
    assert requester is not None and requester.producer_id == "core-control-plane"
    assert (
        await bound.decision_evidence_admission_provider.admit(
            evidence_digest="sha256:" + "1" * 64,
            scope_digest="sha256:" + "2" * 64,
            purpose_id="startup-readiness",
            source_revision="revision",
        )
        is None
    )
    handler = build_test_context_command_handler(store=InMemoryStateStore(), container=bound)
    assert handler is not None
    assert build_test_context_command_handler(store=InMemoryStateStore(), container=container) is (
        None
    )
