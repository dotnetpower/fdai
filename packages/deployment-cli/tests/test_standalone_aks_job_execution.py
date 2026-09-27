from __future__ import annotations

import copy
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai_deployment_cli import standalone_aks_job_execution
from fdai_deployment_cli.aks_job_execution import (
    materialize_cronjob_execution,
    protected_cronjob_template_digest,
)
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.standalone_aks_job_execution import (
    protected_service_account_binding,
)

_REVISION = "a" * 40
_TARGET = "b" * 64
_IMAGE = "example.azurecr.io/fdai@sha256:" + "c" * 64
_SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
_TENANT = "00000000-0000-0000-0000-000000000001"
_CLIENT_ID = "00000000-0000-0000-0000-000000000002"
_IDENTITY_RESOURCE_ID = (
    f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/example/providers/"
    "Microsoft.ManagedIdentity/userAssignedIdentities/inventory"
)


def _scheduled_job() -> dict[str, object]:
    return {
        "component": "inventory",
        "image": _IMAGE,
        "identity_resource_id": _IDENTITY_RESOURCE_ID,
        "identity_client_id": _CLIENT_ID,
        "command": ["python", "-m", "fdai.delivery.inventory_sync_cli"],
        "args": [],
        "schedule": "* * * * *",
        "suspend": False,
        "deadline_seconds": 900,
        "retry_limit": 1,
        "cpu": "500m",
        "memory": "1Gi",
        "environment": {
            "FDAI_INVENTORY_SCOPES": _SUBSCRIPTION,
            "FDAI_INVENTORY_SOURCES": "arg,arm",
        },
        "secret_environment": {"FDAI_INVENTORY_DSN": "inventory-job"},
    }


def _cronjob() -> dict[str, object]:
    labels = {
        "app.kubernetes.io/name": "inventory",
        "app.kubernetes.io/component": "inventory",
        "app.kubernetes.io/managed-by": "terraform",
        "fdai.io/runtime": "aks",
        "fdai.io/source-commit": _REVISION,
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {
            "name": "inventory",
            "namespace": "fdai-runtime",
            "labels": labels,
        },
        "spec": {
            "schedule": "* * * * *",
            "suspend": False,
            "concurrencyPolicy": "Forbid",
            "successfulJobsHistoryLimit": 3,
            "failedJobsHistoryLimit": 3,
            "jobTemplate": {
                "metadata": {"labels": labels},
                "spec": {
                    "completions": 1,
                    "parallelism": 1,
                    "backoffLimit": 1,
                    "activeDeadlineSeconds": 900,
                    "ttlSecondsAfterFinished": 3600,
                    "template": {
                        "metadata": {
                            "labels": {
                                **labels,
                                "azure.workload.identity/use": "true",
                            }
                        },
                        "spec": {
                            "serviceAccountName": "inventory-job",
                            "automountServiceAccountToken": True,
                            "restartPolicy": "Never",
                            "nodeSelector": {"fdai.io/pool": "runtime"},
                            "securityContext": {
                                "runAsNonRoot": True,
                                "seccompProfile": {"type": "RuntimeDefault"},
                            },
                            "containers": [
                                {
                                    "name": "inventory",
                                    "image": _IMAGE,
                                    "imagePullPolicy": "IfNotPresent",
                                    "command": [
                                        "python",
                                        "-m",
                                        "fdai.delivery.inventory_sync_cli",
                                    ],
                                    "args": [],
                                    "env": [
                                        {
                                            "name": "FDAI_INVENTORY_SCOPES",
                                            "value": _SUBSCRIPTION,
                                        },
                                        {
                                            "name": "FDAI_INVENTORY_SOURCES",
                                            "value": "arg,arm",
                                        },
                                        {
                                            "name": "FDAI_INVENTORY_DSN",
                                            "valueFrom": {
                                                "secretKeyRef": {
                                                    "name": "inventory-job",
                                                    "key": "FDAI_INVENTORY_DSN",
                                                }
                                            },
                                        },
                                    ],
                                    "resources": {
                                        "requests": {"cpu": "500m", "memory": "1Gi"},
                                        "limits": {"cpu": "500m", "memory": "1Gi"},
                                    },
                                    "securityContext": {
                                        "allowPrivilegeEscalation": False,
                                        "runAsNonRoot": True,
                                        "capabilities": {"drop": ["ALL"]},
                                    },
                                    "volumeMounts": [
                                        {
                                            "name": "secrets",
                                            "mountPath": "/mnt/secrets-store",
                                            "readOnly": True,
                                        }
                                    ],
                                }
                            ],
                            "volumes": [
                                {
                                    "name": "secrets",
                                    "csi": {
                                        "driver": "secrets-store.csi.k8s.io",
                                        "readOnly": True,
                                        "volumeAttributes": {
                                            "secretProviderClass": "inventory-job"
                                        },
                                    },
                                }
                            ],
                        },
                    },
                },
            },
        },
    }


