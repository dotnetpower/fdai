"""Readiness and run entry point for installed external evaluation adapters."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fdai_evaluation_sdk import EvaluationRunner, EvaluationTask, ResourceLimits, TargetRef

from fdai.composition import default_container_from_env
from fdai.core.rca import Citation, CitationKind, RcaReasoner
from fdai.delivery.evaluation import KubectlEvidenceClient, KubectlEvidenceConfig
from fdai.evaluation.plugins import load_evaluation_adapter
from fdai.runtime.bootstrap_bindings import build_runtime_workload_identity
from fdai.runtime.configuration import _finalize_llm_bindings, _new_http_client
from fdai.runtime.control_loop import _build_control_loop
from fdai.runtime.evaluation_runner import (
    build_sregym_evaluation_host,
    readiness_payload,
    sregym_evaluation_readiness,
)
from fdai.shared.config.models import LlmMode

_KUBECONFIG_ENV = "FDAI_EVALUATION_KUBECONFIG"
_CONTEXT_ENV = "FDAI_EVALUATION_KUBERNETES_CONTEXT"
_CLUSTER_ENV = "FDAI_EVALUATION_KUBERNETES_CLUSTER"
_NAMESPACES_ENV = "FDAI_EVALUATION_KUBERNETES_NAMESPACES"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fdai-evaluation-runner")
    parser.add_argument("command", choices=("check", "run"))
    parser.add_argument("--adapter", default="sregym", choices=("sregym",))
    return parser


def _kubernetes_config(environ: Mapping[str, str]) -> KubectlEvidenceConfig:
    kubeconfig = environ.get(_KUBECONFIG_ENV, "").strip()
    context = environ.get(_CONTEXT_ENV, "").strip()
    cluster = environ.get(_CLUSTER_ENV, "").strip()
    namespaces = frozenset(
        item.strip() for item in environ.get(_NAMESPACES_ENV, "").split(",") if item.strip()
    )
    if not kubeconfig or not context or not cluster or not namespaces:
        raise ValueError(
            f"{_KUBECONFIG_ENV}, {_CONTEXT_ENV}, {_CLUSTER_ENV}, and {_NAMESPACES_ENV} are required"
        )
    return KubectlEvidenceConfig(
        kubeconfig=Path(kubeconfig).expanduser().resolve(),
        context=context,
        cluster_name=cluster,
        allowed_namespaces=namespaces,
    )


def _probe_task(namespace: str) -> EvaluationTask:
    now = datetime.now(UTC)
    return EvaluationTask(
        session_id="readiness-probe",
        task_id="kubernetes-evidence",
        phase="readiness",
        objective="Verify bounded read-only Kubernetes evidence access.",
        target=TargetRef(kind="kubernetes.namespace", value=namespace),
        deadline=now + timedelta(minutes=1),
        resource_limits=ResourceLimits(
            cpu_seconds=30,
            memory_bytes=134_217_728,
            process_count=8,
            output_bytes=1_048_576,
            wall_clock_seconds=30,
        ),
    )


def _requires_llm_binding(mode: str | LlmMode) -> bool:
    return mode == LlmMode.AZURE


async def _probe_rca(reasoner: RcaReasoner | None) -> bool:
    if reasoner is None:
        return False
    try:
        hypothesis = await reasoner.reason(
            incident_summary=(
                "Synthetic readiness probe. Cite the supplied event only and state that no "
                "operational diagnosis is requested."
            ),
            candidate_citations=(
                Citation(kind=CitationKind.EVENT, ref="evaluation-readiness-probe"),
            ),
        )
    except Exception:  # noqa: BLE001 - readiness degrades without leaking provider detail
        return False
    return hypothesis is not None and hypothesis.grounded


async def _probe_kubernetes_evidence(
    evidence_client: KubectlEvidenceClient,
    namespaces: frozenset[str],
) -> tuple[dict[str, bool], str | None]:
    checks = {
        "kubernetes_capacity_live_probe": True,
        "kubernetes_inventory_live_probe": True,
        "kubernetes_events_live_probe": True,
        "kubernetes_nodes_live_probe": True,
        "kubernetes_metrics_live_probe": True,
    }
    first_error_type: str | None = None
    for namespace in sorted(namespaces):
        task = _probe_task(namespace)
        probes = (
            ("kubernetes_capacity_live_probe", evidence_client.capacity),
            ("kubernetes_inventory_live_probe", evidence_client.inventory),
            ("kubernetes_events_live_probe", evidence_client.events),
            ("kubernetes_nodes_live_probe", evidence_client.nodes),
            ("kubernetes_metrics_live_probe", evidence_client.pod_metrics),
        )
        for check_name, probe in probes:
            try:
                await probe(task)
            except Exception as exc:  # noqa: BLE001 - readiness emits only the error type
                checks[check_name] = False
                if first_error_type is None:
                    first_error_type = type(exc).__name__
    return checks, first_error_type


async def _run(command: str, adapter_name: str, environ: Mapping[str, str]) -> int:
    adapter = load_evaluation_adapter(adapter_name)
    kubernetes_config = _kubernetes_config(environ)
    evidence_client = KubectlEvidenceClient(config=kubernetes_config)
    http_client: httpx.AsyncClient | None = None
    try:
        container = default_container_from_env()
        if _requires_llm_binding(container.config.llm.mode):
            http_client = _new_http_client()
            identity = build_runtime_workload_identity(http_client)
            container = await _finalize_llm_bindings(
                container,
                http_client=http_client,
                identity=identity,
            )
        rca_reasoner = (
            container.llm_bindings.rca_reasoner if container.llm_bindings is not None else None
        )
        readiness = sregym_evaluation_readiness(
            evidence_client=evidence_client,
            rca_reasoner=rca_reasoner,
        )
        kubernetes_checks, probe_error = await _probe_kubernetes_evidence(
            evidence_client,
            kubernetes_config.allowed_namespaces,
        )
        rca_live = await _probe_rca(rca_reasoner)
        payload = dict(readiness_payload(readiness))
        checks = dict(payload["checks"])
        checks.update(kubernetes_checks)
        checks["rca_live_probe"] = rca_live
        payload["checks"] = checks
        payload["ready"] = readiness.ready and all(kubernetes_checks.values()) and rca_live
        if probe_error is not None:
            payload["reason_code"] = "kubernetes_evidence_probe_failed"
            payload["error_type"] = probe_error
        elif not rca_live:
            payload["reason_code"] = "rca_live_probe_failed"
        if command == "check" or not payload["ready"]:
            print(json.dumps(payload, sort_keys=True))
            return 0 if payload["ready"] else 2
        control_loop = _build_control_loop(container)
        host, _ = build_sregym_evaluation_host(
            processor=control_loop,
            evidence_client=evidence_client,
            rca_reasoner=rca_reasoner,
        )
        summary = await EvaluationRunner(adapter=adapter, host=host).run()
        print(
            json.dumps(
                {
                    "adapter_id": summary.adapter_id,
                    "session_id": summary.session_id,
                    "task_count": summary.task_count,
                    "completed_count": summary.completed_count,
                    "held_count": summary.held_count,
                    "failed_count": summary.failed_count,
                    "shadow_only": True,
                },
                sort_keys=True,
            )
        )
        return 0 if summary.failed_count == 0 else 1
    finally:
        if http_client is not None:
            await http_client.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run(args.command, args.adapter, os.environ))
    except Exception as exc:  # noqa: BLE001 - process boundary emits no secret-bearing detail
        print(
            json.dumps(
                {
                    "ready": False,
                    "reason_code": "evaluation_runner_startup_failed",
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
