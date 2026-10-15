"""Opt-in real Operator lifecycle checks, not a complete FDAI installation.

Foundation must provide an exclusively owned namespace, migrated PostgreSQL, catalogs,
broker and a running Core. No prerequisite failure becomes a skipped or successful run.
The Hub transport remains an in-memory signed-plan fixture.
"""

from __future__ import annotations

import json
import os
import re
import select
import shutil
import subprocess
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from fdai_lifecycle_agent.agent import LifecycleAgent
from fdai_lifecycle_agent.dry_run import load_current_state
from fdai_lifecycle_agent.journal import WorkloadStore
from fdai_lifecycle_agent.state import LocalStateStore
from fdai_lifecycle_agent.workload import Manifest, rollout_complete

if TYPE_CHECKING:
    from conftest import Harness
    from fdai_deployment_cli.lifecycle_plan import LifecyclePlan
    from test_cross_process_resumption import _run_poll_once, _StubHub, _write_fixtures

    from fdai_lifecycle_agent.kube import KubernetesCluster
else:
    # pytest uses importlib namespaces; mypy resolves the configured tests search path.
    from .test_cross_process_resumption import _run_poll_once, _StubHub, _write_fixtures

CONTEXT = os.environ.get("FDAI_OPERATOR_KIND_CONTEXT", "")
pytestmark = [
    pytest.mark.skipif(
        not CONTEXT, reason="set FDAI_OPERATOR_KIND_CONTEXT for real Operator checks"
    ),
    pytest.mark.timeout(900),
]


@pytest.fixture
def operator_cluster() -> Iterator[tuple[Any, str, KubernetesCluster]]:
    from kubernetes import client, config  # type: ignore[import-untyped]

    from fdai_lifecycle_agent.kube import KubernetesCluster

    assert CONTEXT.startswith("kind-fdai-operator-"), "dedicated Operator kind context required"
    namespace = os.environ["FDAI_OPERATOR_KIND_NAMESPACE"]
    assert namespace.startswith("fdai-operator-")
    api = config.new_client_from_config(context=CONTEXT)
    core = client.CoreV1Api(api)
    try:
        live = core.read_namespace(namespace, _request_timeout=10)
        assert (live.metadata.labels or {}).get("fdai.io/validation-owner") == "operator-kind"
        cluster = KubernetesCluster(context=CONTEXT, namespace=namespace)
        assert cluster.get("Deployment", "operator-service") is None, "use a fresh namespace"
        assert cluster.get("Service", "operator-service-internal") is None
        try:
            yield core, namespace, cluster
        finally:
            cluster.delete("Deployment", "operator-service")
            cluster.delete("Service", "operator-service-internal")
            jobs = client.BatchV1Api(api).list_namespaced_job(
                namespace,
                label_selector="app.kubernetes.io/managed-by=fdai-lifecycle-agent",
                _request_timeout=10,
            )
            for job in jobs.items:
                cluster.delete("Job", job.metadata.name)
    finally:
        api.close()


@pytest.fixture
def reader(operator_cluster: tuple[Any, str, KubernetesCluster]) -> Iterator[httpx.Client]:
    """Use production JWT verification with an ephemeral, namespace-local public JWKS fixture."""
    core, namespace, _ = operator_cluster
    from kubernetes import client

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_key.update(kid="operator-kind", use="sig", alg="RS256")
    core.create_namespaced_config_map(
        namespace,
        {
            "metadata": {"name": "validation-jwks"},
            "data": {"jwks.json": json.dumps({"keys": [public_key]})},
        },
        _request_timeout=10,
    )
    image = os.environ["FDAI_OPERATOR_KIND_IMAGE"]
    client.AppsV1Api(core.api_client).create_namespaced_deployment(
        namespace,
        {
            "metadata": {"name": "validation-jwks"},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": "validation-jwks"}},
                "template": {
                    "metadata": {"labels": {"app": "validation-jwks"}},
                    "spec": {
                        "automountServiceAccountToken": False,
                        "containers": [
                            {
                                "name": "public-jwks",
                                "image": image,
                                "command": [
                                    "python",
                                    "-m",
                                    "http.server",
                                    "8080",
                                    "--directory",
                                    "/jwks",
                                ],
                                "volumeMounts": [
                                    {"name": "keys", "mountPath": "/jwks", "readOnly": True}
                                ],
                            }
                        ],
                        "volumes": [{"name": "keys", "configMap": {"name": "validation-jwks"}}],
                    },
                },
            },
        },
        _request_timeout=10,
    )
    core.create_namespaced_service(
        namespace,
        {
            "metadata": {"name": "validation-jwks"},
            "spec": {
                "selector": {"app": "validation-jwks"},
                "ports": [{"port": 8080, "targetPort": 8080}],
            },
        },
        _request_timeout=10,
    )
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "oid": "00000000-0000-0000-0000-000000000001",
            "aud": "operator-kind",
            "iss": "https://operator-kind.example.test",
            "iat": now,
            "exp": now + timedelta(minutes=20),
            "scp": "operator.read",
            "roles": ["Reader"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "operator-kind"},
    )
    try:
        with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=15) as http:
            yield http
    finally:
        client.AppsV1Api(core.api_client).delete_namespaced_deployment(
            "validation-jwks", namespace, _request_timeout=10
        )
        core.delete_namespaced_service("validation-jwks", namespace, _request_timeout=10)
        core.delete_namespaced_config_map("validation-jwks", namespace, _request_timeout=10)