def _template_digest() -> str:
    return protected_cronjob_template_digest(
        _scheduled_job(),
        template_name="inventory",
        namespace="fdai-runtime",
        source_revision=_REVISION,
    )


def _identity_binding() -> dict[str, object]:
    return protected_service_account_binding(
        _scheduled_job(),
        template_name="inventory",
        namespace="fdai-runtime",
        tenant_id=_TENANT,
        subscription_id=_SUBSCRIPTION,
    )


def _service_account() -> dict[str, object]:
    return {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {
            "name": "inventory-job",
            "namespace": "fdai-runtime",
            "annotations": {
                "azure.workload.identity/client-id": _CLIENT_ID,
                "azure.workload.identity/tenant-id": _TENANT,
            },
        },
    }


def _context(kubeconfig: Path) -> dict[str, object]:
    return {
        "kubeconfig": str(kubeconfig),
        "source_commit": _REVISION,
        "target_binding": _TARGET,
        "tenant_id": _TENANT,
        "subscription_id": _SUBSCRIPTION,
        "protected_aks_job_template_digests": {"inventory": _template_digest()},
        "protected_aks_job_identity_bindings": {"inventory": _identity_binding()},
    }


def _kwargs() -> dict[str, object]:
    return {
        "template_name": "inventory",
        "purpose": "inventory",
        "expected_container_name": "inventory",
        "expected_image": _IMAGE,
        "expected_command": ("python", "-m", "fdai.delivery.inventory_sync_cli"),
        "expected_service_account": "inventory-job",
        "args": ("--initial",),
        "environment": {"FDAI_INVENTORY_PROGRESS_RUN_ID": f"genesis.{_REVISION}"},
        "require_suspended": False,
        "timeout_seconds": 30,
    }


def _private_kubeconfig(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    path = tmp_path / "aks.kubeconfig"
    path.write_text("config", encoding="utf-8")
    path.chmod(0o600)
    return path


def _expected_execution() -> object:
    return materialize_cronjob_execution(
        _cronjob(),
        purpose="inventory",
        source_revision=_REVISION,
        target_binding=_TARGET,
        expected_template_name="inventory",
        expected_container_name="inventory",
        expected_image=_IMAGE,
        expected_command=("python", "-m", "fdai.delivery.inventory_sync_cli"),
        expected_service_account="inventory-job",
        args=("--initial",),
        environment={"FDAI_INVENTORY_PROGRESS_RUN_ID": f"genesis.{_REVISION}"},
        require_suspended=False,
        protected_template_digest=_template_digest(),
        protected_identity_binding_digest=str(_identity_binding()["binding_digest"]),
    )


def _terminal_job() -> dict[str, object]:
    expected = _expected_execution()
    job = copy.deepcopy(expected.manifest)
    job["status"] = {
        "failed": 2,
        "succeeded": 1,
        "conditions": [{"type": "Complete", "status": "True"}],
        "completionTime": "2026-09-27T01:00:00Z",
    }
    return job


def test_starts_content_addressed_job_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kubeconfig = _private_kubeconfig(tmp_path)
    responses = iter(
        (
            json.dumps(_cronjob()),
            json.dumps(_service_account()),
            "",
            json.dumps(_terminal_job()),
        )
    )
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        standalone_aks_job_execution,
        "_capture",
        lambda *_args, **_kwargs: next(responses),
    )
    monkeypatch.setattr(
        standalone_aks_job_execution,
        "_run",
        lambda command, **_kwargs: commands.append(command),
    )

    result = standalone_aks_job_execution.execute_aks_cronjob_once(
        _context(kubeconfig),
        tmp_path,
        **_kwargs(),  # type: ignore[arg-type]
    )

    assert result.name.startswith("fdai-inventory-")
    assert (
        result.manifest["metadata"]["annotations"]["fdai.io/identity-binding-digest"]
        == _identity_binding()["binding_digest"]
    )
    assert commands[0][1:3] == ("create", "--filename")
    assert (tmp_path / f"{result.name}.prepared.json").is_file()
    assert (tmp_path / f"{result.name}.dispatch-intent.json").is_file()
    assert (tmp_path / f"{result.name}.dispatched.json").is_file()
    terminal = json.loads((tmp_path / f"{result.name}.terminal.json").read_text())
    assert terminal["outcome"] == "succeeded"
    assert terminal["terminal_evidence"]["failed"] == 2


