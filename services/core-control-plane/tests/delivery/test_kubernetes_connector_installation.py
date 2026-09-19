"""Observer installation previews preserve non-root private-material and read-only boundaries."""

import os
import stat

import pytest
from fdai.delivery.kubernetes_connector_material import (
    MATERIAL_FILES,
    material_digest,
    stage_connector_material,
)
from fdai.delivery.kubernetes_connector_runtime import private_file


def mounted_material(tmp_path):
    source = tmp_path / "mounted"
    generation = source / "..generation-one"
    generation.mkdir(parents=True)
    contents = {name: ("synthetic-" + name).encode() for name in MATERIAL_FILES}
    for name, content in contents.items():
        path = generation / name
        path.write_bytes(content)
        path.chmod(0o440)
        (source / name).symlink_to(path)
    return source, contents


def test_non_root_staging_preserves_worker_private_file_contract_and_replay(tmp_path) -> None:
    source, contents = mounted_material(tmp_path)
    destination = tmp_path / "private"
    digest = material_digest(contents)
    assert stage_connector_material(source, destination, expected_digest=digest)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    for name, content in contents.items():
        assert private_file(destination / name) == content
        assert (destination / name).stat().st_uid == os.getuid()
    assert not stage_connector_material(source, destination, expected_digest=digest)
    assert not list(tmp_path.glob(".connector-material-*"))


@pytest.mark.parametrize("case", ["escape", "writable", "oversize", "generation", "digest"])
def test_invalid_projection_never_publishes_partial_material(tmp_path, case) -> None:
    source, contents = mounted_material(tmp_path)
    original = (source / "client.key").resolve()
    if case == "escape":
        outside = tmp_path / "other"
        outside.write_bytes(b"synthetic")
        outside.chmod(0o440)
        (source / "client.key").unlink()
        (source / "client.key").symlink_to(outside)
    elif case == "writable":
        original.chmod(0o640)
    elif case == "oversize":
        original.chmod(0o600)
        original.write_bytes(b"a" * 131073)
        original.chmod(0o440)
    elif case == "generation":
        second = source / "..generation-two"
        second.mkdir()
        path = second / "client.key"
        path.write_bytes(contents["client.key"])
        path.chmod(0o440)
        (source / "client.key").unlink()
        (source / "client.key").symlink_to(path)
    digest = "sha256:" + "a" * 64 if case == "digest" else material_digest(contents)
    destination = tmp_path / "private"
    with pytest.raises(ValueError):
        stage_connector_material(source, destination, expected_digest=digest)
    assert not destination.exists()


def install_inputs(**updates):
    from fdai.delivery.kubernetes_connector_installation import ObserverInstallationInput

    return ObserverInstallationInput.model_validate(
        {
            "target_ref": "cluster-example",
            "method": "gitops",
            "egress": "private",
            "namespace": "fdai-observers",
            "name": "fdai-observer-example",
            "image": "registry.example/core@sha256:" + "a" * 64,
            "material_secret": "observer-material",
            "material_digest": "sha256:" + "b" * 64,
            "storage_class": "example-csi",
            "gateway_port": 8443,
            "api_port": 443,
            "gateway_cidrs": ("192.0.2.1/32",),
            "api_cidrs": ("192.0.2.2/32",),
            "dns_cidrs": ("192.0.2.3/32",),
            **updates,
        }
    )


