"""Evaluation runner composition readiness tests."""

from __future__ import annotations

from pathlib import Path

from fdai.core.control_loop import ControlLoopOutcome, ControlLoopResult
from fdai.delivery.evaluation import KubectlEvidenceClient, KubectlEvidenceConfig
from fdai.runtime.evaluation_runner import build_sregym_evaluation_host, readiness_payload


class _Processor:
    async def process(self, event):  # type: ignore[no-untyped-def]
        del event
        return ControlLoopResult(
            outcome=ControlLoopOutcome.ABSTAINED_T0,
            tier="t0",
            decision="abstain",
            resource_type="kubernetes-cluster",
        )


class _Reasoner:
    async def reason(self, *, incident_summary, candidate_citations):  # type: ignore[no-untyped-def]
        del incident_summary, candidate_citations
        return None


def _client(kubeconfig: Path) -> KubectlEvidenceClient:
    return KubectlEvidenceClient(
        config=KubectlEvidenceConfig(
            kubeconfig=kubeconfig,
            context="example-context",
            cluster_name="example-cluster",
            allowed_namespaces=frozenset({"example-app"}),
        )
    )


def test_sregym_host_readiness_requires_grounded_rca_reasoner(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")

    host, unavailable = build_sregym_evaluation_host(
        processor=_Processor(),
        evidence_client=_client(kubeconfig),
        rca_reasoner=None,
    )
    assert host.api_version == "1.0"
    assert unavailable.ready is False
    assert readiness_payload(unavailable)["checks"] == {
        "rca_reasoner": False,
        "kubernetes_inventory": True,
        "kubernetes_events": True,
        "kubernetes_nodes": True,
        "kubernetes_capacity": True,
    }

    _, ready = build_sregym_evaluation_host(
        processor=_Processor(),
        evidence_client=_client(kubeconfig),
        rca_reasoner=_Reasoner(),
    )
    assert ready.ready is True
    assert ready.shadow_only is True
