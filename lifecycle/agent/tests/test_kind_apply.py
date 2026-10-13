"""Apply, verify, and roll back against a real local kind cluster.

Opt in with ``FDAI_LIFECYCLE_KIND_CONTEXT=kind-<cluster>``. Any other context, including an AKS
one, skips the test. It creates one namespace, runs v1, v2, and a broken v3 of the demo workload
through the agent, and deletes the namespace. The kind node pulls the public images by digest.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

from fdai_lifecycle_agent.workload import FIELD_MANAGER, rollout_complete

if TYPE_CHECKING:
    from conftest import Harness

CONTEXT = os.environ.get("FDAI_LIFECYCLE_KIND_CONTEXT", "")
REPOSITORY = "docker.io/nginxinc/nginx-unprivileged"
V1 = "sha256:65e3e85dbaed8ba248841d9d58a899b6197106c23cb0ff1a132b7bfe0547e4c0"  # 1.27-alpine
V2 = "sha256:7377697a821c131a924a7105fafbe7414db4e9fcc77a6f08f776f33f141ec3f8"  # 1.28-alpine
V3 = "sha256:" + "0" * 64  # no such image

pytestmark = [
    pytest.mark.skipif(
        not CONTEXT.startswith("kind-") or shutil.which("kind") is None,
        reason="set FDAI_LIFECYCLE_KIND_CONTEXT to a kind context to run",
    ),
    pytest.mark.timeout(600),
]


@pytest.fixture
def namespace() -> Iterator[str]:
    from kubernetes import client, config  # type: ignore[import-untyped]

    api_client = config.new_client_from_config(context=CONTEXT)
    core = client.CoreV1Api(api_client)
    name = f"fdai-lifecycle-{uuid.uuid4().hex[:8]}"
    core.create_namespace({"metadata": {"name": name}})
    try:
        yield name
    finally:
        core.delete_namespace(name)
        api_client.close()


def test_upgrade_then_roll_back_a_broken_release(harness: Harness, namespace: str) -> None:
    from fdai_lifecycle_agent.kube import KubernetesCluster

    cluster = KubernetesCluster(context=CONTEXT, namespace=namespace)

    def poll(health_timeout_seconds: float) -> str:
        result = harness.apply_poll(
            cluster,
            repository=REPOSITORY,
            namespace=namespace,
            health_timeout_seconds=health_timeout_seconds,
            monotonic=time.monotonic,
            sleep=time.sleep,
        )
        assert result.reported, result
        return f"{result.outcome}/{result.reason_code}"

    def live_image() -> str:
        live = cluster.get("Deployment", "core-control-plane")
        assert live is not None and rollout_complete(live)
        assert FIELD_MANAGER in {entry["manager"] for entry in live["metadata"]["managedFields"]}
        image: str = live["spec"]["template"]["spec"]["containers"][0]["image"]
        return image

    harness.serve(harness.release_plan("1.0.0", V1, sequence=8))
    assert poll(240) == "applied/applied"
    assert live_image() == f"{REPOSITORY}@{V1}"
    assert cluster.get("Service", "core-control-plane") is not None

    harness.serve(harness.release_plan("1.1.0", V2, sequence=9))
    assert poll(240) == "applied/applied"
    assert live_image() == f"{REPOSITORY}@{V2}"

    harness.serve(harness.release_plan("1.2.0", V3, sequence=10))
    assert poll(30) == "rolled-back/health_check_failed"
    assert live_image() == f"{REPOSITORY}@{V2}"

    outcomes = [report.outcome for _, _, report in harness.hub.reports]
    assert outcomes == ["apply-started", "applied"] * 2 + ["apply-started", "rolled-back"]
    assert len(harness.hub.states) == 3