def test_installation_preview_is_deterministic_non_root_and_read_only(tmp_path) -> None:
    from fdai.delivery.kubernetes_connector_installation import render_observer_installation
    from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment

    from .test_kubernetes_connector_planning import context
    from .test_kubernetes_connector_spool import NOW

    directory, digest, target = installation_material(tmp_path)
    original = context()
    inputs = install_inputs(target_ref=target, material_digest=digest)
    proposal = propose_observer_deployment(
        context(
            target_ref=target,
            observed_at=NOW,
            expires_at=NOW.replace(minute=10),
            facts=tuple(
                fact.model_copy(
                    update={
                        "target_ref": target,
                        "observed_at": NOW,
                        "expires_at": NOW.replace(minute=5),
                    }
                )
                for fact in original.facts
            ),
        ),
        now=NOW,
    )
    result = render_observer_installation(inputs, proposal, now=NOW, material_directory=directory)
    assert result == render_observer_installation(
        inputs, proposal, now=NOW, material_directory=directory
    )
    assert result["execution_authority"] is False and result["installation_ready"] is False
    resources = {item["kind"]: item for item in result["documents"]}
    assert len(resources) == 6
    for rule in resources["ClusterRole"]["rules"]:
        assert set(rule["verbs"]) <= {"list", "get"}
        assert not {"*", "secrets", "configmaps"} & set(rule["resources"])
    job = resources["CronJob"]["spec"]
    assert job["suspend"] is True
    assert job["concurrencyPolicy"] == "Forbid"
    pod = job["jobTemplate"]["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    for container in pod["initContainers"] + pod["containers"]:
        assert container["securityContext"]["runAsNonRoot"] is True
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
        assert container["image"] == install_inputs().image
    assert resources["NetworkPolicy"]["spec"]["ingress"] == []
    assert resources["NetworkPolicy"]["spec"]["egress"][0]["ports"] == [
        {"protocol": "TCP", "port": 8443}
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"namespace": "kube-system"},
        {"image": "registry.example/core:latest"},
        {"gateway_cidrs": ("0.0.0.0/0",)},
        {"dns_cidrs": ("127.0.0.1/32",)},
    ],
)
def test_installation_preview_rejects_unsafe_inputs(changes) -> None:
    with pytest.raises(ValueError):
        install_inputs(**changes)


def test_installation_preview_rejects_stale_blocked_and_foreign_proposals(tmp_path) -> None:
    from datetime import timedelta

    from fdai.delivery.kubernetes_connector_installation import render_observer_installation
    from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment

    from .test_kubernetes_connector_planning import NOW, context

    for inputs, proposal, now in (
        (
            install_inputs(),
            propose_observer_deployment(context(states={"azure_policy": "denied"}), now=NOW),
            NOW,
        ),
        (
            install_inputs(target_ref="other-cluster"),
            propose_observer_deployment(context(), now=NOW),
            NOW,
        ),
        (
            install_inputs(),
            propose_observer_deployment(context(), now=NOW),
            NOW + timedelta(minutes=10),
        ),
    ):
        with pytest.raises(ValueError):
            render_observer_installation(inputs, proposal, now=now, material_directory=tmp_path)


def test_real_tls_material_staging_reaches_existing_observer_runtime(tmp_path) -> None:
    import json
    import ssl

    from fdai.delivery.kubernetes_connector_runtime import connector_tls, load_connector_config

    from .test_kubernetes_connector_gateway import certificates
    from .test_kubernetes_connector_spool import registration

    _, (_, principal) = certificates(tmp_path)
    source = tmp_path / "mounted"
    source.mkdir()
    destination = tmp_path / "private"
    config = {
        "role": "observer",
        "registration_path": str(destination / "registrations.json"),
        "tls_ca_path": str(destination / "ca.pem"),
        "tls_certificate_path": str(destination / "client.pem"),
        "tls_key_path": str(destination / "client.key"),
        "gateway_origin": "https://gateway.example",
        "observer_principal_ref": principal,
        "stream_id": "example",
        "producer_revision": "sha256:" + "a" * 64,
        "spool_directory": "/spool/snapshots",
        "api_server": "https://kubernetes.default.svc",
        "api_ca_path": "/api-identity/ca.crt",
        "api_token_path": "/api-identity/token",
    }
    contents = {
        "config.json": json.dumps(config).encode(),
        "registrations.json": json.dumps(
            [registration().model_copy(update={"principal_ref": principal}).model_dump(mode="json")]
        ).encode(),
        "ca.pem": (tmp_path / "ca.pem").read_bytes(),
        "client.pem": (tmp_path / "client.pem").read_bytes(),
        "client.key": (tmp_path / "client.key").read_bytes(),
    }
    for name, value in contents.items():
        (source / name).write_bytes(value)
        (source / name).chmod(0o440)
    assert stage_connector_material(source, destination, expected_digest=material_digest(contents))
    configured = load_connector_config(destination / "config.json")
    tls = connector_tls(configured)
    assert tls.verify_mode == ssl.CERT_REQUIRED and tls.check_hostname
    assert configured.observer_principal_ref == principal


