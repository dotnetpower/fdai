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


def test_installation_preview_rejects_stale_unknown_and_foreign_proposals(tmp_path) -> None:
    from datetime import timedelta

    from fdai.delivery.kubernetes_connector_installation import render_observer_installation
    from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment

    from .test_kubernetes_connector_planning import NOW, context

    for inputs, proposal, now in (
        (install_inputs(), propose_observer_deployment(context(facts=()), now=NOW), NOW),
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
