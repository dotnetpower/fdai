from __future__ import annotations

import base64
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from fdai_deployment_cli.lifecycle_enrollment import (
    installation_key_id,
    raw_installation_public_key,
)
from kubernetes import config  # type: ignore[import-untyped]
from kubernetes.client.exceptions import ApiException  # type: ignore[import-untyped]

from fdai_lifecycle_agent import cli, enrollment_cli, kube
from fdai_lifecycle_agent.enrollment import derive_enrollment_facts
from fdai_lifecycle_agent.hub_client import HttpHubClient, HubProtocolError
from fdai_lifecycle_agent.workload import Manifest, WorkloadError

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
NAMESPACE = "fdai-app"
DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def workload(
    kind: str = "Deployment",
    *,
    name: str = "core",
    entity: str | None = "core",
    version: str | None = "1.4.0",
    revision: str | None = "15",
    image: str = f"registry.example/core@{DIGEST}",
    status: dict[str, Any] | None = None,
    spec: dict[str, Any] | None = None,
) -> Manifest:
    labels = {}
    if entity is not None:
        labels["fdai.io/entity"] = entity
    if version is not None:
        labels["app.kubernetes.io/version"] = version
    annotations = {} if revision is None else {"fdai.io/schema-revision": revision}
    pod = {"spec": {"containers": [{"name": "app", "image": image}]}}
    body: dict[str, Any] = {"template": pod}
    if kind == "CronJob":
        body = {"jobTemplate": {"spec": {"template": pod}}}
    return {
        "metadata": {
            "name": name,
            "namespace": NAMESPACE,
            "generation": 3,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": spec if spec is not None else {"replicas": 2, **body},
        "status": status
        if status is not None
        else {
            "observedGeneration": 3,
            "replicas": 2,
            "updatedReplicas": 2,
            "availableReplicas": 2,
            "readyReplicas": 2,
        },
    }


class Source:
    def __init__(
        self,
        deployments: Sequence[Manifest] = (),
        cronjobs: Sequence[Manifest] = (),
        error: WorkloadError | None = None,
    ) -> None:
        self.deployments, self.cronjobs, self.error = deployments, cronjobs, error
        self.calls = 0

    def list_entity_workloads(self) -> tuple[Sequence[Manifest], Sequence[Manifest]]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.deployments, self.cronjobs


def derive(*deployments: Manifest, cronjobs: Sequence[Manifest] = ()) -> Any:
    return derive_enrollment_facts(Source(deployments, cronjobs), namespace=NAMESPACE, now=NOW)


def test_a_healthy_release_stamped_entity_is_reported_from_the_cluster() -> None:
    entities, reported = derive(workload())

    assert entities == [{"entity_id": "core", "kind": "workload"}]
    assert reported["schema_revision"] == 15
    assert reported["observed_at"] == NOW.isoformat()
    assert reported["entities"] == {
        "core": {"release_id": "1.4.0", "artifact_digests": [DIGEST], "health": "healthy"}
    }
    assert isinstance(reported["digest"], str) and len(reported["digest"]) == 64
    assert derive(workload())[1]["digest"] == reported["digest"]
    assert (
        derive(workload(image=f"registry.example/core@{OTHER_DIGEST}"))[1]["digest"]
        != reported["digest"]
    )


def test_a_workload_without_a_release_label_reports_explicit_absence_not_a_version() -> None:
    _, reported = derive(workload(version=None, revision=None))

    assert reported["schema_revision"] == 0
    assert reported["entities"] == {
        "core": {"release_id": None, "artifact_digests": [], "health": "unknown"}
    }


@pytest.mark.parametrize(
    ("status", "health"),
    [
        ({"observedGeneration": 3, "replicas": 2, "availableReplicas": 1}, "degraded"),
        ({"observedGeneration": 3, "replicas": 2}, "unhealthy"),
        (
            {
                "observedGeneration": 2,
                "replicas": 2,
                "updatedReplicas": 2,
                "availableReplicas": 2,
                "readyReplicas": 2,
            },
            "degraded",
        ),
    ],
)
def test_health_comes_from_rollout_status(status: dict[str, Any], health: str) -> None:
    _, reported = derive(workload(status=status))

    assert reported["entities"]["core"]["health"] == health


def test_a_scaled_to_zero_deployment_is_unhealthy_and_cronjobs_alone_are_unknown() -> None:
    zero = workload(spec={"replicas": 0, "template": {"spec": {"containers": []}}}, status={})
    assert derive(zero)[1]["entities"]["core"]["health"] == "unhealthy"

    cron = workload("CronJob", name="nightly", image=f"registry.example/job@{OTHER_DIGEST}")
    state = derive(cronjobs=[cron])[1]["entities"]["core"]
    assert state == {"release_id": "1.4.0", "artifact_digests": [OTHER_DIGEST], "health": "unknown"}


def test_entities_group_their_workloads_and_the_worst_health_wins() -> None:
    entities, reported = derive(
        workload(name="api"),
        workload(name="worker", status={"observedGeneration": 3, "replicas": 2}),
        workload(name="console", entity="console", image=f"registry.example/c@{OTHER_DIGEST}"),
    )

    assert [entity["entity_id"] for entity in entities] == ["console", "core"]
    assert reported["entities"]["core"]["health"] == "unhealthy"
    assert reported["entities"]["console"]["artifact_digests"] == [OTHER_DIGEST]


@pytest.mark.parametrize(
    ("workloads", "reason"),
    [
        ([], "enrollment_no_entities_observed"),
        ([workload(entity="Bad_Id")], "enrollment_entity_invalid"),
        ([workload(entity=None)], "enrollment_entity_invalid"),
        ([workload(version="latest")], "enrollment_release_ambiguous"),
        (
            [workload(name="a", version="1.4.0"), workload(name="b", version="1.5.0")],
            "enrollment_release_ambiguous",
        ),
        (
            [workload(name="a", version="1.4.0"), workload(name="b", version=None)],
            "enrollment_release_ambiguous",
        ),
        ([workload(revision=None)], "enrollment_schema_revision_unobserved"),
        ([workload(revision="-1")], "enrollment_schema_revision_unobserved"),
        ([workload(revision="2147483648")], "enrollment_schema_revision_unobserved"),
        (
            [workload(name="a"), workload(name="b", entity="other", revision="16")],
            "enrollment_schema_revision_ambiguous",
        ),
    ],
)
def test_ambiguous_or_unobserved_facts_are_refused_not_guessed(
    workloads: list[Manifest], reason: str
) -> None:
    with pytest.raises(WorkloadError, match=reason):
        derive(*workloads)


def test_a_workload_in_another_namespace_and_too_many_entities_are_refused() -> None:
    foreign = workload()
    foreign["metadata"]["namespace"] = "other"
    with pytest.raises(WorkloadError, match="enrollment_entity_invalid"):
        derive(foreign)
    many = [workload(name=f"w{index}", entity=f"e{index}") for index in range(65)]
    with pytest.raises(WorkloadError, match="enrollment_too_many_entities"):
        derive(*many)


# --- command ---------------------------------------------------------------


def declaration(**changes: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": "fdai.lifecycle-installation-declaration.v1",
        "installation_id": "installation-alpha",
        "settings": {
            "channel": "stable",
            "version_range": ">=1.4.0 <2.0.0",
            "region": "korea-central",
            "allowed_regions": ["korea-central"],
            "windows": [
                {
                    "start": "11:30:00",
                    "duration": "PT1H",
                    "timezone": "Asia/Seoul",
                    "allows_downtime": False,
                }
            ],
        },
        "configuration": {
            "schema": {"replicas": {"default": 1, "x-fdai-owner": "customer"}},
            "environment": {},
            "entity_overrides": [{"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 2}}],
        },
    }
    return document | changes


class Hub:
    def __init__(self, error: HubProtocolError | None = None) -> None:
        self.error = error
        self.requests: list[tuple[str, bytes, bytes]] = []

    def submit_enrollment_request(
        self, installation_id: str, signed_payload: bytes, proof: bytes
    ) -> None:
        self.requests.append((installation_id, signed_payload, proof))
        if self.error is not None:
            raise self.error


class Fixture:
    def __init__(self, tmp_path: Path) -> None:
        self.private = tmp_path / "private"
        self.private.mkdir(mode=0o700)
        self.key = Ed25519PrivateKey.generate()
        self.key_path = self.write(
            "installation.pem",
            self.key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
        )
        self.declaration_path = self.write("declaration.json", json.dumps(declaration()).encode())
        self.hub = Hub()
        self.source = Source([workload()])

    def write(self, name: str, content: bytes, mode: int = 0o600) -> Path:
        path = self.private / name
        path.write_bytes(content)
        path.chmod(mode)
        return path

    def run(self, *extra: str, hub: Hub | None = None, source: Source | None = None) -> int:
        chosen_hub = hub or self.hub
        chosen_source = source or self.source

        @contextmanager
        def connect_hub(url: str, scope: str, timeout: float) -> Iterator[Hub]:
            assert (url, scope, timeout) == (
                "https://hub.example.com",
                "api://hub-api/.default",
                10.0,
            )
            yield chosen_hub

        return cli.main(
            [
                "enroll",
                "--installation-id",
                "installation-alpha",
                "--installation-key",
                str(self.key_path),
                "--declaration",
                str(self.declaration_path),
                "--namespace",
                NAMESPACE,
                "--hub-url",
                "https://hub.example.com",
                "--hub-scope",
                "api://hub-api/.default",
                *extra,
            ],
            clock=lambda: NOW,
            connect_enrollment_source=lambda namespace: chosen_source,
            connect_enrollment_hub=connect_hub,
        )


@pytest.fixture
def fixture(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)


def test_enroll_signs_and_submits_exactly_one_request_and_prints_only_public_facts(
    fixture: Fixture, capsys: pytest.CaptureFixture[str]
) -> None:
    assert fixture.run() == 0

    ((installation_id, payload, proof),) = fixture.hub.requests
    assert installation_id == "installation-alpha"
    fixture.key.public_key().verify(proof, payload)
    document = json.loads(payload)
    assert set(document) == {
        "installation_id",
        "settings",
        "configuration",
        "entities",
        "reported",
        "installation_key",
        "requested_at",
    }
    assert document["requested_at"] == NOW.isoformat()
    assert document["settings"] == declaration()["settings"]
    assert document["configuration"] == declaration()["configuration"]
    assert document["entities"] == [{"entity_id": "core", "kind": "workload"}]
    assert "product" not in document["settings"]
    key_id = installation_key_id(raw_installation_public_key(fixture.key))
    out = capsys.readouterr()
    assert json.loads(out.out) == {
        "installation_id": "installation-alpha",
        "installation_key_id": key_id,
        "enrollment": "pending",
        "submit_before": (NOW + timedelta(minutes=5)).isoformat(),
    }
    private_text = fixture.key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    for stream in (out.out, out.err):
        assert base64.b64encode(private_text).decode() not in stream
        assert "BEGIN" not in stream


@pytest.mark.parametrize(
    "mutation",
    ["mode", "missing", "mismatch", "unknown-field", "product", "secret", "extra-key", "duplicate"],
)
def test_the_declaration_is_strict_and_nothing_is_invented_or_sent(
    fixture: Fixture, mutation: str
) -> None:
    document = declaration()
    raw: bytes | None = None
    if mutation == "mode":
        fixture.declaration_path.chmod(0o644)
    elif mutation == "missing":
        fixture.declaration_path.unlink()
    elif mutation == "mismatch":
        document["installation_id"] = "installation-beta"
    elif mutation == "unknown-field":
        document["settings"]["plan_duration"] = "PT30M"
    elif mutation == "product":
        document["settings"]["product"] = "fdai"
    elif mutation == "secret":
        document["configuration"]["environment"] = {"password": "hunter2hunter2"}
    elif mutation == "extra-key":
        document["extra"] = True
    else:
        raw = b'{"schema": "x", "schema": "y"}'
    if mutation not in {"mode", "missing"}:
        fixture.declaration_path.write_bytes(raw or json.dumps(document).encode())

    assert fixture.run() == 2
    assert fixture.hub.requests == []
    assert fixture.source.calls == 0


def test_the_key_must_be_an_owner_only_ed25519_pem(fixture: Fixture) -> None:
    fixture.key_path.chmod(0o644)
    assert fixture.run() == 2
    assert fixture.hub.requests == []


def test_cluster_failures_and_unobserved_facts_submit_nothing(fixture: Fixture) -> None:
    for source in (
        Source(error=WorkloadError("enrollment_source_unavailable")),
        Source([workload(revision=None)]),
        Source([]),
    ):
        assert fixture.run(source=source) == 2
    assert fixture.hub.requests == []


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "61"])
def test_the_timeout_is_bounded(fixture: Fixture, timeout: str) -> None:
    assert fixture.run("--timeout-seconds", timeout) == 2
    assert fixture.hub.requests == []


def test_an_existing_record_is_a_safe_idempotent_conflict(
    fixture: Fixture, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = Hub(HubProtocolError("conflict", code="installation_exists"))

    assert fixture.run(hub=hub) == 3
    assert len(hub.requests) == 1
    err = capsys.readouterr().err
    assert "nothing was changed" in err and "pending enrollment list" in err


def test_a_hub_refusal_is_reported_without_retry(
    fixture: Fixture, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = Hub(HubProtocolError("stale", code="enrollment_proof_stale"))

    assert fixture.run(hub=hub) == 3
    assert len(hub.requests) == 1
    assert "enrollment_proof_stale" in capsys.readouterr().err


def test_an_uncertain_delivery_is_not_retried_and_points_at_the_pending_list(
    fixture: Fixture, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = Hub(HubProtocolError("Hub enrollment request failed: ReadTimeout"))

    assert fixture.run(hub=hub) == 4
    assert len(hub.requests) == 1
    err = capsys.readouterr().err
    assert "unknown" in err and "pending enrollment list" in err


def test_the_default_hub_client_posts_only_the_signed_bytes_to_the_enrollment_request_route() -> (
    None
):
    import httpx

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"enrollment": "pending"})

    with HttpHubClient(
        "https://hub.example.com",
        transport=httpx.MockTransport(handler),
        authorization=lambda: "token-value",
    ) as client:
        client.submit_enrollment_request("installation-alpha", b"payload", b"proof")

    (request,) = seen
    assert request.method == "POST"
    assert request.url.path == "/v1/installations/installation-alpha/enrollment-request"
    assert json.loads(request.content) == {
        "signed_payload": base64.b64encode(b"payload").decode(),
        "proof": base64.b64encode(b"proof").decode(),
    }
    assert request.headers["authorization"] == "Bearer token-value"


def test_a_transport_failure_is_not_retried() -> None:
    import httpx

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    with HttpHubClient(
        "https://hub.example.com",
        transport=httpx.MockTransport(handler),
        authorization=lambda: "token-value",
    ) as client:
        with pytest.raises(HubProtocolError) as raised:
            client.submit_enrollment_request("installation-alpha", b"payload", b"proof")

    assert calls == 1
    assert raised.value.code == ""


def test_enroll_has_no_kubeconfig_option_and_the_default_source_is_in_cluster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["enroll", "--kube-context", "any"])
    load = Mock()
    kubeconfig = Mock(side_effect=AssertionError("unexpected kubeconfig fallback"))
    monkeypatch.setattr(config, "load_incluster_config", load)
    monkeypatch.setattr(config, "new_client_from_config", kubeconfig)
    monkeypatch.setattr(kube, "ApiClient", Mock())

    enrollment_cli.connect_in_cluster_source(NAMESPACE)

    load.assert_called_once()
    kubeconfig.assert_not_called()


def kube_cluster(monkeypatch: pytest.MonkeyPatch) -> tuple[kube.KubernetesCluster, Mock]:
    api = Mock()
    monkeypatch.setattr(config, "load_incluster_config", Mock())
    monkeypatch.setattr(kube, "ApiClient", Mock(return_value=api))
    return kube.KubernetesCluster(in_cluster=True, namespace=NAMESPACE), api


def test_the_cluster_lists_only_labelled_deployments_and_cronjobs_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster, api = kube_cluster(monkeypatch)
    api.call_api.side_effect = [{"items": [workload()]}, {"items": []}]

    deployments, cronjobs = cluster.list_entity_workloads()

    assert len(deployments) == 1 and cronjobs == []
    calls = api.call_api.call_args_list
    assert [call.args for call in calls] == [
        ("/apis/apps/v1/namespaces/{namespace}/deployments", "GET"),
        ("/apis/batch/v1/namespaces/{namespace}/cronjobs", "GET"),
    ]
    for call in calls:
        assert call.kwargs["path_params"] == {"namespace": NAMESPACE}
        assert call.kwargs["query_params"] == [
            ("labelSelector", "fdai.io/entity"),
            ("limit", "100"),
        ]
        assert call.kwargs["_request_timeout"] == 10.0


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        ({"items": [], "metadata": {"continue": "token"}}, "enrollment_source_too_large"),
        ({"items": "nope"}, "enrollment_source_too_large"),
        ({}, "enrollment_source_unavailable"),
        (ApiException(status=403), "enrollment_source_unavailable"),
        (OSError("down"), "enrollment_source_unavailable"),
    ],
)
def test_oversized_or_failed_listing_is_refused_without_following_a_page(
    monkeypatch: pytest.MonkeyPatch, response: Any, reason: str
) -> None:
    cluster, api = kube_cluster(monkeypatch)
    api.call_api.side_effect = [response]

    with pytest.raises(WorkloadError, match=reason):
        cluster.list_entity_workloads()

    assert api.call_api.call_count == 1


@pytest.mark.parametrize(
    "channel", ["DEV", "RELEASE_CANDIDATE", "RELEASE", "custom-pilot", "stable"]
)
def test_declaration_accepts_every_real_channel_name(tmp_path: Path, channel: str) -> None:
    from fdai_lifecycle_agent.installation_declaration import load_declaration

    document = declaration()
    document["settings"]["channel"] = channel
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "declaration.json"
    path.write_text(json.dumps(document))
    path.chmod(0o600)
    assert load_declaration(path).settings.channel == channel


@pytest.mark.parametrize("channel", ["", "1dev", "dev channel", "DEV/../x", "x" * 65])
def test_declaration_still_rejects_malformed_channel_names(tmp_path: Path, channel: str) -> None:
    from fdai_lifecycle_agent.installation_declaration import DeclarationError, load_declaration

    document = declaration()
    document["settings"]["channel"] = channel
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "declaration.json"
    path.write_text(json.dumps(document))
    path.chmod(0o600)
    with pytest.raises(DeclarationError):
        load_declaration(path)