def test_staging_rejects_changed_existing_material_without_overwrite(tmp_path) -> None:
    source, contents = mounted_material(tmp_path)
    destination = tmp_path / "private"
    digest = material_digest(contents)
    stage_connector_material(source, destination, expected_digest=digest)
    (destination / "client.key").write_bytes(b"changed-test-content")
    with pytest.raises(ValueError, match="replaced"):
        stage_connector_material(source, destination, expected_digest=digest)
    assert (destination / "client.key").read_bytes() == b"changed-test-content"


def test_failed_staging_removes_only_its_temporary_directory(tmp_path, monkeypatch) -> None:
    from fdai.delivery import kubernetes_connector_material as material

    source, contents = mounted_material(tmp_path)
    destination = tmp_path / "private"

    def fail(*args):
        raise OSError("injected rename failure")

    monkeypatch.setattr(material.os, "rename", fail)
    with pytest.raises(OSError):
        stage_connector_material(source, destination, expected_digest=material_digest(contents))
    assert not destination.exists()
    assert not list(tmp_path.glob(".connector-material-*"))
    assert source.exists()


def test_material_command_real_process_stages_and_replays_without_credentials(tmp_path) -> None:
    import json
    import subprocess
    import sys

    source, contents = mounted_material(tmp_path)
    destination = tmp_path / "private"
    command = [
        sys.executable,
        "-m",
        "fdai.delivery.kubernetes_connector_material",
        "--source",
        str(source),
        "--destination",
        str(destination),
        "--expected-digest",
        material_digest(contents),
    ]
    for expected in ("staged", "unchanged"):
        result = subprocess.run(  # noqa: S603 - fixed interpreter/module and pytest-owned paths
            command, capture_output=True, text=True, timeout=10, check=True
        )
        assert json.loads(result.stdout) == {"status": expected}
        assert result.stderr == ""
        assert all(content.decode() not in result.stdout for content in contents.values())
    for name, content in contents.items():
        assert private_file(destination / name) == content


def installation_material(tmp_path, *, config_changes=None, registration_changes=None):
    import json

    from .test_kubernetes_connector_gateway import certificates
    from .test_kubernetes_connector_spool import registration

    _, (_, principal) = certificates(tmp_path)
    registered = registration().model_dump(mode="json")
    registered.update(
        {
            "principal_ref": principal,
            "namespaces": ["fdai-observers"],
            **(registration_changes or {}),
        }
    )
    config = {
        "role": "observer",
        "registration_path": "/private/material/registrations.json",
        "tls_ca_path": "/private/material/ca.pem",
        "tls_certificate_path": "/private/material/client.pem",
        "tls_key_path": "/private/material/client.key",
        "allow_cluster_resources": True,
        "gateway_origin": "https://gateway.example:8443",
        "observer_principal_ref": principal,
        "stream_id": "example",
        "producer_revision": "sha256:" + "a" * 64,
        "spool_directory": "/spool/snapshots",
        "api_server": "https://kubernetes.default.svc",
        "api_ca_path": "/api-identity/ca.crt",
        "api_token_path": "/api-identity/token",
        **(config_changes or {}),
    }
    contents = {
        "config.json": json.dumps(config).encode(),
        "registrations.json": json.dumps([registered]).encode(),
        **{name: (tmp_path / name).read_bytes() for name in ("ca.pem", "client.pem", "client.key")},
    }
    directory = tmp_path / "validated-material"
    directory.mkdir(mode=0o700)
    for name, content in contents.items():
        (directory / name).write_bytes(content)
        (directory / name).chmod(0o600)
    return directory, material_digest(contents), registered["scope"]["cluster_ref"]


@pytest.mark.parametrize(
    "case", ["valid", "target", "namespace", "port", "path", "api", "scope", "revoked", "digest"]
)
def test_installation_material_is_bound_to_actual_workload(tmp_path, case) -> None:
    from fdai.delivery.kubernetes_connector_installation import validate_installation_material

    from .test_kubernetes_connector_spool import NOW

    changes = {
        "port": {"gateway_origin": "https://gateway.example:443"},
        "path": {"spool_directory": "/ephemeral/snapshots"},
        "api": {"api_server": "https://other-cluster.example"},
        "scope": {"allow_cluster_resources": False},
    }
    directory, digest, target = installation_material(
        tmp_path,
        config_changes=changes.get(case),
        registration_changes={"revoked": True} if case == "revoked" else None,
    )
    inputs = install_inputs(
        target_ref="foreign-cluster" if case == "target" else target,
        namespace="other-namespace" if case == "namespace" else "fdai-observers",
        material_digest="sha256:" + "f" * 64 if case == "digest" else digest,
    )
    if case == "valid":
        validate_installation_material(inputs, directory=directory, now=NOW)
    else:
        with pytest.raises(ValueError):
            validate_installation_material(inputs, directory=directory, now=NOW)


