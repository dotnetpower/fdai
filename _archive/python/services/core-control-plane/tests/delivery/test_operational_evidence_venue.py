"""The execution venue comes from the authoritative resolver, never from the anchor document."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.core.operational_evidence.registry_json import RegistryUnavailableError
from fdai.core.operational_evidence.trust_registry_loader import load_deployment_anchors
from fdai.delivery.operational_evidence_readiness import operational_evidence_projection
from fdai.delivery.operational_evidence_server import build_verifier_workload
from fdai_service_contracts.venue import ExecutionVenue

from tests.core.operational_evidence.support import NOW, anchors_json
from tests.delivery.test_operational_evidence_readiness import _environment

_ANCHORS = "FDAI_OPERATIONAL_EVIDENCE_ANCHORS_JSON"


def _duplicated_venue() -> str:
    body = anchors_json(venue="deployed")
    return body[:-1] + ', "venue": "local"}'


def test_anchor_document_must_agree_with_the_resolved_venue() -> None:
    with pytest.raises(RegistryUnavailableError, match="binding is invalid"):
        load_deployment_anchors(
            anchors_json(venue="local"), execution_venue=ExecutionVenue.DEPLOYED
        )
    bound = load_deployment_anchors(
        anchors_json(venue="deployed", evidence_class="live"),
        execution_venue=ExecutionVenue.DEPLOYED,
    )
    assert bound.venue is ExecutionVenue.DEPLOYED


@pytest.mark.parametrize("venue", list(ExecutionVenue))
def test_repeated_anchor_keys_are_unavailable(venue: ExecutionVenue) -> None:
    with pytest.raises(RegistryUnavailableError, match="repeats a key"):
        load_deployment_anchors(_duplicated_venue(), execution_venue=venue)


def _workload_env(tmp_path: Path, **values: str) -> dict[str, str]:
    env = {
        **_environment(tmp_path),
        "FDAI_OPERATIONAL_EVIDENCE_VERIFIER_DSN": "postgresql://placeholder@127.0.0.1:5433/x",
    }
    env.update(values)
    return {key: value for key, value in env.items() if value}


def test_verifier_starts_only_in_the_resolved_local_venue(tmp_path: Path) -> None:
    root = tmp_path
    local = build_verifier_workload(_workload_env(tmp_path), root=root)
    assert local.deployed_venue is False
    with pytest.raises(RuntimeError, match="executor anchors"):
        build_verifier_workload(
            _workload_env(
                tmp_path,
                FDAI_EXECUTION_VENUE="deployed",
                **{_ANCHORS: anchors_json(venue="deployed", evidence_class="live")},
            ),
            root=root,
        )
    with pytest.raises(RegistryUnavailableError):
        build_verifier_workload(_workload_env(tmp_path, FDAI_EXECUTION_VENUE=""), root=root)
    with pytest.raises(RegistryUnavailableError, match="repeats a key"):
        build_verifier_workload(
            _workload_env(tmp_path, **{_ANCHORS: _duplicated_venue()}), root=root
        )
    with pytest.raises(RuntimeError):
        build_verifier_workload(_workload_env(tmp_path, FDAI_EXECUTION_VENUE="staging"), root=root)


def test_settings_rows_are_unavailable_when_the_anchor_venue_disagrees(tmp_path: Path) -> None:
    rows = operational_evidence_projection(
        _workload_env(tmp_path, FDAI_EXECUTION_VENUE="deployed"),
        now=NOW,
        verifier_readiness={"state": "ready", "bound_purposes": ["operator-test-context-command"]},
    )
    assert {row["reason"] for row in rows} == {
        "a pinned registry or the anchor binding is unavailable"
    }
    assert all(row["available"] is False for row in rows)
