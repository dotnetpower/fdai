"""Evaluation runner CLI configuration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.core.rca import RcaTier, RootCauseHypothesis
from fdai.runtime.evaluation_runner_cli import (
    _EVALUATION_MUTATION_READINESS,
    _cluster_identity,
    _kubernetes_config,
    _probe_kubernetes_evidence,
    _probe_rca,
    _requires_llm_binding,
    main,
)
from fdai.shared.config.models import LlmMode


def test_evaluation_runtime_declares_shadow_only_mutation_readiness() -> None:
    assert _EVALUATION_MUTATION_READINESS.mutation_ready is False


def test_kubernetes_config_requires_complete_exact_scope(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text(
        "contexts:\n"
        "- name: example-context\n"
        "  context:\n"
        "    cluster: example-cluster\n"
        "clusters:\n"
        "- name: example-cluster\n"
        "  cluster:\n"
        "    server: https://example.invalid:6443\n"
        "    certificate-authority-data: Y2E=\n",
        encoding="utf-8",
    )
    config = _kubernetes_config(
        {
            "FDAI_EVALUATION_KUBECONFIG": str(kubeconfig),
            "FDAI_EVALUATION_KUBERNETES_CONTEXT": "example-context",
            "FDAI_EVALUATION_KUBERNETES_CLUSTER": "example-cluster",
            "FDAI_EVALUATION_KUBERNETES_NAMESPACES": "app-a, app-b",
        }
    )
    assert config.allowed_namespaces == frozenset({"app-a", "app-b"})
    assert config.cluster_identity.startswith("sha256:")

    with pytest.raises(ValueError, match="are required"):
        _kubernetes_config({})

    with pytest.raises(ValueError, match="do not match"):
        _kubernetes_config(
            {
                "FDAI_EVALUATION_KUBECONFIG": str(kubeconfig),
                "FDAI_EVALUATION_KUBERNETES_CONTEXT": "example-context",
                "FDAI_EVALUATION_KUBERNETES_CLUSTER": "other-cluster",
                "FDAI_EVALUATION_KUBERNETES_NAMESPACES": "app-a",
            }
        )


def test_cluster_identity_uses_api_server_and_ca_not_alias(tmp_path: Path) -> None:
    identities: list[str] = []
    for index, server in enumerate(("one.invalid", "two.invalid")):
        kubeconfig = tmp_path / f"config-{index}"
        kubeconfig.write_text(
            "clusters:\n"
            "- name: prod\n"
            "  cluster:\n"
            f"    server: https://{server}:6443\n"
            "    certificate-authority-data: Y2E=\n",
            encoding="utf-8",
        )
        identities.append(_cluster_identity(kubeconfig, "prod"))

    assert identities[0] != identities[1]


def test_cli_rejects_unknown_adapter_before_runtime_start() -> None:
    with pytest.raises(SystemExit):
        main(("check", "--adapter", "unknown"))


def test_azure_mode_matches_deserialized_string_value() -> None:
    assert _requires_llm_binding("azure") is True
    assert _requires_llm_binding(LlmMode.AZURE) is True
    assert _requires_llm_binding("disabled") is False


async def test_rca_probe_requires_grounded_live_hypothesis() -> None:
    class _Reasoner:
        async def reason(self, *, incident_summary, candidate_citations):  # type: ignore[no-untyped-def]
            assert "Synthetic readiness probe" in incident_summary
            return RootCauseHypothesis(
                tier=RcaTier.T2,
                cause="No operational diagnosis was requested.",
                confidence=1.0,
                citations=(candidate_citations[0],),
            )

    class _AbstainingReasoner:
        async def reason(self, *, incident_summary, candidate_citations):  # type: ignore[no-untyped-def]
            del incident_summary, candidate_citations
            return None

    assert await _probe_rca(_Reasoner()) is True
    assert await _probe_rca(_AbstainingReasoner()) is False
    assert await _probe_rca(None) is False


async def test_kubernetes_probe_requires_every_advertised_capability() -> None:
    class _Client:
        async def admission(self, task):  # type: ignore[no-untyped-def]
            return {}

        async def capacity(self, task):  # type: ignore[no-untyped-def]
            assert task.target.value == "example-app"
            return {}

        async def dependencies(self, task):  # type: ignore[no-untyped-def]
            assert task.target.value == "example-app"
            return {}

        async def inventory(self, task):  # type: ignore[no-untyped-def]
            assert task.target.value == "example-app"
            return {}

        async def events(self, task):  # type: ignore[no-untyped-def]
            assert task.target.value == "example-app"
            return {}

        async def nodes(self, task):  # type: ignore[no-untyped-def]
            assert task.target.value == "example-app"
            return {}

        async def owners(self, task):  # type: ignore[no-untyped-def]
            return {}

        async def pod_metrics(self, task):  # type: ignore[no-untyped-def]
            assert task.target.value == "example-app"
            raise RuntimeError("forbidden")

    checks, error_type = await _probe_kubernetes_evidence(
        _Client(),  # type: ignore[arg-type]
        frozenset({"example-app"}),
    )

    assert checks == {
        "kubernetes_admission_live_probe": True,
        "kubernetes_capacity_live_probe": True,
        "kubernetes_dependencies_live_probe": True,
        "kubernetes_inventory_live_probe": True,
        "kubernetes_events_live_probe": True,
        "kubernetes_nodes_live_probe": True,
        "kubernetes_owners_live_probe": True,
        "kubernetes_metrics_live_probe": False,
    }
    assert error_type == "RuntimeError"


async def test_kubernetes_probe_requires_inventory_access() -> None:
    class _Client:
        async def admission(self, task):  # type: ignore[no-untyped-def]
            return {}

        async def capacity(self, task):  # type: ignore[no-untyped-def]
            return {}

        async def dependencies(self, task):  # type: ignore[no-untyped-def]
            return {}

        async def inventory(self, task):  # type: ignore[no-untyped-def]
            raise RuntimeError("forbidden")

        async def events(self, task):  # type: ignore[no-untyped-def]
            return {}

        async def nodes(self, task):  # type: ignore[no-untyped-def]
            return {}

        async def owners(self, task):  # type: ignore[no-untyped-def]
            return {}

        async def pod_metrics(self, task):  # type: ignore[no-untyped-def]
            return {}

    checks, error_type = await _probe_kubernetes_evidence(
        _Client(),  # type: ignore[arg-type]
        frozenset({"example-app"}),
    )

    assert checks["kubernetes_inventory_live_probe"] is False
    assert error_type == "RuntimeError"