def test_explicit_unknown_candidate_renders_only_an_inspection_draft(tmp_path) -> None:
    from datetime import timedelta

    from fdai.delivery.kubernetes_connector_installation import render_observer_installation
    from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment

    from .test_kubernetes_connector_planning import context
    from .test_kubernetes_connector_spool import NOW

    directory, digest, target = installation_material(tmp_path)
    proposal = propose_observer_deployment(
        context(
            target_ref=target, facts=(), observed_at=NOW, expires_at=NOW + timedelta(minutes=5)
        ),
        now=NOW,
    )
    inputs = install_inputs(target_ref=target, material_digest=digest)
    draft = render_observer_installation(inputs, proposal, now=NOW, material_directory=directory)
    assert draft["recommended"] is False
    assert "admission" in draft["missing"]
    assert draft["execution_authority"] is False
    assert draft["installation_ready"] is False
    with pytest.raises(ValueError):
        render_observer_installation(
            inputs.model_copy(update={"method": "run_command"}),
            proposal,
            now=NOW,
            material_directory=directory,
        )


@pytest.mark.parametrize(
    "case",
    ["allowed", "forbidden", "redirect", "throttled", "foreign", "drift", "mutated", "pod-denied"],
)
async def test_server_admission_uses_only_exact_dry_run_requests(tmp_path, case) -> None:
    import json
    import ssl
    from datetime import timedelta

    import httpx
    from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment
    from fdai.delivery.kubernetes_connector_read_preflight import KubernetesObserverReadPreflight

    from .test_kubernetes_connector_planning import context
    from .test_kubernetes_connector_spool import NOW

    directory, digest, target = installation_material(tmp_path)
    proposal = propose_observer_deployment(
        context(
            target_ref=target, facts=(), observed_at=NOW, expires_at=NOW + timedelta(minutes=5)
        ),
        now=NOW,
    )
    inputs = install_inputs(target_ref=target, material_digest=digest)
    calls = []

    class Auth:
        async def headers(self):
            return {"Authorization": "Bearer ephemeral-test"}

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            assert request.url.path == "/api/v1/namespaces/kube-system"
            foreign = case == "foreign" or (case == "drift" and len(calls) > 1)
            return httpx.Response(
                200,
                json={
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {
                        "name": "kube-system",
                        "uid": "other" if foreign else "cluster-uid",
                    },
                },
            )
        assert request.method == "POST"
        assert dict(request.url.params) == {
            "dryRun": "All",
            "fieldValidation": "Strict",
            "fieldManager": "fdai-observer-preflight",
        }
        assert "Authorization" in request.headers
        body = json.loads(request.content)
        if case in {"forbidden", "redirect", "throttled"}:
            return httpx.Response({"forbidden": 403, "redirect": 307, "throttled": 429}[case])
        if body["kind"] == "Pod":
            if case == "mutated":
                body["spec"]["hostNetwork"] = True
            if case == "pod-denied":
                return httpx.Response(403)
        return httpx.Response(201, json=body)

    probe = KubernetesObserverReadPreflight(
        origin="https://api.example",
        target_ref=target,
        namespace_uid="cluster-uid",
        auth=Auth(),
        tls=ssl.create_default_context(),
        now=lambda: NOW,
        transport=httpx.MockTransport(handler),
    )
    fact = await probe.collect_installation(inputs, proposal, material_directory=directory)
    assert fact.name == "admission"
    assert fact.state == ("allowed" if case == "allowed" else "unknown")
    if case == "allowed":
        assert len(calls) == 9
    if case in {"forbidden", "redirect", "throttled"}:
        assert len(calls) == 2