class InterruptedApply(BaseException):
    """A process-loss boundary after a real Deployment write."""


class RecordingCluster:
    def __init__(self, cluster: KubernetesCluster) -> None:
        self.cluster = cluster
        self.writes: list[tuple[str, str]] = []
        self.crash = False
        self.verified_jobs = 0

    def apply(self, manifest: Manifest, *, dry_run: bool = False) -> None:
        self.cluster.apply(manifest, dry_run=dry_run)
        if not dry_run:
            self.writes.append(("apply", manifest["kind"]))
            if self.crash and manifest["kind"] == "Deployment":
                self.crash = False
                raise InterruptedApply

    def get(self, kind: str, name: str) -> Manifest | None:
        live = self.cluster.get(kind, name)
        if kind == "Job" and live is not None:
            conditions = live.get("status", {}).get("conditions", [])
            if any(c.get("type") == "Complete" and c.get("status") == "True" for c in conditions):
                self.verified_jobs += 1
        return live

    def delete(self, kind: str, name: str) -> None:
        self.cluster.delete(kind, name)
        self.writes.append(("delete", kind))


def _request(reader: httpx.Client, namespace: str, path: str) -> dict[str, Any]:
    """Port-forward one safe request without logging its bearer token."""
    kubectl = shutil.which("kubectl")
    assert kubectl is not None, "kubectl is required"
    process = subprocess.Popen(  # noqa: S603 - no shell; validated dedicated context and namespace.
        [
            kubectl,
            "--context",
            CONTEXT,
            "--namespace",
            namespace,
            "port-forward",
            "--address",
            "127.0.0.1",
            "service/operator-service-internal",
            ":80",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert select.select([process.stdout], [], [], 15)[0], "port-forward startup deadline"
        line = process.stdout.readline()
        match = re.search(r"127\.0\.0\.1:(\d+) ->", line)
        assert match is not None, "port-forward did not become ready"
        response = reader.get(f"http://127.0.0.1:{match[1]}{path}")
        assert response.status_code == 200, f"{path}: HTTP {response.status_code}"
        payload: dict[str, Any] = response.json()
        return payload
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_real_operator_configuration_update_failure_and_restart(
    harness: Harness,
    operator_cluster: tuple[Any, str, KubernetesCluster],
    reader: httpx.Client,
) -> None:
    core, namespace, raw_cluster = operator_cluster
    operator_image = os.environ["FDAI_OPERATOR_KIND_IMAGE"]
    schema_image = os.environ["FDAI_OPERATOR_KIND_CORE_IMAGE"]
    for image in (operator_image, schema_image):
        assert re.fullmatch(r"[a-z0-9./:-]+@sha256:[0-9a-f]{64}", image), "pin OCI manifests"
    operator_repo, operator_digest = operator_image.split("@")
    core_repo, core_digest = schema_image.split("@")
    cluster = RecordingCluster(raw_cluster)
    harness.apply_mode(cluster)
    settings = harness.settings(
        component_repositories={"operator-service": operator_repo, "core-control-plane": core_repo}
    )

    def poll(*, restarted: bool = False, timeout: float = 180) -> Any:
        deps = harness.dependencies(
            apply=harness.apply_mode(
                cluster,
                namespace=namespace,
                health_timeout_seconds=timeout,
                monotonic=time.monotonic,
                sleep=time.sleep,
            ),
            read_current_state=lambda: load_current_state(harness.state_file),
            clock=lambda: datetime.now(UTC),
            state_store=LocalStateStore(harness.state_store.path.parent)
            if restarted
            else harness.state_store,
        )
        return LifecycleAgent(settings, deps).poll_once()

    def serve(sequence: int, config_map: str) -> LifecyclePlan:
        values = {
            "workload_profile": "operator-service-v1",
            "operator_config_map_name": config_map,
            "operator_database": {"secret_name": "operator-database"},
            "schema_database": {"secret_name": "schema-reader"},
            "replicas": 1,
        }
        configuration: dict[str, object] = {
            "schema": {
                key: {
                    "default": value,
                    "x-fdai-axis": "installation-path",
                    "x-fdai-owner": "customer",
                }
                for key, value in values.items()
            },
            "environment": {},
            "entity_overrides": [{"versions": ">=1.0.0 <2.0.0", "values": {}}],
        }
        release = harness.manifest(
            version="1.0.0", operator_service=operator_digest, core_control_plane=core_digest
        )
        release["source_commit"] = os.environ["FDAI_OPERATOR_KIND_SOURCE_COMMIT"]
        release["platform_tag"] = "linux-aarch64"
        return harness.serve(
            harness.plan(
                plan_id=f"operator-kind-{sequence}",
                sequence=sequence,
                target_release_id="1.0.0",
                target_release_digest=harness.add_release(release),
                configuration_revision_digest=harness.add_configuration(configuration),
                source_state_digest=load_current_state(harness.state_file).digest,
                entity_ids=frozenset({"operator-api"}),
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
            )
        )

    def observe(config_map: str) -> tuple[int, str]:
        live = raw_cluster.get("Deployment", "operator-service")
        assert live is not None and rollout_complete(live)
        container = live["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == operator_image
        assert container["envFrom"][0]["configMapRef"]["name"] == config_map
        pods = core.list_namespaced_pod(
            namespace,
            label_selector="app.kubernetes.io/name=operator-service",
            _request_timeout=10,
        ).items
        ready = [
            p
            for p in pods
            if p.metadata.deletion_timestamp is None
            and all(c.ready for c in p.status.container_statuses or [])
        ]
        assert len(ready) == 1
        status = ready[0].status.container_statuses[0]
        assert status.image_id.endswith(operator_digest), "runtime image differs from Release"
        assert _request(reader, namespace, "/healthz") == {"status": "ok"}
        activity = _request(reader, namespace, "/agents/activity")
        assert activity["source"] == "durable-operational-projection"
        assert isinstance(activity["items"], list)
        from kubernetes import client

        assert (
            not client.BatchV1Api(core.api_client)
            .list_namespaced_job(namespace, _request_timeout=10)
            .items
        )
        generation = live["metadata"]["generation"]
        assert isinstance(generation, int)
        return generation, str(ready[0].metadata.uid)

    serve(8, "operator-config-v1")
    assert poll().outcome == "applied"
    first = observe("operator-config-v1")
    serve(9, "operator-config-v2")
    assert poll().outcome == "applied"
    before = observe("operator-config-v2")
    assert before[1] != first[1], "configuration revision did not replace the Pod"
    assert poll(restarted=True).outcome == "already-reported"
    assert observe("operator-config-v2") == before

    serve(10, "operator-config-failure")
    result = poll(timeout=45)
    assert (result.outcome, result.reason_code) == ("rolled-back", "health_check_failed")
    observe("operator-config-v2")
    interrupted_plan = serve(11, "operator-config-v1")
    cluster.crash = True
    with pytest.raises(InterruptedApply):
        poll()
    store = WorkloadStore(harness.state_store.path.parent)
    journal = store.load().journal
    assert journal is not None and journal.phase == "applying"
    root = harness.state_store.path.parent.parent
    _write_fixtures(harness, root, preserve_current_state=True)
    (root / "local-policy.json").write_text(
        json.dumps(
            {
                "schema": "fdai.lifecycle-local-policy.v1",
                "entity_ids": ["core", "operator-api"],
                "regions": ["korea-central"],
                "capability_modes": {"action:scale-service": "enforce"},
                "destructive_allowed": False,
                "max_duration_minutes": 60,
                "entity_components": {
                    "core": ["core-control-plane"],
                    "operator-api": ["operator-service"],
                },
                "component_images": {
                    "core-control-plane": core_repo,
                    "operator-service": operator_repo,
                },
            }
        )
    )
    stub = _StubHub()
    try:
        stub.plan = interrupted_plan
        recovered = _run_poll_once(
            root, stub.url, "installation-alpha", namespace, health_timeout=60, context=CONTEXT
        )
        assert recovered.returncode == 0, "recovery process failed"
        assert json.loads(recovered.stdout)["outcome"] == "rolled-back"
        restored = observe("operator-config-v2")
        replay = _run_poll_once(
            root, stub.url, "installation-alpha", namespace, health_timeout=60, context=CONTEXT
        )
        assert replay.returncode == 0, "replay process failed"
        assert json.loads(replay.stdout)["outcome"] == "already-reported"
        assert observe("operator-config-v2") == restored
        assert [r["outcome"] for r in stub.reports] == ["rolled-back"]
        assert stub.reports[0]["reason_code"] == "apply_failed"
        assert len(stub.states) == 1
    finally:
        stub.close()
    assert cluster.verified_jobs >= 4
    assert store.load().journal is None
    assert {m["kind"] for m in store.load().healthy} == {"Deployment", "Service"}
    assert [r.outcome for _, _, r in harness.hub.reports] == (
        ["apply-started", "applied"] * 2 + ["apply-started", "rolled-back", "apply-started"]
    )
    assert len(harness.hub.states) == 3
