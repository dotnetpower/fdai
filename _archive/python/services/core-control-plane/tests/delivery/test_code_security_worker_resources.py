"""Installation output binds actual worker parsers, identities, schedules and secret references."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fdai.delivery.code_security_cli import _parser, main
from fdai.delivery.code_security_worker_resources import (
    ScanWorkerInstallConfig,
    scan_worker_resources,
)


def _config() -> ScanWorkerInstallConfig:
    return ScanWorkerInstallConfig(
        controller_namespace="scan-controller",
        controller_service_account="controller",
        scanner_namespace="code-security",
        image="example.invalid/scanner@sha256:" + "a" * 64,
        controller_source_pvc="controller-source",
        scanner_source_pvc="scanner-source",
        controller_cache_pvc="controller-cache",
        scanner_cache_pvc="scanner-cache",
        cache_subpath="snapshots/" + "b" * 64 + "/cache",
        state_secret="scan-state",
        broker_config_map="scan-broker",
        request_schedule="*/5 * * * *",
        scan_schedule="0 2 * * *",
    )


def _jobs(config: ScanWorkerInstallConfig) -> list[dict]:
    return [item for item in scan_worker_resources(config)["items"] if item["kind"] == "CronJob"]


@pytest.mark.parametrize("enabled", [False, True])
def test_schedules_bind_existing_parsers_and_credential_free_scanner_namespace(
    enabled: bool,
) -> None:
    config = replace(_config(), enabled=enabled)
    jobs = _jobs(config)
    assert len(jobs) == 2
    for job in jobs:
        assert job["metadata"]["namespace"] == config.controller_namespace
        schedule = job["spec"]
        assert schedule["suspend"] is not enabled
        assert schedule["timeZone"] == "Etc/UTC" and schedule["concurrencyPolicy"] == "Forbid"
        template = schedule["jobTemplate"]["spec"]
        assert template["backoffLimit"] == 0 and template["activeDeadlineSeconds"] == 3600
        pod = template["template"]["spec"]
        assert pod["serviceAccountName"] == config.controller_service_account
        assert pod["automountServiceAccountToken"] is True
        assert "runtimeClassName" not in pod
        assert not pod.get("initContainers")
        container = pod["containers"][0]
        args = _parser().parse_args(container["args"])
        assert args.command in {"process-scan-requests", "process-scheduled-scans"}
        assert args.scanner_runtime == "kata" and args.state_access == "restricted"
        assert args.scanner_namespace == config.scanner_namespace
        assert args.scanner_source_pvc == "scanner-source"
        assert args.scanner_cache_pvc == "scanner-cache"
        assert args.cache_dir == "/cache" and args.scanner_cache_subpath == config.cache_subpath
        assert len(args.scanner_bin) == 5
        assert container["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
        assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
        env = {item["name"]: item for item in container["env"]}
        assert env["FDAI_STATE_STORE_DSN"]["valueFrom"]["secretKeyRef"] == {
            "name": "scan-state",
            "key": "dsn",
            "optional": False,
        }
        assert not any(name.startswith("FDAI_GITHUB_APP") for name in env)
        claims = {
            item["name"]: item["persistentVolumeClaim"]
            for item in pod["volumes"]
            if "persistentVolumeClaim" in item
        }
        assert claims["source"]["claimName"] == "controller-source"
        assert claims["cache"] == {"claimName": "controller-cache", "readOnly": True}
        mount = next(item for item in container["volumeMounts"] if item["name"] == "cache")
        assert mount["readOnly"] is True and mount["subPath"] == config.cache_subpath


def test_app_credentials_are_secret_references_in_controller_only() -> None:
    config = replace(_config(), github_app_secret="read-only-app")
    rendered = scan_worker_resources(config)
    for item in rendered["items"]:
        if item.get("metadata", {}).get("namespace") == config.scanner_namespace:
            assert "secretKeyRef" not in json.dumps(item)
    for job in _jobs(config):
        container = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
        app = [item for item in container["env"] if item["name"].startswith("FDAI_GITHUB_APP_")]
        assert len(app) == 3
        assert {item["valueFrom"]["secretKeyRef"]["key"] for item in app} == {
            "client-id",
            "installation-id",
            "private-key",
        }
        assert all("value" not in item for item in app)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("image", "example.invalid/scanner:latest"),
        ("controller_namespace", "code-security"),
        ("state_secret", "invalid/value"),
        ("scanner_cache_pvc", "scanner-source"),
        ("controller_cache_pvc", "controller-source"),
        ("cache_subpath", "cache"),
        ("cache_subpath", "snapshots/../../private"),
        ("request_schedule", "* * * * * *"),
        ("request_schedule", "never"),
        ("request_schedule", "99 * * * *"),
        ("max_batch", 0),
        ("max_batch", 21),
        ("max_batch", True),
        ("enabled", 1),
    ],
)
def test_invalid_or_ambiguous_installation_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(_config(), **{field: value})


def test_installed_cli_renders_resources_without_creating_them(
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config()
    args = ["render-scanner-workers"]
    for field in (
        "controller_namespace",
        "controller_service_account",
        "scanner_namespace",
        "image",
        "controller_source_pvc",
        "scanner_source_pvc",
        "controller_cache_pvc",
        "scanner_cache_pvc",
        "cache_subpath",
        "state_secret",
        "broker_config_map",
        "request_schedule",
        "scan_schedule",
    ):
        args += ["--" + field.replace("_", "-"), getattr(config, field)]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert sum(item["kind"] == "CronJob" for item in result["resources"]["items"]) == 2
    assert all(
        item["spec"]["suspend"]
        for item in result["resources"]["items"]
        if item["kind"] == "CronJob"
    )


def test_worker_schedules_round_trip_through_official_kubernetes_models() -> None:
    from types import SimpleNamespace

    from kubernetes.client import ApiClient, V1CronJob

    client = ApiClient()
    try:
        for rendered in _jobs(_config()):
            model = client.deserialize(SimpleNamespace(data=json.dumps(rendered)), V1CronJob)
            assert model.spec.time_zone == "Etc/UTC"
            assert model.spec.concurrency_policy == "Forbid"
            assert model.spec.suspend is True
            pod = model.spec.job_template.spec.template.spec
            assert pod.service_account_name == "controller"
            assert pod.containers[0].security_context.read_only_root_filesystem is True
            assert pod.containers[0].env[1].value_from.secret_key_ref.name == "scan-state"
            assert pod.volumes[1].persistent_volume_claim.read_only is True
    finally:
        client.close()