def test_protected_identity_binding_retains_uami_and_tenant() -> None:
    binding = _identity_binding()

    assert binding["identity_client_id"] == _CLIENT_ID
    assert binding["identity_resource_id"] == _IDENTITY_RESOURCE_ID.casefold()
    assert binding["tenant_id"] == _TENANT
    assert binding["subscription_id"] == _SUBSCRIPTION


def test_protected_identity_resource_cannot_cross_subscription(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kubeconfig = _private_kubeconfig(tmp_path)
    context = _context(kubeconfig)
    binding = dict(_identity_binding())
    binding["identity_resource_id"] = (
        "/subscriptions/00000000-0000-0000-0000-000000000099/resourcegroups/example/"
        "providers/microsoft.managedidentity/userassignedidentities/inventory"
    )
    material = {key: item for key, item in binding.items() if key != "binding_digest"}
    binding["binding_digest"] = canonical_digest(material)
    context["protected_aks_job_identity_bindings"] = {"inventory": binding}
    responses = iter((json.dumps(_cronjob()),))
    monkeypatch.setattr(
        standalone_aks_job_execution,
        "_capture",
        lambda *_args, **_kwargs: next(responses),
    )

    with pytest.raises(ValueError, match="identity binding differs"):
        standalone_aks_job_execution.execute_aks_cronjob_once(
            context,
            tmp_path,
            **_kwargs(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("drift", ["client", "tenant", "extra"])
def test_service_account_identity_drift_blocks_before_job_read(
    drift: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kubeconfig = _private_kubeconfig(tmp_path)
    service_account = _service_account()
    annotations = service_account["metadata"]["annotations"]  # type: ignore[index]
    if drift == "client":
        annotations["azure.workload.identity/client-id"] = "f" * 36
    elif drift == "tenant":
        annotations["azure.workload.identity/tenant-id"] = "e" * 36
    else:
        annotations["azure.workload.identity/use"] = "true"
    responses = iter((json.dumps(_cronjob()), json.dumps(service_account)))
    monkeypatch.setattr(
        standalone_aks_job_execution,
        "_capture",
        lambda *_args, **_kwargs: next(responses),
    )
    monkeypatch.setattr(
        standalone_aks_job_execution,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("identity drift dispatched a Job"),
    )

    with pytest.raises(ValueError, match="ServiceAccount identity binding changed"):
        standalone_aks_job_execution.execute_aks_cronjob_once(
            _context(kubeconfig),
            tmp_path,
            **_kwargs(),  # type: ignore[arg-type]
        )


def test_dispatch_intent_can_dispatch_after_pre_create_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kubeconfig = _private_kubeconfig(tmp_path)
    responses = iter(
        (
            json.dumps(_cronjob()),
            json.dumps(_service_account()),
            "",
            json.dumps(_cronjob()),
            json.dumps(_service_account()),
            "",
            json.dumps(_terminal_job()),
        )
    )
    crashed = False
    commands: list[tuple[str, ...]] = []

    def crash_before_create(command: tuple[str, ...], **_kwargs: object) -> None:
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("simulated pre-create crash")
        commands.append(command)

    monkeypatch.setattr(
        standalone_aks_job_execution,
        "_capture",
        lambda *_args, **_kwargs: next(responses),
    )
    monkeypatch.setattr(
        standalone_aks_job_execution,
        "_run",
        crash_before_create,
    )
    with pytest.raises(RuntimeError, match="pre-create crash"):
        standalone_aks_job_execution.execute_aks_cronjob_once(
            _context(kubeconfig),
            tmp_path,
            **_kwargs(),  # type: ignore[arg-type]
        )

    result = standalone_aks_job_execution.execute_aks_cronjob_once(
        _context(kubeconfig),
        tmp_path,
        **_kwargs(),  # type: ignore[arg-type]
    )

    assert len(commands) == 1
    assert (tmp_path / f"{result.name}.terminal.json").is_file()


def test_stale_dispatch_intent_does_not_recreate_a_possibly_ttl_deleted_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kubeconfig = _private_kubeconfig(tmp_path)
    responses = iter(
        (
            json.dumps(_cronjob()),
            json.dumps(_service_account()),
            "",
            json.dumps(_cronjob()),
            json.dumps(_service_account()),
            "",
        )
    )
    create_attempts = 0

    def crash_before_create(*_args: object, **_kwargs: object) -> None:
        nonlocal create_attempts
        create_attempts += 1
        if create_attempts == 1:
            raise RuntimeError("simulated pre-create crash")
        pytest.fail("stale dispatch intent recreated a Job")

    monkeypatch.setattr(
        standalone_aks_job_execution,
        "_capture",
        lambda *_args, **_kwargs: next(responses),
    )
    monkeypatch.setattr(standalone_aks_job_execution, "_run", crash_before_create)
    with pytest.raises(RuntimeError, match="pre-create crash"):
        standalone_aks_job_execution.execute_aks_cronjob_once(
            _context(kubeconfig),
            tmp_path,
            **_kwargs(),  # type: ignore[arg-type]
        )
    intent_path = next(tmp_path.glob("*.dispatch-intent.json"))
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["recorded_at"] = (
        (datetime.now(tz=UTC) - timedelta(seconds=3_700)).isoformat().replace("+00:00", "Z")
    )
    material = {key: item for key, item in intent.items() if key != "checkpoint_digest"}
    intent["checkpoint_digest"] = canonical_digest(material)
    intent_path.write_text(json.dumps(intent), encoding="utf-8")

    with pytest.raises(ValueError, match="terminal TTL deletion"):
        standalone_aks_job_execution.execute_aks_cronjob_once(
            _context(kubeconfig),
            tmp_path,
            **_kwargs(),  # type: ignore[arg-type]
        )

    assert create_attempts == 1


def test_create_timeout_reconciles_exact_created_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kubeconfig = _private_kubeconfig(tmp_path)
    responses = iter(
        (
            json.dumps(_cronjob()),
            json.dumps(_service_account()),
            "",
            json.dumps(_terminal_job()),
        )
    )

    monkeypatch.setattr(
        standalone_aks_job_execution,
        "_capture",
        lambda *_args, **_kwargs: next(responses),
    )

    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(("kubectl", "create"), 60)

    monkeypatch.setattr(standalone_aks_job_execution, "_run", timeout)

    result = standalone_aks_job_execution.execute_aks_cronjob_once(
        _context(kubeconfig),
        tmp_path,
        **_kwargs(),  # type: ignore[arg-type]
    )

    assert (tmp_path / f"{result.name}.terminal.json").is_file()


def test_ambiguous_create_timeout_never_redispatches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kubeconfig = _private_kubeconfig(tmp_path)
    responses = iter(
        (
            json.dumps(_cronjob()),
            json.dumps(_service_account()),
            "",
            "",
            json.dumps(_cronjob()),
            json.dumps(_service_account()),
            "",
        )
    )
    create_attempts = 0

    monkeypatch.setattr(
        standalone_aks_job_execution,
        "_capture",
        lambda *_args, **_kwargs: next(responses),
    )

    def timeout(*_args: object, **_kwargs: object) -> None:
        nonlocal create_attempts
        create_attempts += 1
        raise subprocess.TimeoutExpired(("kubectl", "create"), 60)

    monkeypatch.setattr(standalone_aks_job_execution, "_run", timeout)

    with pytest.raises(ValueError, match="ambiguous outcome"):
        standalone_aks_job_execution.execute_aks_cronjob_once(
            _context(kubeconfig),
            tmp_path,
            **_kwargs(),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="create outcome remains ambiguous"):
        standalone_aks_job_execution.execute_aks_cronjob_once(
            _context(kubeconfig),
            tmp_path,
            **_kwargs(),  # type: ignore[arg-type]
        )

    assert create_attempts == 1


def test_terminal_checkpoint_survives_ttl_deleted_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kubeconfig = _private_kubeconfig(tmp_path)
    first_responses = iter(
        (
            json.dumps(_cronjob()),
            json.dumps(_service_account()),
            "",
            json.dumps(_terminal_job()),
        )
    )
    monkeypatch.setattr(
        standalone_aks_job_execution,
        "_capture",
        lambda *_args, **_kwargs: next(first_responses),
    )
    monkeypatch.setattr(standalone_aks_job_execution, "_run", lambda *_args, **_kwargs: None)
    expected = standalone_aks_job_execution.execute_aks_cronjob_once(
        _context(kubeconfig),
        tmp_path,
        **_kwargs(),  # type: ignore[arg-type]
    )

    replay_commands: list[tuple[str, ...]] = []
    replay_responses = iter((json.dumps(_cronjob()), json.dumps(_service_account())))
    monkeypatch.setattr(
        standalone_aks_job_execution,
        "_capture",
        lambda command, **_kwargs: replay_commands.append(command) or next(replay_responses),
    )
    monkeypatch.setattr(
        standalone_aks_job_execution,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("terminal replay redispatched the Job"),
    )

    assert (
        standalone_aks_job_execution.execute_aks_cronjob_once(
            _context(kubeconfig),
            tmp_path,
            **_kwargs(),  # type: ignore[arg-type]
        )
        == expected
    )
    assert len(replay_commands) == 2
    assert replay_commands[0][2] == "cronjob"
    assert replay_commands[1][2] == "serviceaccount"