async def test_admission_runtime_signs_only_registered_fact_and_can_retain_it(
    tmp_path, monkeypatch
) -> None:
    import json
    from datetime import timedelta

    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment
    from fdai.delivery.kubernetes_connector_preflight import SignedObserverConstraints
    from fdai.delivery.kubernetes_connector_preflight_runtime import (
        FileObserverPreflightGrants,
        collect_admission_preflight,
    )
    from fdai.delivery.kubernetes_connector_read_preflight import KubernetesObserverReadPreflight
    from fdai.shared.providers.testing import InMemoryStateStore

    from .test_kubernetes_connector_planning import DIGEST, NOW, context
    from .test_kubernetes_connector_preflight import material

    grant, _, private = material()
    directory, digest, target = installation_material(tmp_path)
    grant = grant.model_copy(
        update={"target_ref": target, "allowed_facts": {"admission": ("kubernetes_api",)}}
    )
    proposal = propose_observer_deployment(context(target_ref=target, facts=()), now=NOW)
    paths = {
        name: tmp_path / name
        for name in ("grants.json", "key.pem", "inputs.json", "proposal.json", "probe.json")
    }
    values = {
        "grants.json": json.dumps([grant.model_dump(mode="json")]).encode(),
        "key.pem": private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
        "inputs.json": install_inputs(target_ref=target, material_digest=digest)
        .model_dump_json()
        .encode(),
        "proposal.json": proposal.model_dump_json().encode(),
    }
    config = {
        "target_ref": target,
        "discovery_digest": DIGEST,
        "issuer_ref": grant.issuer_ref,
        "producer_revision": DIGEST,
        "api_origin": "https://api.example",
        "namespace_uid": "cluster-uid",
        "api_ca_path": str(tmp_path / "ca.pem"),
        "api_token_path": str(tmp_path / "token"),
        "signing_key_path": str(paths["key.pem"]),
        "grants_path": str(paths["grants.json"]),
        "installation_inputs_path": str(paths["inputs.json"]),
        "proposal_path": str(paths["proposal.json"]),
        "material_directory": str(directory),
    }
    values["probe.json"] = json.dumps(config).encode()
    for name, content in values.items():
        paths[name].write_bytes(content)
        paths[name].chmod(0o600)
    called = []

    async def collect(self, inputs, supplied, *, material_directory):
        from fdai_service_contracts.observer_deployment import ObserverDeploymentFact

        assert (
            inputs.target_ref == target and supplied == proposal and material_directory == directory
        )
        called.append(True)
        return ObserverDeploymentFact(
            target_ref=target,
            name="admission",
            state="allowed",
            source="kubernetes_api",
            evidence_digest=DIGEST,
            observed_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )

    monkeypatch.setattr(KubernetesObserverReadPreflight, "collect_installation", collect)
    receipt = await collect_admission_preflight(paths["probe.json"], now=lambda: NOW)
    assert [fact.name for fact in receipt.context.facts] == ["admission"]
    store = InMemoryStateStore()
    reader = SignedObserverConstraints(
        store, grants=FileObserverPreflightGrants(paths["grants.json"]), now=lambda: NOW
    )
    assert await reader.retain(receipt)
    assert (await reader.read(target, now=NOW)).facts[0].name == "admission"
    paths["grants.json"].write_text(
        json.dumps(
            [
                grant.model_copy(
                    update={"allowed_facts": {"kubernetes_read": ("kubernetes_api",)}}
                ).model_dump(mode="json")
            ]
        )
    )
    with pytest.raises(ValueError, match="verifier"):
        await collect_admission_preflight(paths["probe.json"], now=lambda: NOW)
    assert len(called) == 1


async def test_admission_requests_cross_real_verified_tls(tmp_path) -> None:
    from datetime import timedelta

    from aiohttp import web
    from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment
    from fdai.delivery.kubernetes_connector_read_preflight import KubernetesObserverReadPreflight

    from .test_kubernetes_connector_gateway import certificates
    from .test_kubernetes_connector_planning import context
    from .test_kubernetes_connector_spool import NOW

    directory, digest, target = installation_material(tmp_path)
    (server_tls, _), (client_tls, _) = certificates(tmp_path)
    proposal = propose_observer_deployment(
        context(
            target_ref=target,
            facts=(),
            observed_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        ),
        now=NOW,
    )
    checks = []

    class Auth:
        async def headers(self):
            return {"Authorization": "Bearer deployment-preflight-test"}

    async def endpoint(request):
        assert request.headers["Authorization"] == "Bearer deployment-preflight-test"
        if request.method == "GET":
            assert request.path == "/api/v1/namespaces/kube-system"
            return web.json_response(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {"name": "kube-system", "uid": "cluster-uid"},
                }
            )
        assert request.method == "POST"
        assert dict(request.query) == {
            "dryRun": "All",
            "fieldValidation": "Strict",
            "fieldManager": "fdai-observer-preflight",
        }
        document = await request.json()
        checks.append(document["kind"])
        return web.json_response(document, status=201)

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", endpoint)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_tls)
        await site.start()
        probe = KubernetesObserverReadPreflight(
            origin=f"https://127.0.0.1:{runner.addresses[0][1]}",
            target_ref=target,
            namespace_uid="cluster-uid",
            auth=Auth(),
            tls=client_tls,
            now=lambda: NOW,
        )
        fact = await probe.collect_installation(
            install_inputs(target_ref=target, material_digest=digest),
            proposal,
            material_directory=directory,
        )
        assert fact.state == "allowed"
        assert checks == [
            "ServiceAccount",
            "ClusterRole",
            "ClusterRoleBinding",
            "PersistentVolumeClaim",
            "CronJob",
            "NetworkPolicy",
            "Pod",
        ]
    finally:
        await runner.cleanup()


async def test_admission_cancellation_never_retries_or_becomes_a_fact(tmp_path) -> None:
    import asyncio
    import ssl
    from datetime import timedelta

    import httpx
    from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment
    from fdai.delivery.kubernetes_connector_read_preflight import KubernetesObserverReadPreflight

    from .test_kubernetes_connector_planning import context
    from .test_kubernetes_connector_spool import NOW

    directory, digest, target = installation_material(tmp_path)
    proposal = propose_observer_deployment(
        context(
            target_ref=target, facts=(), observed_at=NOW, expires_at=NOW + timedelta(minutes=5)
        ),
        now=NOW,
    )
    calls = []

    class Auth:
        async def headers(self):
            return {"Authorization": "Bearer preflight-test"}

    async def cancel(request):
        calls.append(request.method)
        raise asyncio.CancelledError

    probe = KubernetesObserverReadPreflight(
        origin="https://api.example",
        target_ref=target,
        namespace_uid="cluster-uid",
        auth=Auth(),
        tls=ssl.create_default_context(),
        now=lambda: NOW,
        transport=httpx.MockTransport(cancel),
    )
    with pytest.raises(asyncio.CancelledError):
        await probe.collect_installation(
            install_inputs(target_ref=target, material_digest=digest),
            proposal,
            material_directory=directory,
        )
    assert calls == ["GET"]


@pytest.mark.parametrize("version", ["1.30.0", "1.34.0", "1.36.0"])
def test_rendered_resources_pass_strict_kubernetes_schemas(tmp_path, version) -> None:
    import copy
    from datetime import timedelta

    from fdai.delivery.kubernetes_connector_installation import render_observer_installation
    from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment

    from .test_kubernetes_connector_planning import context
    from .test_kubernetes_connector_spool import NOW

    validator = pytest.importorskip(
        "kubernetes_validate", reason="explicit pinned schema-validation overlay required"
    )
    directory, digest, target = installation_material(tmp_path)
    proposal = propose_observer_deployment(
        context(
            target_ref=target, facts=(), observed_at=NOW, expires_at=NOW + timedelta(minutes=5)
        ),
        now=NOW,
    )
    preview = render_observer_installation(
        install_inputs(target_ref=target, material_digest=digest),
        proposal,
        now=NOW,
        material_directory=directory,
    )
    documents = preview["documents"]
    template = next(item for item in documents if item["kind"] == "CronJob")["spec"]["jobTemplate"][
        "spec"
    ]["template"]
    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "fdai-observer-example",
            "namespace": "fdai-observers",
            **template["metadata"],
        },
        "spec": template["spec"],
    }
    for document in [*documents, pod]:
        validator.validate(document, version, strict=True)
    invalid = copy.deepcopy(pod)
    invalid["spec"]["unsupportedObserverField"] = True
    with pytest.raises(validator.ValidationError):
        validator.validate(invalid, version, strict=True)
